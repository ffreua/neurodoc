from scheduling.models import Appointment

from .services import get_or_create_card_for_appointment

AGENDADO_STAGE = 'Agendado'


def handle_appointment_reserved(event):
    appointment = Appointment.objects.filter(id=event.payload_minimal['appointment_id']).first()
    if appointment is None:
        return
    get_or_create_card_for_appointment(appointment, AGENDADO_STAGE)
