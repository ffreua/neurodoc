import hashlib
import logging
import secrets
from urllib.parse import quote_plus

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from patients.contacts import SELF_RELATIONSHIP, authorized_document_contacts

from . import access
from .email import EmailSendFailed, send_email
from .models import Delivery, DeliveryAttempt, DeliveryAttemptOutcome, DeliveryChannel, DeliveryStatus
from .reconciliation import POLL_OFFSETS_MINUTES
from .smsdev import SmsChannelDisabled, SmsSendFailed, send_sms

logger = logging.getLogger(__name__)

DOCUMENT_MESSAGE = 'Seu documento está disponível no NeuroDoc. Acesse o link para visualizá-lo com segurança.'

#: O SMS tem outro texto, e **sem acento**. Não é desleixo: é o que faz a
#: mensagem existir.
#:
#: Um SMS só cabe em 160 caracteres enquanto estiver em GSM-7. Basta um
#: acento para a operadora passar a mensagem inteira para UCS-2, e aí o
#: segmento cai para **70**. Com um link de 70 caracteres no corpo, a
#: versão acentuada não cabe em segmento nenhum — e cada segmento extra é
#: uma mensagem a mais cobrada da clínica.
#:
#: O texto de e-mail continua acentuado e completo: lá não há limite, e
#: ler "voce recebera" num e-mail é o desleixo que o SMS não pode evitar.
SMS_DOCUMENT_TEMPLATE = (
    'Seu documento do NeuroDoc: {link} '
    'Informe os 4 ultimos digitos do CPF do paciente para abrir.'
)

#: A versão mínima, para quando a instalação tem um domínio longo.
#: Perder a explicação do CPF é ruim; mandar duas mensagens cobradas, ou
#: não mandar nenhuma, é pior.
SMS_DOCUMENT_TEMPLATE_CURTO = 'Documento NeuroDoc: {link} Use os 4 ultimos digitos do CPF.'

#: O teto de um segmento. Mora aqui, e não só em `smsdev`, porque é aqui
#: que a mensagem é montada — e foi a montagem que estourou: a mensagem de
#: documento tinha **221 caracteres**, 61 acima do limite, e derrubava a
#: entrega inteira com um `ValueError` que ninguém tratava.
SMS_SEGMENTO = 160
#: O lembrete se apresenta pela **clinica**, e nao pelo NeuroDoc.
#:
#: O paciente nao sabe o que e NeuroDoc -- ele conhece o consultorio onde
#: marcou. "Lembrete NeuroDoc" chega como mensagem de remetente
#: desconhecido, que e o que se apaga sem ler, e ainda expoe o nome do
#: fornecedor onde deveria estar o de quem atende.
#:
#: Tambem nao pede resposta, pela mesma razao do template de confirmacao:
#: ninguem le resposta de SMS.
REMINDER_MESSAGE_TEMPLATE = (
    '{clinic}: lembrete de consulta em {when}. Nao responda; '
    'duvidas, ligue para a clinica.'
)


def _still_valid(contact):
    return contact.valid_until is None or contact.valid_until > timezone.now()


def _eligible_document_contacts(patient):
    return [
        c for c in authorized_document_contacts(patient).all()
        if _still_valid(c) and (
            (c.email_enabled and c.verified_email_at and c.email)
            or (c.sms_enabled and c.verified_phone_at and c.phone)
        )
    ]


def _eligible_reminder_contacts(patient):
    return [
        c for c in patient.contacts.all()
        if _still_valid(c) and (
            (c.email_enabled and c.verified_email_at and c.email)
            or (c.sms_enabled and c.verified_phone_at and c.phone)
        )
    ]


def _proprio_primeiro(contacts):
    """Os contatos com o do próprio paciente na frente.

    É a ordem que decide quem fica quando dois contatos têm o mesmo
    endereço (`_repetido`): a entrega fica registrada no contato do
    paciente, e não no do parente que por acaso deu o mesmo e-mail.
    """
    return sorted(contacts, key=lambda c: c.relationship != SELF_RELATIONSHIP)


def _repetido(vistos, contact, channel):
    """Este endereço já recebeu esta mensagem neste envio?

    **Um envio por endereço, e não por contato.** A entrega percorre os
    contatos do paciente, e nada impede dois deles com o mesmo e-mail -- o
    paciente e a mãe que usa a caixa dele, ou o contato digitado de novo.
    Cada um tem a sua `Delivery`, com chave própria, e por isso a
    idempotência não pegava: o mesmo cancelamento chegava duas vezes à
    mesma caixa (relatado em 2026-10-15, testando o servidor SMTP da
    clínica). Telefone compara pelos dígitos, e-mail sem caixa nem espaço.
    """
    if channel == DeliveryChannel.EMAIL:
        endereco = (contact.email or '').strip().lower()
    else:
        endereco = ''.join(ch for ch in (contact.phone or '') if ch.isdigit())
    chave = (channel, endereco)
    if chave in vistos:
        return True
    vistos.add(chave)
    return False


def _channels_for(contact):
    channels = []
    if contact.email_enabled and contact.verified_email_at and contact.email:
        channels.append(DeliveryChannel.EMAIL)
    if contact.sms_enabled and contact.verified_phone_at and contact.phone:
        channels.append(DeliveryChannel.SMS)
    return channels


def _notify_no_contact(patient, o_que):
    """Ninguém neste paciente pode receber a mensagem.

    O aviso dizia "Entrega pendente — verifique o cadastro de contato do
    paciente" e apontava para o horário ou o documento. Quem o recebia
    tinha de adivinhar qual paciente e ir procurá-lo na lista; e o destino,
    quando existisse, não era onde a correção acontece.

    Agora nomeia o paciente, diz o que ficou por entregar, e leva à ficha
    — que é onde se cadastra telefone e e-mail.

    Vai para quem administra o cadastro do paciente (`PATIENT_ADMIN`), que
    é quem pode de fato resolver: a secretária, o gestor, o dono. Por
    capacidade e não por papel, porque é a capacidade que decide se a ficha
    abre.
    """
    from notifications.services import notify_capability, patient_context
    from tenancy.permissions import Capability

    notify_capability(
        patient.tenant, Capability.PATIENT_ADMIN, kind='delivery_pending_contact',
        sanitized_title=f'Sem contato para entregar: {o_que}',
        target_type='patient', target_id=patient.id,
        context=patient_context(patient, pending=o_que),
    )


def _record_attempt(delivery, outcome, provider_code='', sanitized_error=''):
    attempt_number = delivery.attempts.count() + 1
    DeliveryAttempt.objects.create(
        tenant=delivery.tenant, delivery=delivery, attempt_number=attempt_number,
        started_at=timezone.now(), ended_at=timezone.now(), outcome=outcome,
        provider_code=provider_code, sanitized_error=sanitized_error[:255],
    )


def _send(delivery, message, subject='Notificação NeuroDoc', physician_membership=None):
    # Clínica desligada não fala com paciente em nome dela.
    #
    # Quase tudo que envia nasce de um POST, e o middleware já recusa POST
    # numa organização suspensa. O que escapa é o que foi enfileirado
    # **antes** do desligamento — uma campanha em lotes, um lembrete
    # agendado — e continuaria saindo por dias, assinado por uma clínica
    # que já não tem acesso ao próprio sistema.
    #
    # Os dois canais passam por aqui, então a verificação é uma só.
    from tenancy.models import Tenant, TenantStatus

    # A posse do envio vem antes de tudo. Ver `DeliveryStatus.SENDING`:
    # quem não conseguir passar a entrega de "na fila" a "enviando" não
    # envia -- outro processo já está enviando, ou já enviou.
    #
    # Fora de transação -- o caso do despachante, que deixou de abrir uma,
    # e da confirmação manual, que também deixou (auditoria de 2026-10) --,
    # o `UPDATE` vale para as outras conexões na hora. Dentro de uma, o
    # outro processo espera a trava da linha e a encontra já resolvida.
    # Nos dois casos, um envio só.
    if Delivery.objects.filter(
        id=delivery.id, status=DeliveryStatus.PENDING,
    ).update(status=DeliveryStatus.SENDING) != 1:
        delivery.refresh_from_db(fields=['status', 'provider_id', 'next_attempt_at'])
        return
    delivery.status = DeliveryStatus.SENDING

    ativa = Tenant.objects.filter(
        id=delivery.tenant_id, status=TenantStatus.ACTIVE,
    ).exists()
    if not ativa:
        delivery.status = DeliveryStatus.CHANNEL_UNAVAILABLE
        delivery.save(update_fields=['status'])
        _record_attempt(delivery, DeliveryAttemptOutcome.FAILED, sanitized_error='tenant_inactive')
        return

    try:
        if delivery.channel == DeliveryChannel.EMAIL:
            send_email(
                delivery.contact.email, subject, message,
                physician_membership=physician_membership,
            )
        else:
            result = send_sms(
                delivery.contact.phone, message, refer=str(delivery.id),
                tenant_id=delivery.tenant_id,
            )
            delivery.provider_id = str(result.get('id', ''))[:100]
    except SmsChannelDisabled:
        # `CHANNEL_UNAVAILABLE`, e nao `NO_CONTACT`: o paciente tem
        # telefone, quem nao pode enviar e o sistema. Gravado como "sem
        # contato", isto mandava a clinica conferir a ficha do paciente
        # -- que estava certa -- enquanto a causa era credencial.
        delivery.status = DeliveryStatus.CHANNEL_UNAVAILABLE
        delivery.save(update_fields=['status'])
        _record_attempt(delivery, DeliveryAttemptOutcome.FAILED, sanitized_error='channel_disabled')
        return
    except (EmailSendFailed, SmsSendFailed) as exc:
        # De volta à fila, como era antes da posse: falha de transporte é
        # tentativa registrada, e a entrega continua reenviável.
        delivery.status = DeliveryStatus.PENDING
        delivery.save(update_fields=['status'])
        _record_attempt(delivery, DeliveryAttemptOutcome.FAILED, sanitized_error=exc.__class__.__name__)
        return
    except Exception as exc:
        # Rede final, e ela existe por um caso concreto: a mensagem de
        # documento passou de 160 caracteres, `send_sms` levantou
        # `ValueError`, ninguem tratou, e o medico viu `Server Error (500)`
        # com o documento ja assinado -- perdendo junto o e-mail, que a
        # transacao comum desfez.
        #
        # Entrega e **efeito colateral** do que o sistema faz, nunca a
        # coisa em si. Uma falha aqui tem de virar linha vermelha na lista
        # de entregas, para alguem reenviar; nunca uma tela de erro sobre
        # uma operacao que ja deu certo.
        delivery.status = DeliveryStatus.FAILED
        delivery.save(update_fields=['status'])
        _record_attempt(
            delivery, DeliveryAttemptOutcome.FAILED,
            sanitized_error=exc.__class__.__name__,
        )
        logger.exception(
            'communications: falha inesperada ao entregar %s por %s',
            delivery.id, delivery.channel,
        )
        return
    delivery.status = DeliveryStatus.ACCEPTED
    if delivery.channel == DeliveryChannel.SMS:
        # Email has no DLR-equivalent in this baseline, so ACCEPTED is its
        # final state; only SMS gets polled for a real DELIVERED/FAILED.
        delivery.next_attempt_at = timezone.now() + timezone.timedelta(minutes=POLL_OFFSETS_MINUTES[0])
    delivery.save(update_fields=['status', 'provider_id', 'next_attempt_at'])
    _record_attempt(delivery, DeliveryAttemptOutcome.ACCEPTED)


def deliver_document(document, force_new_link=False, envio_id=None):
    """Manda o documento aos contatos autorizados do paciente.

    **A transação é por entrega, e não em volta de todas.** Era em volta
    de todas, e isso transformava uma falha de um canal no desaparecimento
    dos outros: quando o SMS estourou por exceder o segmento, o `rollback`
    levou junto a linha do e-mail que já tinha sido aceito — o paciente
    não recebia nada, e a lista de entregas não mostrava sequer a
    tentativa. Um canal que falha tem de aparecer falhando, sozinho.

    `force_new_link=False` é a entrega automática da emissão, e é
    idempotente: o evento da fila pode chegar duas vezes, e a segunda não
    pode mandar um segundo SMS ao paciente.

    `force_new_link=True` é o reenvio pedido por alguém na tela. Ali o
    contrário é que vale — a mensagem não chegou, ou o link expirou, e
    repetir é justamente o pedido. Cada reenvio **revoga o link anterior**:
    dois links vivos para o mesmo documento dobram a superfície e não
    servem a nada, e revogar é também a saída quando se suspeita que o
    link foi parar em mãos erradas.

    **Mas a repetição do mesmo reenvio não é outro reenvio** (auditoria de
    2026-10, C2). A tarefa tenta de novo quando algo estoura, e uma falha
    depois da primeira mensagem fazia a segunda volta revogar o link que
    acabara de chegar ao paciente e mandar outro: dois SMS, o primeiro com
    link morto. Com `envio_id` (o id da tarefa, que a nova tentativa
    preserva), a chave da entrega deixa de ser sorteada e passa a ser a
    marca do pedido: a repetição encontra o que já saiu e não envia de novo,
    e só revoga se nada deste pedido foi gravado ainda.
    """
    contacts = _eligible_document_contacts(document.patient)
    if not contacts:
        numero = document.document_number or 'sem número'
        _notify_no_contact(
            document.patient,
            f'{document.get_kind_display().lower()} {numero}',
        )
        return []

    marca = marca_do_envio(envio_id) if force_new_link and envio_id is not None else None
    ja_comecou = marca is not None and Delivery.objects.filter(
        document=document, idempotency_key__endswith=f':{marca}',
    ).exists()
    if force_new_link and not ja_comecou:
        # Uma vez, antes de qualquer link novo. Ficava dentro do laço, e a
        # segunda volta revogava o link que a primeira acabara de mandar:
        # no reenvio para e-mail e SMS, uma das duas mensagens chegava com
        # link morto (auditoria de 2026-10-09, ND-1121-003). Revogar aqui
        # fecha os links de antes do reenvio, que é a função dele, e deixa
        # vivos os deste lote. Na repetição do mesmo pedido, a revogação
        # já foi feita, e refazê-la mataria os links deste lote.
        with transaction.atomic():
            access.revoke_previous_tokens(document)

    deliveries = []
    vistos = set()
    for contact in _proprio_primeiro(contacts):
        for channel in _channels_for(contact):
            if _repetido(vistos, contact, channel):
                continue
            idem_key = f'document:{document.id}:{contact.id}:{channel}'
            if force_new_link:
                # Chave nova a cada reenvio: a restrição de unicidade
                # existe para o evento repetido não duplicar o envio, e
                # reaproveitá-la aqui faria o reenvio virar um silêncio.
                #
                # Sufixo aleatório, e não o relógio. Com precisão de
                # segundos, dois reenvios dentro do mesmo segundo caíam na
                # mesma chave: o segundo não enviava nada, não trocava o
                # link, e a tela ainda dizia que tinha enviado.
                #
                # Com a marca do pedido, a chave se repete só na repetição
                # do mesmo pedido -- que é quando ela deve se repetir.
                idem_key = f'{idem_key}:{marca or secrets.token_hex(4)}'
            # O token e gravado numa transacao curta, e a mensagem so sai
            # **depois** que ela fecha.
            #
            # Enviar dentro da transacao foi o que produziu o link que nao
            # valia: o e-mail saia com um token que ainda nao estava
            # visivel para outra conexao e que, se a transacao falhasse
            # adiante, nunca chegava a existir. O paciente recebia a
            # mensagem e a tela dizia "invalido ou expirado".
            #
            # O e-mail tambem e protegido por `on_commit` no backend; o SMS
            # nao passa por backend nenhum, e so esta ordem o cobre.
            raw_token = None
            with transaction.atomic():
                delivery, created = Delivery.objects.get_or_create(
                    tenant=document.tenant, idempotency_key=idem_key,
                    defaults={
                        'document': document, 'contact': contact, 'channel': channel,
                        'event_version': document.version,
                    },
                )
                if created or delivery.status == DeliveryStatus.PENDING:
                    token, raw_token = access.create_access_token(document, contact)
            if raw_token is not None:
                link = f'{settings.PUBLIC_BASE_URL}/d/{raw_token}/'
                _send(delivery, _document_message(document, link, delivery.channel))
            deliveries.append(delivery)
    return deliveries


def _document_message(document, link, channel=None):
    """O texto que o paciente recebe, no formato do canal.

    Sem diagnóstico, sem medicação, sem o tipo do documento: a mensagem
    aparece na tela bloqueada do celular e é lida por quem estiver por
    perto. "Documento" basta para a pessoa saber que é dela e clicar.

    Dizer de antemão o que será pedido evita a ligação para a recepção —
    quem chega ao link já sabe que precisa do CPF em mãos.

    **Um texto por canal, e foi a falta disso que quebrou a entrega.** A
    mesma frase servia aos dois: no e-mail ficava bem, e no SMS dava 221
    caracteres contra um limite de 160. O `ValueError` que isso levantava
    não era tratado em lugar nenhum e subia até a view — o médico via
    `Server Error (500)` com o documento já assinado, e nem o e-mail saía,
    porque a transação que envolvia os dois canais era desfeita junto.
    """
    if channel != DeliveryChannel.SMS:
        return (
            f'{DOCUMENT_MESSAGE} {link} '
            'Para abrir, informe os 4 últimos dígitos do CPF do paciente.'
        )
    return _sms_document_message(link)


def _sms_document_message(link):
    """A mensagem de SMS que cabe num segmento.

    Escolhe entre a completa e a mínima conferindo o tamanho **com o link
    real**, e não por contagem feita a mão: o link depende de
    `PUBLIC_BASE_URL`, que muda por instalação, e uma contagem fixa
    quebraria na primeira que tivesse um domínio mais longo.

    Se nem a mínima couber, devolve a mínima mesmo assim: quem recusa é
    `smsdev.send_sms`, com `SmsSendFailed` — uma falha registrada na
    entrega, que a tela mostra, e não uma exceção solta.
    """
    completa = SMS_DOCUMENT_TEMPLATE.format(link=link)
    if len(completa) <= SMS_SEGMENTO:
        return completa
    return SMS_DOCUMENT_TEMPLATE_CURTO.format(link=link)


#: Estados em que um lembrete ainda faz sentido. Fora deles o paciente
#: já chegou, já foi atendido, faltou ou teve a consulta cancelada.
LEMBRETE_ESTADOS_VALIDOS = ('scheduled', 'confirmed')


def deliver_appointment_reminder(appointment, event_version):
    """Lembra o paciente do horário marcado.

    **O estado de agora manda sobre o evento de então** -- a mesma regra
    de `deliver_appointment_notice`, que o lembrete não tinha. Cancelar
    derruba os lembretes ainda pendentes (`invalidate_stale_reminders`),
    mas um que o despachante já tinha reclamado escapava, e saía
    "lembrete de consulta" para consulta cancelada (auditoria de
    2026-10-09, A5). Consulta que já começou também não vira lembrete:
    é o caso do evento atrasado por um worker parado.

    A versão do evento **não** é comparada com a do agendamento, apesar
    de parecer o óbvio: `row_version` sobe também ao confirmar e ao
    trocar o tipo, que não reagendam lembrete nenhum -- comparar
    calaria o lembrete de toda consulta confirmada. Quem descobre o
    lembrete substituído por uma remarcação é o consumidor
    (`scheduling.handlers`), olhando se há evento mais novo.

    Sem `atomic` em volta, de propósito: cada entrega se grava sozinha.
    Dentro de uma transação, uma falha ao pôr o e-mail na fila acontecia
    **depois** do commit que já dizia "aceita", e a mensagem sumia com a
    lista de entregas afirmando o contrário. Fora dela a falha cai em
    `_send`, que a registra na própria entrega.
    """
    if appointment.status not in LEMBRETE_ESTADOS_VALIDOS:
        return []
    if appointment.starts_at <= timezone.now():
        return []
    contacts = _eligible_reminder_contacts(appointment.patient)
    if not contacts:
        from django.utils import timezone as _tz

        quando = _tz.localtime(appointment.starts_at).strftime('%d/%m às %H:%M')
        _notify_no_contact(appointment.patient, f'lembrete do horário de {quando}')
        return []

    # `localtime`, e nao `starts_at` cru: aquele imprime em UTC, e o
    # lembrete chegava com o horario deslocado tres horas -- o paciente
    # aparecendo cedo ou perdendo a consulta, com a mensagem "certa".
    when = timezone.localtime(appointment.starts_at).strftime('%d/%m às %H:%M')
    clinic = (
        appointment.tenant.trade_name or appointment.tenant.legal_name or 'Clinica'
    )[:24]
    message = _encurtar_para_sms(
        REMINDER_MESSAGE_TEMPLATE, clinic, '', when, '',
    )
    deliveries = []
    vistos = set()
    for contact in _proprio_primeiro(contacts):
        for channel in _channels_for(contact):
            if _repetido(vistos, contact, channel):
                continue
            idem_key = f'reminder:{appointment.id}:{event_version}:{contact.id}:{channel}'
            delivery, created = Delivery.objects.get_or_create(
                tenant=appointment.tenant, idempotency_key=idem_key,
                defaults={
                    'appointment': appointment, 'contact': contact, 'channel': channel,
                    'event_version': event_version,
                },
            )
            if created or delivery.status == DeliveryStatus.PENDING:
                _send(
                    delivery, message,
                    physician_membership=appointment.physician_membership,
                )
            deliveries.append(delivery)
    return deliveries


# --------------------------------------------------------------------------
# Lembrete de retorno previsto
# --------------------------------------------------------------------------

#: Aviso de que o retorno se aproxima. **Só por e-mail**, e não é economia.
#:
#: Confirmação de consulta é transacional: a pessoa marcou, o sistema
#: confirma. **Este aviso não é.** Não existe consulta marcada -- a clínica
#: procura o paciente para que uma exista. A leitura que sustenta o envio é
#: continuidade do cuidado (LGPD art. 11, II, "f" -- tutela da saúde por
#: profissional de saúde), e é ela que **dispensa consentimento**. A leitura
#: que não sustenta é captação de paciente, que exigiria opt-in específico.
#:
#: A diferença mora no texto, e por isso ele está escrito assim: informa
#: que o acompanhamento está previsto e diz como agendar. Não convida, não
#: lamenta ausência, não oferece nada. "Sentimos sua falta, agende já" é a
#: mesma mensagem do outro lado da linha.
#:
#: Por e-mail e não por SMS por três razões que se somam: o e-mail carrega
#: descadastro, cabe o texto inteiro, e não custa por mensagem -- disparo
#: recorrente para a base inteira em SMS vira conta.
RETURN_EMAIL_SUBJECT = 'Seu retorno está próximo'
RETURN_EMAIL_TEMPLATE = """Olá, {patient}.

No seu último atendimento ficou previsto um retorno com {doctor}, e ele se
aproxima:

  Retorno previsto para ... {when}

Para marcar, ligue para a clínica{contato}.

Esta mensagem é automática e esta caixa não recebe respostas — se você
responder a este e-mail, ninguém vai ler.

É apenas um aviso de acompanhamento: não contém informação clínica, nem
diagnóstico, nem resultado de exame.
"""


def _contatos_para_aviso(patient):
    """Quem pode receber o aviso de retorno, por e-mail.

    Exige `email_enabled` -- o aviso não é a execução de algo que a pessoa
    pediu, então a autorização dela é o que o sustenta -- e respeita a
    revogação de divulgação: quem pediu para não ser procurado não é
    procurado, ainda que a base legal aqui seja outra. Contato com validade
    vencida sai da lista, como em todo o resto deste módulo.
    """
    return [
        contato for contato in patient.contacts.all()
        if _still_valid(contato)
        and contato.email
        and contato.email_enabled
        and contato.marketing_opt_out_at is None
    ]


@transaction.atomic
def deliver_return_reminder(scheduled_return):
    """Avisa o paciente de que o retorno previsto se aproxima.

    Idempotente por retorno: a chave inclui o identificador do registro, e
    quem chama marca `notified_at`. Os dois juntos são o que impede o
    paciente de receber um e-mail por dia durante as três semanas que
    antecedem a data.

    Devolve a lista de entregas criadas -- vazia quando não há contato
    autorizado, que é informação e não falha: significa que a secretária
    precisa ligar.
    """
    from tenancy.models import ClinicProfile

    paciente = scheduled_return.patient
    contatos = _contatos_para_aviso(paciente)
    if not contatos:
        return []

    perfil = ClinicProfile.objects.filter(tenant_id=scheduled_return.tenant_id).first()
    telefone = (getattr(perfil, 'phone', '') or '').strip()
    medico = scheduled_return.physician_membership.user.get_full_name()
    mensagem = RETURN_EMAIL_TEMPLATE.format(
        patient=paciente.full_name.split()[0],
        doctor=medico,
        when=scheduled_return.due_on.strftime('%d/%m/%Y'),
        contato=f': {telefone}' if telefone else '',
    )

    entregas = []
    vistos = set()
    for contato in _proprio_primeiro(contatos):
        if _repetido(vistos, contato, DeliveryChannel.EMAIL):
            continue
        chave = f'return:{scheduled_return.id}:{contato.id}'
        entrega, criada = Delivery.objects.get_or_create(
            tenant_id=scheduled_return.tenant_id, idempotency_key=chave,
            defaults={
                'contact': contato, 'channel': DeliveryChannel.EMAIL,
                'event_version': 1, 'scheduled_return': scheduled_return,
            },
        )
        if criada or entrega.status == DeliveryStatus.PENDING:
            _send(
                entrega, mensagem, subject=RETURN_EMAIL_SUBJECT,
                physician_membership=scheduled_return.physician_membership,
            )
        entregas.append(entrega)
    return entregas


# --------------------------------------------------------------------------
# Confirmação enviada à mão pela secretaria
# --------------------------------------------------------------------------

#: Teto de um SMS. Acima disso a operadora quebra em duas mensagens, que
#: sao cobradas como duas e podem chegar fora de ordem.
SMS_MAX_CHARS = 160

#: O SMS **informa**, e nao pede resposta.
#:
#: A versao anterior dizia "Confirme respondendo a esta mensagem", e
#: ninguem le resposta de SMS: nao ha webhook, nao ha caixa de entrada, nao
#: ha nada. O paciente respondia "confirmo" e a mensagem morria no
#: provedor -- ele achando que tinha confirmado, a clinica sem saber.
#: Pedir uma acao que o sistema nao recebe e pior que nao pedir nada.
#:
#: "Nao responda" antes do caminho certo, e nao depois: quem le SMS le a
#: primeira linha e age. A instrucao de ligar so vale se a pessoa souber
#: antes que responder nao serve.
CONFIRMATION_SMS_TEMPLATE = (
    '{clinic}: consulta com {doctor} em {when}. Nao responda. '
    'Confirmar ou cancelar: ligue para a clinica{contato}.'
)
CONFIRMATION_EMAIL_SUBJECT = 'Confirmação de consulta'
#: O e-mail tem espaco, entao ele explica o que o SMS so consegue apontar.
#:
#: Duas frases carregam o essencial e estao la de proposito: que a caixa
#: nao recebe resposta -- senao a pessoa responde e espera retorno --, e
#: que o telefone e o unico caminho. A ausencia de informacao clinica
#: continua dita: e-mail nao e canal seguro, e quem recebe precisa saber
#: que nao ha diagnostico ali antes de encaminhar a mensagem para alguem.
#: O corpo do e-mail de horário — marcado, remarcado ou cancelado.
#:
#: **`Local` é o endereço, e não o nome da clínica.** Era o nome, e o
#: paciente recebia "Local: Clínica Tal" — que ele já sabia, e que não o
#: leva a lugar nenhum. O nome continua na primeira linha porque é o que
#: está escrito na porta; o endereço vem embaixo, e é ele que responde à
#: pergunta que a pessoa tem na mão.
#:
#: As quatro informações que a mensagem precisa carregar, e que estão
#: aqui de propósito: **quando**, **com quem**, **onde** e **como falar
#: com a clínica**. As três primeiras o sistema sabe; a quarta depende de
#: a clínica ter preenchido a identidade, e quando não tem, o texto diz
#: isso em vez de calar.
CONFIRMATION_EMAIL_TEMPLATE = """Olá, {patient}.

{abertura}

  Data e hora .... {when}
  Profissional ... {doctor}
  Local .......... {clinic}{address_block}{phone_block}

{instrucao}

Esta mensagem é automática e esta caixa não recebe respostas — se você
responder a este e-mail, ninguém vai ler.

É apenas um aviso sobre o seu horário: não contém informação clínica, nem
diagnóstico, nem resultado de exame.
"""

#: O que muda entre marcar, remarcar e cancelar: a abertura e a
#: instrução. O resto do corpo é o mesmo, e tem de ser — um cancelamento
#: que não repita data, profissional e local deixa o paciente sem saber
#: **qual** consulta foi desmarcada, e quem tem duas marcadas fica pior
#: do que sem aviso nenhum.
ASSUNTOS = {
    'booked': 'Consulta marcada',
    'rescheduled': 'Consulta remarcada',
    'cancelled': 'Consulta cancelada',
}
ABERTURAS = {
    'booked': 'Sua consulta está marcada:',
    'rescheduled': 'Sua consulta foi remarcada. O novo horário é:',
    'cancelled': 'Sua consulta foi CANCELADA. Era esta:',
}
INSTRUCOES = {
    'booked': 'Para confirmar, remarcar ou cancelar, ligue para a clínica{contato}.',
    'rescheduled': 'Se o novo horário não servir, ligue para a clínica{contato}.',
    'cancelled': 'Nenhum horário foi reservado no lugar. Para remarcar, ligue para a '
                 'clínica{contato}.',
}


class NoUsableContact(Exception):
    pass


def confirmation_contacts(appointment, channel):
    """Contatos que podem receber a confirmação por este canal.

    **Não** exige o opt-in nem a verificação que os lembretes automáticos
    exigem, e a diferença é deliberada: aqui a secretária acabou de falar
    com a pessoa e está confirmando o horário no número que ela mesma
    passou. É mensagem transacional, pedida por quem atende, para quem
    marcou — não é disparo automático nem comunicação de marketing.

    Exigir verificação prévia inviabilizaria justamente o caso do
    pré-cadastro por telefone, que é o motivo de o canal existir.

    Continua valendo: contato com validade vencida sai da lista, e a
    mensagem não leva conteúdo clínico.
    """
    field = 'email' if channel == DeliveryChannel.EMAIL else 'phone'
    vistos = set()
    return [
        contact for contact in _proprio_primeiro(appointment.patient.contacts.all())
        if _still_valid(contact) and getattr(contact, field)
        and not _repetido(vistos, contact, channel)
    ]


def _contato_e_endereco_da_clinica(tenant):
    """Telefone, endereço e mapa cadastrados na identidade da clínica.

    Sem ele, a mensagem diz "ligue para a clínica" e a pessoa tem de
    procurar o número. Com ele, a instrução é acionável no próprio texto —
    que é o ponto de mandar a mensagem.

    Nunca levanta: perfil ausente é o estado de uma clínica que acabou de
    nascer, e uma confirmação de horário não deve falhar porque ninguém
    preencheu o cadastro ainda.
    """
    # `ClinicProfile.objects.filter(tenant_id=...)`, e nao um acessor
    # reverso: o relacionamento nao declara `related_name`, entao
    # `tenant.clinic_profile` nao existe -- `getattr` com `None` devolvia
    # sempre `None` e o telefone nunca entrava na mensagem, em silencio. E
    # a forma que o resto do codigo ja usa (`documents/pdf/common.py`).
    from tenancy.models import ClinicProfile

    perfil = ClinicProfile.objects.filter(tenant_id=tenant.id).first()
    if perfil is None:
        return '', '', ''
    telefone = (perfil.phone or '').strip()
    endereco = perfil.address_summary().strip()
    mapa = (
        f'https://www.google.com/maps/search/?api=1&query={quote_plus(endereco)}'
        if endereco else ''
    )
    return telefone, endereco, mapa


def _encurtar_para_sms(modelo, clinic, doctor, when, contato):
    """Monta o SMS garantindo o teto, sem decepar a frase.

    O corte cego `texto[:160]` que existia aqui cabia enquanto o texto
    fosse este; qualquer palavra a mais na redação passava a cortar o fim
    da instrução — e o fim é justamente onde está o que a pessoa deve
    fazer. Uma mensagem que termina em "ligue para a cl" é pior que uma
    sem instrução nenhuma.

    A ordem em que se cede é deliberada, e vai do menos ao mais
    informativo:

    1. o telefone sai — quem marcou consulta tem o número da clínica;
    2. o sobrenome do médico sai, ficando o primeiro nome;
    3. o nome da clínica encolhe — ela já se identifica pelo remetente do
       SMS (`sms_sender_name`).

    O texto fixo nunca é tocado: ele é a mensagem.
    """
    def montar(c, d, ct):
        return modelo.format(clinic=c, doctor=d, when=when, contato=ct)

    for candidato in (
        montar(clinic, doctor, contato),
        montar(clinic, doctor, ''),
        montar(clinic, doctor.split()[0] if doctor else '', ''),
        montar(clinic[:24], doctor.split()[0] if doctor else '', ''),
        montar(clinic[:14], doctor.split()[0] if doctor else '', ''),
    ):
        if len(candidato) <= SMS_MAX_CHARS:
            return candidato
    # Fim de linha: nomes absurdamente longos. Corta, mas no espaço, para
    # a mensagem terminar numa palavra inteira.
    return montar(clinic[:14], doctor.split()[0] if doctor else '', '')[:SMS_MAX_CHARS].rsplit(' ', 1)[0]


def _confirmation_message(appointment, channel, motivo='booked'):
    """O texto que o paciente recebe sobre o horário dele.

    `motivo` escolhe a abertura e a instrução — marcado, remarcado ou
    cancelado. O miolo (quando, com quem, onde) é o mesmo nos três de
    propósito: um cancelamento sem esses dados não diz **qual** consulta
    caiu, e quem tem duas marcadas fica pior do que sem aviso.
    """
    tenant = appointment.tenant
    clinic = (tenant.trade_name or tenant.legal_name or 'Clinica')[:40]
    doctor = (
        appointment.physician_membership.user.get_full_name()
        or appointment.physician_membership.user.email
    )
    telefone, endereco, mapa = _contato_e_endereco_da_clinica(tenant)
    when = timezone.localtime(appointment.starts_at).strftime('%d/%m/%Y às %H:%M')
    if channel == DeliveryChannel.EMAIL:
        if endereco:
            address_block = (
                f'\n                   {endereco}'
                f'\n  Como chegar .... {mapa}'
            )
        else:
            # Sem endereço cadastrado, dizer isso é melhor do que deixar
            # o paciente supor que o nome da clínica basta para chegar.
            address_block = (
                '\n                   (endereço não cadastrado — confirme por telefone)'
            )
        phone_block = f'\n  Telefone ....... {telefone}' if telefone else ''
        return CONFIRMATION_EMAIL_TEMPLATE.format(
            patient=appointment.patient.full_name.split()[0],
            when=when, doctor=doctor, clinic=clinic,
            abertura=ABERTURAS[motivo],
            instrucao=INSTRUCOES[motivo].format(
                contato=f': {telefone}' if telefone else '',
            ),
            address_block=address_block,
            phone_block=phone_block,
        )
    # SMS: a data perde o ano, que a pessoa já sabe, e o resto cede na
    # ordem de `_encurtar_para_sms`.
    short_when = timezone.localtime(appointment.starts_at).strftime('%d/%m às %H:%M')
    return _encurtar_para_sms(
        CONFIRMATION_SMS_TEMPLATE, clinic, doctor, short_when,
        f': {telefone}' if telefone else '',
    )


def deliver_appointment_notice(appointment, motivo, event_version):
    """Avisa o paciente, por e-mail, que o horário dele mudou de estado.

    Nasce de evento e roda **no worker** — marcar e cancelar são atos de
    tela, e a entrega não pode prender a tela nem falhar junto com ela.

    **Só e-mail, de propósito.** SMS custa crédito, é recurso de plano, e
    o aviso automático dispararia em todo agendamento de toda clínica; o
    canal continua disponível pela confirmação que a secretária manda à
    mão, que é quando alguém decidiu gastar. E-mail não tem esse custo.

    Os contatos são os de `confirmation_contacts`, que não exigem opt-in:
    é mensagem transacional sobre um horário que a própria pessoa marcou,
    no endereço que ela deu — inclusive o do pré-cadastro por telefone,
    que é justamente quem mais precisa do aviso. Contato com validade
    vencida continua fora, e a mensagem não leva conteúdo clínico.

    Idempotente pela chave da entrega: o dispatcher pode reentregar o
    evento, e o paciente não recebe dois e-mails do mesmo cancelamento.
    """
    # ------------------------------------------- duas guardas de coerência
    #
    # Nenhuma delas substitui `JANELA_DO_AVISO` em `handlers.py`, que é a
    # que pega o replay; estas pegam o resto, e cada uma por conta
    # própria.
    #
    # **Consulta que já aconteceu não vira aviso.** "Sua consulta está
    # marcada" sobre a semana passada não é mensagem — é confusão. Em
    # 2026-10-07, quatro pacientes receberam exatamente isso.
    if appointment.starts_at < timezone.now():
        return []

    # **O estado de agora manda sobre o fato de então.** Entre o evento e
    # a entrega cabe uma transição: marcar e cancelar em seguida emite os
    # dois eventos, e se o do "marcada" for processado depois o paciente
    # recebe a confirmação de um horário que já caiu. Duas pessoas
    # receberam "sua consulta está marcada" para consulta cancelada.
    from scheduling.models import AppointmentStatus

    cancelada = appointment.status == AppointmentStatus.CANCELLED
    if motivo == 'cancelled' and not cancelada:
        return []
    if motivo in ('booked', 'rescheduled') and cancelada:
        return []

    contacts = confirmation_contacts(appointment, DeliveryChannel.EMAIL)
    if not contacts:
        return []
    message = _confirmation_message(appointment, DeliveryChannel.EMAIL, motivo=motivo)
    assunto = ASSUNTOS[motivo]
    deliveries = []
    for contact in contacts:
        idem_key = f'notice:{motivo}:{appointment.id}:{event_version}:{contact.id}'
        delivery, created = Delivery.objects.get_or_create(
            tenant=appointment.tenant, idempotency_key=idem_key,
            defaults={
                'appointment': appointment, 'contact': contact,
                'channel': DeliveryChannel.EMAIL, 'event_version': event_version,
            },
        )
        if created or delivery.status == DeliveryStatus.PENDING:
            _send(
                delivery, message, subject=assunto,
                physician_membership=appointment.physician_membership,
            )
        deliveries.append(delivery)
    return deliveries


def marca_do_envio(envio_id):
    """Oito caracteres que identificam um pedido de envio entre as repetições dele.

    `envio_id` é o id da tarefa do Celery, que a nova tentativa automática
    preserva. O id inteiro não cabe: a chave de idempotência tem 100
    caracteres, e as dos dois envios já passam de 90.
    """
    return hashlib.sha256(str(envio_id).encode()).hexdigest()[:8]


def send_appointment_confirmation(context, appointment, channel, actor_id, contact=None, envio_id=None):
    """Envia a confirmação de um horário por SMS ou e-mail.

    Reenvio é permitido de propósito: a mensagem pode não chegar, e a
    secretária precisa poder mandar de novo. Cada envio é uma `Delivery`
    própria, numerada — o histórico mostra quantas vezes se tentou, em vez de
    sobrescrever a tentativa anterior.

    **Repetir o pedido não é reenviar** (auditoria de 2026-10, C1). A tarefa
    tenta de novo quando algo estoura, e o que estourava podia vir
    **depois** do SMS — a trilha de auditoria, a gravação da entrega. A
    função inteira era uma transação: a falha desfazia a `Delivery`, o SMS
    que já tinha saído sumia do histórico, e a nova tentativa, sem como
    saber dele, mandava outro. Agora a entrega é gravada antes do envio,
    numa transação que fecha antes dele, e leva a marca do pedido
    (`envio_id`); a repetição a encontra e não envia de novo — `_send` só
    envia entrega que ainda está na fila. Dois cliques são dois pedidos,
    com marcas diferentes, e continuam sendo dois envios.
    """
    from audit.services import record_audit_event

    candidates = [contact] if contact is not None else confirmation_contacts(appointment, channel)
    candidates = [c for c in candidates if c is not None]
    if not candidates:
        campo = 'e-mail' if channel == DeliveryChannel.EMAIL else 'telefone'
        raise NoUsableContact(
            f'Nenhum contato deste paciente tem {campo} cadastrado. '
            'Inclua o contato na ficha do paciente.'
        )

    target = candidates[0]
    message = _confirmation_message(appointment, channel)
    anteriores = Delivery.objects.filter(
        appointment=appointment, contact=target, channel=channel,
        idempotency_key__startswith=f'confirmation:{appointment.id}:',
    )
    delivery = None
    if envio_id is not None:
        marca = marca_do_envio(envio_id)
        delivery = anteriores.filter(idempotency_key__endswith=f':{marca}').first()
    if delivery is not None:
        sent = anteriores.filter(created_at__lt=delivery.created_at).count()
    else:
        sent = anteriores.count()
        # Sem o contato na chave quando há marca: com ele, a chave de e-mail
        # passaria dos 100 caracteres. A marca já a torna única.
        chave = (
            f'confirmation:{appointment.id}:{channel}:{sent + 1}:{marca}'
            if envio_id is not None
            else f'confirmation:{appointment.id}:{target.id}:{channel}:{sent + 1}'
        )
        with transaction.atomic():
            delivery = Delivery.objects.create(
                tenant=appointment.tenant, appointment=appointment, contact=target, channel=channel,
                event_version=appointment.row_version, idempotency_key=chave,
            )
    _send(
        delivery, message, subject=CONFIRMATION_EMAIL_SUBJECT,
        physician_membership=appointment.physician_membership,
    )
    delivery.refresh_from_db()
    record_audit_event(
        actor_id, appointment.tenant_id, 'communications.confirmation_sent',
        object_type='appointment', object_id=appointment.id, outcome='success',
        integrity_metadata={
            'channel': channel, 'contact_id': str(target.id), 'status': delivery.status,
            'attempt': sent + 1,
        },
    )
    return delivery
