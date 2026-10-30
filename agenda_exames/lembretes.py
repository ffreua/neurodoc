"""Lembrete do exame: 24 h antes, pelo despachante de eventos.

Um lembrete só, e não dois como na consulta: o exame costuma ter preparo
(cabelo lavado e seco no EEG, sem creme na ENMG, a noite inteira na
polissonografia) que a recepção explica ao marcar — duas horas antes é
tarde para ele.

A versão do evento é `Reserva.versao_lembrete`, que sobe a cada
remarcação. O evento de uma versão velha é cancelado na hora
(`invalidar`), e o que o despachante já tinha reclamado é descartado na
entrega (`communications.services.deliver_exam_reminder` compara a
versão). Cancelamento, falta e realização calam o lembrete pelo estado.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from events.models import OutboxEvent, OutboxEventStatus

TOPICO_LEMBRETE = 'agenda_exames.lembrete'
HORAS_ANTES = 24


@transaction.atomic
def invalidar(reserva):
    OutboxEvent.objects.filter(
        tenant_id=reserva.tenant_id, topic=TOPICO_LEMBRETE, aggregate_type='reserva_exame',
        aggregate_id=reserva.id, status=OutboxEventStatus.PENDING,
    ).exclude(event_version=reserva.versao_lembrete).update(status=OutboxEventStatus.CANCELLED)


@transaction.atomic
def agendar(reserva):
    invalidar(reserva)
    quando = reserva.inicio - timedelta(hours=HORAS_ANTES)
    evento, _ = OutboxEvent.objects.get_or_create(
        tenant_id=reserva.tenant_id, topic=TOPICO_LEMBRETE, aggregate_type='reserva_exame',
        aggregate_id=reserva.id, event_version=reserva.versao_lembrete,
        defaults={
            'payload_minimal': {'reserva_id': str(reserva.id)},
            'available_at': quando,
            # Marcado com menos de 24 h: o paciente acabou de ouvir a data.
            'status': OutboxEventStatus.PENDING if quando > timezone.now() else OutboxEventStatus.CANCELLED,
        },
    )
    return evento


@transaction.atomic
def cancelar_todos(reserva):
    OutboxEvent.objects.filter(
        tenant_id=reserva.tenant_id, topic=TOPICO_LEMBRETE, aggregate_type='reserva_exame',
        aggregate_id=reserva.id, status=OutboxEventStatus.PENDING,
    ).update(status=OutboxEventStatus.CANCELLED)


def tratar_lembrete(evento):
    from communications.services import deliver_exam_reminder

    from .models import Reserva

    reserva = Reserva.objects.select_related('paciente', 'tenant').filter(
        id=evento.payload_minimal['reserva_id'],
    ).first()
    if reserva is None:
        return
    deliver_exam_reminder(reserva, evento.event_version)
