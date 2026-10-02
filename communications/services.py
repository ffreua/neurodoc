import logging
import secrets
from urllib.parse import quote_plus

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from patients.contacts import authorized_document_contacts

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

    ativa = Tenant.objects.filter(
        id=delivery.tenant_id, status=TenantStatus.ACTIVE,
    ).exists()
    if not ativa:
        delivery.status = DeliveryStatus.NO_CONTACT
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
        delivery.status = DeliveryStatus.NO_CONTACT
        delivery.save(update_fields=['status'])
        _record_attempt(delivery, DeliveryAttemptOutcome.FAILED, sanitized_error='channel_disabled')
        return
    except (EmailSendFailed, SmsSendFailed) as exc:
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


def deliver_document(document, force_new_link=False):
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
    """
    contacts = _eligible_document_contacts(document.patient)
    if not contacts:
        numero = document.document_number or 'sem número'
        _notify_no_contact(
            document.patient,
            f'{document.get_kind_display().lower()} {numero}',
        )
        return []

    deliveries = []
    for contact in contacts:
        for channel in _channels_for(contact):
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
                idem_key = f'{idem_key}:{secrets.token_hex(4)}'
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
                    if force_new_link:
                        access.revoke_previous_tokens(document)
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


@transaction.atomic
def deliver_appointment_reminder(appointment, event_version):
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
    for contact in contacts:
        for channel in _channels_for(contact):
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
    for contato in contatos:
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
CONFIRMATION_EMAIL_TEMPLATE = """Olá, {patient}.

Sua consulta está marcada:

  Data e hora .... {when}
  Profissional ... {doctor}
  Local .......... {clinic}
{address_block}

Para confirmar, remarcar ou cancelar, ligue para a clínica{contato}.

Esta mensagem é automática e esta caixa não recebe respostas — se você
responder a este e-mail, ninguém vai ler.

É apenas uma confirmação de horário: não contém informação clínica, nem
diagnóstico, nem resultado de exame.
"""


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
    return [
        contact for contact in appointment.patient.contacts.all()
        if _still_valid(contact) and getattr(contact, field)
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


def _confirmation_message(appointment, channel):
    tenant = appointment.tenant
    clinic = (tenant.trade_name or tenant.legal_name or 'Clinica')[:40]
    doctor = (
        appointment.physician_membership.user.get_full_name()
        or appointment.physician_membership.user.email
    )
    telefone, endereco, mapa = _contato_e_endereco_da_clinica(tenant)
    when = timezone.localtime(appointment.starts_at).strftime('%d/%m/%Y às %H:%M')
    if channel == DeliveryChannel.EMAIL:
        address_block = ''
        if endereco:
            address_block = f'  Endereço ....... {endereco}\n  Google Maps .... {mapa}'
        return CONFIRMATION_EMAIL_TEMPLATE.format(
            patient=appointment.patient.full_name.split()[0],
            when=when, doctor=doctor, clinic=clinic,
            contato=f': {telefone}' if telefone else '',
            address_block=address_block,
        )
    # SMS: a data perde o ano, que a pessoa já sabe, e o resto cede na
    # ordem de `_encurtar_para_sms`.
    short_when = timezone.localtime(appointment.starts_at).strftime('%d/%m às %H:%M')
    return _encurtar_para_sms(
        CONFIRMATION_SMS_TEMPLATE, clinic, doctor, short_when,
        f': {telefone}' if telefone else '',
    )


@transaction.atomic
def send_appointment_confirmation(context, appointment, channel, actor_id, contact=None):
    """Envia a confirmação de um horário por SMS ou e-mail.

    Reenvio é permitido de propósito: a mensagem pode não chegar, e a
    secretária precisa poder mandar de novo. Cada envio é uma `Delivery`
    própria, numerada — o histórico mostra quantas vezes se tentou, em vez de
    sobrescrever a tentativa anterior.
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
    sent = Delivery.objects.filter(
        appointment=appointment, contact=target, channel=channel,
        idempotency_key__startswith=f'confirmation:{appointment.id}:',
    ).count()
    delivery = Delivery.objects.create(
        tenant=appointment.tenant, appointment=appointment, contact=target, channel=channel,
        event_version=appointment.row_version,
        idempotency_key=f'confirmation:{appointment.id}:{target.id}:{channel}:{sent + 1}',
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
