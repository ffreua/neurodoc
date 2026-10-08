"""Comunicação em massa: montar a lista, enviar no ritmo, registrar o que saiu.

Três coisas governam este módulo, e nenhuma é opcional.

**Consentimento.** A lista sai de quem tem `marketing_opt_in_at` e não
revogou. É reconferido no instante do envio, e não só na montagem: entre
criar a campanha e disparar podem passar dias, e quem se descadastrou
nesse intervalo não pode receber.

**Descadastro em um clique.** O link é acrescentado no envio, não digitado
por quem escreve — mensagem sem ele não sai. A LGPD (art. 8º, §5º) manda
que revogar seja tão fácil quanto consentir, e exigir login para parar de
receber e-mail não é fácil.

**Ritmo.** Servidor de e-mail derruba conexão e provedor marca domínio como
spam quando mil mensagens saem de uma vez de um remetente novo. O envio é
fatiado por minuto, e a campanha volta para a fila até acabar.

**Servidor próprio.** A comunicação em massa só sai pelo servidor SMTP da
própria clínica, em qualquer plano — nunca pelo da instalação. Não é corte
comercial: é que a reputação do servidor da instalação é dividida por todas
as clínicas, e uma campanha que caia em filtro de spam levaria junto a
confirmação de conta e a recuperação de senha de quem não tem nada com ela.
Remetente da clínica **sem** servidor não basta, porque sai pelo da
instalação (ver `email.clinic_own_server`). A exigência é conferida em
quatro portas: a tela, a guarda do disparo, cada fatia e o próprio envio.
"""

from contextlib import contextmanager

import secrets

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .email import EmailSendFailed, OwnServerRequired, clinic_own_server, send_email
from .models import CampaignStatus, MarketingCampaign, MarketingRecipient, RecipientStatus

#: Teto por minuto que a tela aceita. Não é limite técnico do SMTP — é o
#: ponto a partir do qual um erro de configuração vira incidente de
#: reputação antes de alguém perceber e pausar.
MAX_PER_MINUTE = 120


class CampaignBlocked(Exception):
    """A campanha não pode sair. A mensagem diz o que falta."""


#: O que a tela e a guarda dizem quando falta o servidor próprio. Num lugar
#: só para a recusa do disparo e o aviso da tela não divergirem.
SEM_SERVIDOR_PROPRIO = (
    'A comunicação em massa sai apenas pelo servidor de e-mail da própria '
    'clínica. Cadastre e ative o servidor SMTP da clínica em Integrações → '
    'SMS e e-mail para criar, testar e disparar campanhas.'
)


def has_own_server(tenant_id):
    """A clínica pode fazer comunicação em massa? Vale para qualquer plano."""
    return clinic_own_server(tenant_id) is not None


def eligible_contacts(tenant_id):
    """Contatos que consentiram e não revogaram.

    Ordenado por id para a montagem ser determinística: duas montagens da
    mesma lista têm de produzir a mesma ordem, senão comparar duas
    campanhas vira adivinhação.
    """
    from django.db.models import Q

    from patients.models import PatientContact

    agora = timezone.now()
    ainda_valido = Q(valid_until__isnull=True) | Q(valid_until__gt=agora)
    return (
        PatientContact.objects
        .filter(
            tenant_id=tenant_id,
            marketing_opt_in_at__isnull=False,
            marketing_opt_out_at__isnull=True,
        )
        .exclude(email='')
        .filter(ainda_valido)
        .select_related('patient')
        .order_by('id')
    )


def unsubscribe_token(contact):
    """Garante um token de descadastro para este contato.

    Criado sob demanda e guardado: um token novo a cada envio invalidaria
    o link da mensagem anterior, e quem tenta se descadastrar por um e-mail
    de dois meses atrás merece que funcione.
    """
    if not contact.marketing_unsubscribe_token:
        contact.marketing_unsubscribe_token = secrets.token_urlsafe(24)
        contact.save(update_fields=['marketing_unsubscribe_token'])
    return contact.marketing_unsubscribe_token


def unsubscribe_url(contact):
    from django.conf import settings

    base = (settings.PUBLIC_BASE_URL or '').rstrip('/')
    return f'{base}/descadastrar/{unsubscribe_token(contact)}/'


@transaction.atomic
def build_recipients(campaign):
    """Congela a lista de destinatários da campanha.

    Congelada, e não recalculada a cada envio, porque a campanha é um
    registro do que foi enviado a quem — e uma lista que muda sozinha
    tornaria esse registro incapaz de responder a pergunta.

    A reconferência de consentimento no envio é o que mantém o congelamento
    seguro: quem entra na lista e se descadastra depois é pulado, não
    enviado.
    """
    criados = 0
    for contact in eligible_contacts(campaign.tenant_id):
        _, created = MarketingRecipient.objects.get_or_create(
            tenant_id=campaign.tenant_id, campaign=campaign, contact=contact,
            defaults={'email': contact.email},
        )
        criados += 1 if created else 0
    return criados


def _body_with_footer(campaign, contact):
    """O texto escrito, mais o rodapé obrigatório.

    O rodapé é acrescentado aqui e não é editável: quem escreve a campanha
    não deve poder removê-lo por esquecimento nem por escolha. Diz quem
    mandou, por que a pessoa está recebendo, e como parar.
    """
    tenant = campaign.tenant
    nome = tenant.trade_name or tenant.legal_name
    return (
        f'{campaign.body_text}\n\n'
        '---\n'
        f'Você recebeu esta mensagem porque autorizou {nome} a enviar comunicações.\n'
        f'Para não receber mais, acesse: {unsubscribe_url(contact)}\n'
        'Esta é uma mensagem de divulgação. Para assuntos do seu atendimento, '
        'use os canais de sempre da clínica.\n'
    )


#: Classe de trava das campanhas, no espaco de travas consultivas do
#: PostgreSQL. Numero proprio, ao lado do `BACKUP_LOCK` de `ops/locks.py`:
#: duas travas diferentes nao podem dividir o mesmo numero.
CAMPAIGN_LOCK_CLASS = 72654003


@contextmanager
def _envio_exclusivo(campaign):
    """Uma fatia de cada vez, por campanha.

    `send_batch` lia os pendentes e enviava, sem travar as linhas. Duas
    fatias simultaneas da mesma campanha liam **os mesmos** destinatarios
    e mandavam o e-mail duas vezes para a mesma pessoa -- e o caminho para
    isso era curto: dois cliques no botao de disparar, ou um clique em
    cima da tarefa periodica que ja estava rodando.

    Trava consultiva e nao `select_for_update`: manter uma transacao
    aberta durante o SMTP e o que esgota o pool de conexoes quando o
    servidor de e-mail demora. A trava vale pela sessao, o envio acontece
    fora de transacao, e quem nao a pega simplesmente nao envia -- a fatia
    dele seria duplicata da que ja esta saindo.

    `crc32` e nao `hash()`: o `hash` de texto e aleatorizado por processo
    no Python, entao dois workers calculariam chaves diferentes e a trava
    nao trancaria nada.
    """
    import zlib

    from django.db import connection

    chave = zlib.crc32(str(campaign.id).encode()) - 2**31
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, %s)',
                       [CAMPAIGN_LOCK_CLASS, chave])
        peguei = cursor.fetchone()[0]
    if not peguei:
        yield False
        return
    try:
        yield True
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s, %s)',
                           [CAMPAIGN_LOCK_CLASS, chave])


def guard(campaign):
    """Recusa o disparo quando falta algo. Erra para o lado de não enviar."""
    # `SENDING` saiu da lista. Aceita-lo fazia o segundo clique no botao de
    # disparar agendar uma segunda cadeia de fatias para a mesma campanha.
    # "Retomar" parte de `PAUSED`, entao nada legitimo se perde -- e quem
    # clica duas vezes recebe uma frase em vez de duplicar o envio.
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        if campaign.status == CampaignStatus.SENDING:
            raise CampaignBlocked('Esta campanha já está enviando.')
        raise CampaignBlocked('Esta campanha já foi concluída ou cancelada.')
    if not campaign.subject.strip() or not campaign.body_text.strip():
        raise CampaignBlocked('Assunto e texto são obrigatórios.')
    if not has_own_server(campaign.tenant_id):
        raise CampaignBlocked(SEM_SERVIDOR_PROPRIO)
    if not campaign.recipients.filter(status=RecipientStatus.PENDING).exists():
        raise CampaignBlocked('Nenhum destinatário na fila.')


def send_batch(campaign, limit=None):
    """Envia uma fatia da fila. Devolve quantos saíram e quantos faltam.

    O tamanho da fatia é `per_minute`: quem chama de novo é a tarefa
    agendada, um minuto depois. Fatiar aqui, e não dormir dentro da tarefa,
    mantém o worker livre entre as fatias.
    """
    limit = limit or campaign.per_minute
    with _envio_exclusivo(campaign) as meu:
        if not meu:
            # Outra fatia desta campanha esta saindo agora. A nossa seria
            # duplicata dela, e `restantes` continua o que era: quem
            # segura a trava reagenda a proxima.
            restantes = campaign.recipients.filter(
                status=RecipientStatus.PENDING,
            ).count()
            return {'enviados': 0, 'falhas': 0, 'pulados': 0, 'restantes': restantes,
                    'concorrente': True}
        return _enviar_fatia(campaign, limit)


def _pausar_sem_servidor(campaign):
    """Para a campanha cujo servidor próprio sumiu no meio do envio.

    Entre o disparo e a última fatia podem passar horas, e a clínica pode
    desligar o servidor nesse meio-tempo. Seguir enviando faria o resto da
    lista sair pelo servidor da instalação — exatamente o que a guarda
    recusou no disparo. Pausar, e não cancelar: religado o servidor,
    "retomar" continua de onde parou, sem reenviar a quem já recebeu.
    """
    if campaign.status == CampaignStatus.SENDING:
        campaign.status = CampaignStatus.PAUSED
        campaign.save(update_fields=['status'])
        record_audit_event(
            None, campaign.tenant_id, 'communications.campaign_paused',
            object_type='marketing_campaign', object_id=campaign.id, outcome='success',
            integrity_metadata={'motivo': 'sem_servidor_proprio'},
        )


def _enviar_fatia(campaign, limit):
    if not has_own_server(campaign.tenant_id):
        _pausar_sem_servidor(campaign)
        restantes = campaign.recipients.filter(status=RecipientStatus.PENDING).count()
        return {'enviados': 0, 'falhas': 0, 'pulados': 0, 'restantes': restantes,
                'sem_servidor_proprio': True}

    pendentes = (
        campaign.recipients.filter(status=RecipientStatus.PENDING)
        .select_related('contact')[:limit]
    )

    enviados = falhas = pulados = 0
    for recipient in pendentes:
        contact = recipient.contact
        # Reconferência no instante do envio: a lista foi congelada antes,
        # e o consentimento pode ter sido revogado desde então.
        if not contact.accepts_marketing:
            recipient.status = RecipientStatus.SKIPPED
            recipient.detail = 'Consentimento revogado ou contato sem e-mail válido.'
            recipient.save(update_fields=['status', 'detail'])
            pulados += 1
            continue
        try:
            send_email(
                contact.email, campaign.subject, _body_with_footer(campaign, contact),
                tenant_id=campaign.tenant_id, require_own_server=True,
            )
        except OwnServerRequired:
            # O servidor sumiu no meio da fatia. O destinatário fica
            # pendente -- não falhou, não chegou a sair -- e a campanha para.
            _pausar_sem_servidor(campaign)
            break
        except EmailSendFailed as exc:
            recipient.status = RecipientStatus.FAILED
            # Classe do erro, não a mensagem crua: ela pode trazer de volta
            # o endereço e trechos da conversa com o servidor.
            recipient.detail = exc.__class__.__name__
            recipient.save(update_fields=['status', 'detail'])
            falhas += 1
            continue
        recipient.status = RecipientStatus.SENT
        recipient.sent_at = timezone.now()
        recipient.email = contact.email
        recipient.save(update_fields=['status', 'sent_at', 'email'])
        enviados += 1

    restantes = campaign.recipients.filter(status=RecipientStatus.PENDING).count()
    if restantes == 0 and campaign.status == CampaignStatus.SENDING:
        campaign.status = CampaignStatus.SENT
        campaign.finished_at = timezone.now()
        campaign.save(update_fields=['status', 'finished_at'])
        record_audit_event(
            None, campaign.tenant_id, 'communications.campaign_finished',
            object_type='marketing_campaign', object_id=campaign.id, outcome='success',
            integrity_metadata=campaign.counts,
        )
    return {'enviados': enviados, 'falhas': falhas, 'pulados': pulados, 'restantes': restantes}


def start(campaign, actor=None):
    """Põe a campanha em envio e agenda a primeira fatia."""
    guard(campaign)
    campaign.status = CampaignStatus.SENDING
    campaign.started_at = campaign.started_at or timezone.now()
    campaign.save(update_fields=['status', 'started_at'])
    record_audit_event(
        actor, campaign.tenant_id, 'communications.campaign_started',
        object_type='marketing_campaign', object_id=campaign.id, outcome='success',
        integrity_metadata={'recipients': campaign.counts.get('total', 0),
                            'per_minute': campaign.per_minute},
    )
    from .tasks import run_campaign_batch

    run_campaign_batch.delay(str(campaign.id))
    return campaign


def pause(campaign, actor=None):
    campaign.status = CampaignStatus.PAUSED
    campaign.save(update_fields=['status'])
    record_audit_event(
        actor, campaign.tenant_id, 'communications.campaign_paused',
        object_type='marketing_campaign', object_id=campaign.id, outcome='success',
    )
    return campaign


def unsubscribe(contact, source='link'):
    """Revoga o consentimento. Idempotente.

    Não apaga o contato nem o `marketing_opt_in_at`: apagar o consentimento
    apagaria também a prova de que ele existiu, e é justamente essa prova
    que sustenta o que já foi enviado.
    """
    if contact.marketing_opt_out_at is None:
        contact.marketing_opt_out_at = timezone.now()
        contact.save(update_fields=['marketing_opt_out_at'])
        record_audit_event(
            None, contact.tenant_id, 'communications.marketing_unsubscribed',
            object_type='patient_contact', object_id=contact.id, outcome='success',
            integrity_metadata={'source': source},
        )
    return contact
