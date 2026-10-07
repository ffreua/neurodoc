from documents.models import MedicalDocument

from .services import deliver_document


def handle_document_issued(event):
    document = MedicalDocument.objects.filter(id=event.payload_minimal['medical_document_id']).first()
    if document is None:
        return
    deliver_document(document)


def _aviso(event, motivo):
    """Consumidor dos eventos de horário: avisa o paciente por e-mail.

    Mora em `communications` e não em `scheduling` porque quem entrega é
    este app — e porque o CRM já consome `appointment_reserved` por conta
    própria. O dispatcher aceita vários consumidores no mesmo tópico, e é
    isso que permite o aviso ao paciente entrar sem um evento novo para o
    fato que já tinha um.
    """
    from scheduling.models import Appointment

    from .services import deliver_appointment_notice

    appointment = Appointment.objects.filter(
        id=event.payload_minimal.get('appointment_id'),
    ).select_related('tenant', 'patient', 'physician_membership__user').first()
    if appointment is None:
        return
    deliver_appointment_notice(appointment, motivo, event.event_version)


def handle_appointment_booked(event):
    _aviso(event, 'booked')


def handle_appointment_rescheduled(event):
    _aviso(event, 'rescheduled')


def handle_appointment_cancelled(event):
    _aviso(event, 'cancelled')
