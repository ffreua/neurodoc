import secrets

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

DOCUMENT_MESSAGE = 'Seu documento está disponível no NeuroDoc. Acesse o link para visualizá-lo com segurança.'
REMINDER_MESSAGE_TEMPLATE = 'Lembrete NeuroDoc: consulta em {when}. Em caso de duvida, contate a clinica.'


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
    delivery.status = DeliveryStatus.ACCEPTED
    if delivery.channel == DeliveryChannel.SMS:
        # Email has no DLR-equivalent in this baseline, so ACCEPTED is its
        # final state; only SMS gets polled for a real DELIVERED/FAILED.
        delivery.next_attempt_at = timezone.now() + timezone.timedelta(minutes=POLL_OFFSETS_MINUTES[0])
    delivery.save(update_fields=['status', 'provider_id', 'next_attempt_at'])
    _record_attempt(delivery, DeliveryAttemptOutcome.ACCEPTED)


@transaction.atomic
def deliver_document(document, force_new_link=False):
    """Manda o documento aos contatos autorizados do paciente.

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
                link = f'{settings.PUBLIC_BASE_URL}/d/{raw_token}/'
                _send(delivery, _document_message(document, link))
            deliveries.append(delivery)
    return deliveries


def _document_message(document, link):
    """O texto que o paciente recebe.

    Sem diagnóstico, sem medicação, sem o tipo do documento: a mensagem
    aparece na tela bloqueada do celular e é lida por quem estiver por
    perto. "Documento" basta para a pessoa saber que é dela e clicar.

    Dizer de antemão o que será pedido evita a ligação para a recepção —
    quem chega ao link já sabe que precisa do CPF em mãos.
    """
    return (
        f'{DOCUMENT_MESSAGE} {link} '
        'Para abrir, informe os 4 últimos dígitos do CPF do paciente.'
    )


@transaction.atomic
def deliver_appointment_reminder(appointment, event_version):
    contacts = _eligible_reminder_contacts(appointment.patient)
    if not contacts:
        from django.utils import timezone as _tz

        quando = _tz.localtime(appointment.starts_at).strftime('%d/%m às %H:%M')
        _notify_no_contact(appointment.patient, f'lembrete do horário de {quando}')
        return []

    when = appointment.starts_at.strftime('%d/%m %H:%M')
    message = REMINDER_MESSAGE_TEMPLATE.format(when=when)
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
# Confirmação enviada à mão pela secretaria
# --------------------------------------------------------------------------

CONFIRMATION_SMS_TEMPLATE = (
    '{clinic}: consulta com {doctor} em {when}. Confirme respondendo a esta '
    'mensagem ou ligue para a clinica.'
)
CONFIRMATION_EMAIL_SUBJECT = 'Confirmação de consulta'
CONFIRMATION_EMAIL_TEMPLATE = """Olá, {patient}.

Sua consulta está marcada:

  Data e hora: {when}
  Profissional: {doctor}
  Local: {clinic}

Se precisar remarcar ou cancelar, entre em contato com a clínica.

Esta mensagem é apenas uma confirmação de horário e não contém informação clínica.
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


def _confirmation_message(appointment, channel):
    tenant = appointment.tenant
    clinic = (tenant.trade_name or tenant.legal_name or 'Clinica')[:40]
    doctor = (
        appointment.physician_membership.user.get_full_name()
        or appointment.physician_membership.user.email
    )
    when = timezone.localtime(appointment.starts_at).strftime('%d/%m/%Y às %H:%M')
    if channel == DeliveryChannel.EMAIL:
        return CONFIRMATION_EMAIL_TEMPLATE.format(
            patient=appointment.patient.full_name.split()[0],
            when=when, doctor=doctor, clinic=clinic,
        )
    # SMS tem 160 caracteres: o nome do médico entra encurtado quando
    # precisa, e a data sem o ano, que a pessoa já sabe.
    short_when = timezone.localtime(appointment.starts_at).strftime('%d/%m às %H:%M')
    short_doctor = doctor if len(doctor) <= 24 else doctor.split()[0]
    text = CONFIRMATION_SMS_TEMPLATE.format(
        clinic=clinic[:24], doctor=short_doctor, when=short_when,
    )
    return text[:160]


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
