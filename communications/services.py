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


def _notify_no_contact(tenant, target_type, target_id):
    from notifications.services import notify_role

    notify_role(
        tenant, roles=('secretary', 'owner'), kind='delivery_pending_contact',
        sanitized_title='Entrega pendente — verifique o cadastro de contato do paciente',
        target_type=target_type, target_id=target_id,
    )


def _record_attempt(delivery, outcome, provider_code='', sanitized_error=''):
    attempt_number = delivery.attempts.count() + 1
    DeliveryAttempt.objects.create(
        tenant=delivery.tenant, delivery=delivery, attempt_number=attempt_number,
        started_at=timezone.now(), ended_at=timezone.now(), outcome=outcome,
        provider_code=provider_code, sanitized_error=sanitized_error[:255],
    )


def _send(delivery, message):
    try:
        if delivery.channel == DeliveryChannel.EMAIL:
            send_email(delivery.contact.email, 'Notificação NeuroDoc', message)
        else:
            result = send_sms(delivery.contact.phone, message, refer=str(delivery.id))
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
def deliver_document(document):
    contacts = _eligible_document_contacts(document.patient)
    if not contacts:
        _notify_no_contact(document.tenant, 'medical_document', document.id)
        return []

    deliveries = []
    for contact in contacts:
        for channel in _channels_for(contact):
            idem_key = f'document:{document.id}:{contact.id}:{channel}'
            delivery, created = Delivery.objects.get_or_create(
                tenant=document.tenant, idempotency_key=idem_key,
                defaults={
                    'document': document, 'contact': contact, 'channel': channel,
                    'event_version': document.version,
                },
            )
            if created or delivery.status == DeliveryStatus.PENDING:
                token, raw_token = access.create_access_token(document, contact)
                link = f'{settings.PUBLIC_BASE_URL}/d/{raw_token}/'
                _send(delivery, f'{DOCUMENT_MESSAGE} {link}')
            deliveries.append(delivery)
    return deliveries


@transaction.atomic
def deliver_appointment_reminder(appointment, event_version):
    contacts = _eligible_reminder_contacts(appointment.patient)
    if not contacts:
        _notify_no_contact(appointment.tenant, 'appointment', appointment.id)
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
                _send(delivery, message)
            deliveries.append(delivery)
    return deliveries
