from communications.services import deliver_appointment_reminder

from .models import Appointment


def handle_appointment_reminder(event):
    appointment = Appointment.objects.filter(id=event.payload_minimal['appointment_id']).first()
    if appointment is None:
        return
    deliver_appointment_reminder(appointment, event.event_version)
