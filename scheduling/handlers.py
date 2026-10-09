from communications.services import deliver_appointment_reminder
from events.models import OutboxEvent

from .models import Appointment


def _substituido(event):
    """Há lembrete mais novo deste mesmo horário, no mesmo tópico.

    Remarcar e trocar o paciente reagendam os lembretes com a versão nova
    do agendamento (`schedule_reminders`), e cancelam os antigos que ainda
    estão pendentes. O que já tinha sido reclamado pelo despachante
    escapava desse cancelamento e lembrava o horário velho -- ou o
    paciente velho. A existência do evento mais novo é a prova de que
    este foi substituído, e vale também para a versão que subiu por
    confirmação, que não cria lembrete novo e por isso não cala nada.
    """
    return OutboxEvent.objects.filter(
        tenant_id=event.tenant_id, topic=event.topic, aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id, event_version__gt=event.event_version,
    ).exists()


def handle_appointment_reminder(event):
    appointment = Appointment.objects.filter(id=event.payload_minimal['appointment_id']).first()
    if appointment is None:
        return
    if _substituido(event):
        return
    deliver_appointment_reminder(appointment, event.event_version)
