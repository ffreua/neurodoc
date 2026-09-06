from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import CRMCard, CRMStage, CRMTransition

DEFAULT_STAGE_NAMES = ['Contato', 'Agendamento pendente', 'Agendado', 'Acompanhamento', 'Concluído']
TERMINAL_STAGE_NAME = 'Concluído'


class InvalidTransition(Exception):
    pass


def bootstrap_default_stages(tenant):
    """Idempotent: safe to call more than once, only fills in stages that
    don't exist yet by name. Not auto-triggered on tenant creation in this
    sprint -- seed_demo integration is S14 scope.
    """
    created = []
    for order, name in enumerate(DEFAULT_STAGE_NAMES, start=1):
        stage, was_created = CRMStage.objects.get_or_create(
            tenant=tenant, name=name, defaults={'order': order},
        )
        if was_created:
            created.append(stage)
    return created


@transaction.atomic
def move_card(card, to_stage, actor_membership, reason=''):
    """The only way a card's stage changes -- an explicit, administrative
    action. Never touches Encounter/MedicalDocument state; the caller
    (a view, or an outbox handler reacting to a scheduling event) is
    responsible for keeping this call free of clinical side effects.
    """
    if to_stage.tenant_id != card.tenant_id:
        raise InvalidTransition('Stage belongs to a different tenant')
    from_stage = card.stage
    card.stage = to_stage
    card.save(update_fields=['stage'])
    transition = CRMTransition.objects.create(
        tenant=card.tenant, card=card, from_stage=from_stage, to_stage=to_stage,
        actor=actor_membership, reason=reason[:255],
    )
    record_audit_event(
        actor_membership.user_id if actor_membership else None, card.tenant_id, 'crm.card_moved',
        object_type='crm_card', object_id=card.id, outcome='success',
        integrity_metadata={
            'from_stage': str(from_stage.id) if from_stage else None,
            'to_stage': str(to_stage.id),
        },
    )
    return transition


def open_card_for_patient(tenant, patient):
    return CRMCard.objects.filter(
        tenant=tenant, patient=patient,
    ).exclude(stage__name=TERMINAL_STAGE_NAME).order_by('-created_at').first()


@transaction.atomic
def get_or_create_card_for_appointment(appointment, initial_stage_name):
    tenant = appointment.tenant
    stage = CRMStage.objects.filter(tenant=tenant, name=initial_stage_name).first()
    if stage is None:
        bootstrap_default_stages(tenant)
        stage = CRMStage.objects.get(tenant=tenant, name=initial_stage_name)

    card = open_card_for_patient(tenant, appointment.patient)
    if card is None:
        first_stage = CRMStage.objects.filter(tenant=tenant, order=1).first() or stage
        card = CRMCard.objects.create(
            tenant=tenant, patient=appointment.patient, appointment=appointment, stage=first_stage,
        )
        CRMTransition.objects.create(
            tenant=tenant, card=card, from_stage=None, to_stage=first_stage, actor=None,
            reason='Card criado automaticamente ao reservar consulta',
        )
    if card.appointment_id != appointment.id:
        card.appointment = appointment
        card.save(update_fields=['appointment'])
    if card.stage_id != stage.id:
        move_card(card, stage, actor_membership=None, reason='Consulta reservada')
    return card
