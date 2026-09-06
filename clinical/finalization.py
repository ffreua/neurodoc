from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from events.models import OutboxEvent, OutboxEventStatus

from .carry_forward import has_pending_review
from .models import ClinicalAmendment, Encounter, EncounterStatus

ENCOUNTER_FINALIZED_TOPIC = 'clinical.encounter_finalized'


class FinalizationError(Exception):
    pass


@transaction.atomic
def finalize_encounter(context, encounter, actor_membership):
    if encounter.status == EncounterStatus.FINALIZED:
        raise FinalizationError('Encounter is already finalized')
    if has_pending_review(encounter):
        raise FinalizationError('Carry-forward items are still pending review')
    has_history = bool(encounter.chief_complaint or encounter.hpi)
    has_plan = bool(encounter.plan_text)
    if not (has_history or encounter.finalization_justification):
        raise FinalizationError('Chief complaint/HPI or a justification is required')
    if not (has_plan or encounter.finalization_justification):
        raise FinalizationError('Plan (conduta) or a justification is required')

    encounter.status = EncounterStatus.FINALIZED
    encounter.finalized_at = timezone.now()
    encounter.finalized_by = actor_membership
    encounter.content_hash = encounter.compute_content_hash()
    encounter.row_version += 1
    encounter.full_clean()
    encounter.save()
    record_audit_event(
        actor_membership.user_id, context.tenant_id, 'clinical.encounter_finalized',
        object_type='encounter', object_id=encounter.id, outcome='success',
        integrity_metadata={'content_hash': encounter.content_hash},
    )
    OutboxEvent.objects.get_or_create(
        tenant_id=encounter.tenant_id, topic=ENCOUNTER_FINALIZED_TOPIC, aggregate_type='encounter',
        aggregate_id=encounter.id, event_version=encounter.row_version,
        defaults={
            'payload_minimal': {'encounter_id': str(encounter.id), 'patient_id': str(encounter.patient_id)},
            'available_at': timezone.now(),
            'status': OutboxEventStatus.PENDING,
        },
    )
    return encounter


@transaction.atomic
def add_amendment(context, encounter, author_membership, reason, text):
    if encounter.status != EncounterStatus.FINALIZED:
        raise FinalizationError('Amendments only apply to finalized encounters')
    amendment = ClinicalAmendment.objects.create(
        tenant_id=context.tenant_id, encounter=encounter, author=author_membership,
        reason=reason, text=text, authored_at=timezone.now(),
    )
    record_audit_event(
        author_membership.user_id, context.tenant_id, 'clinical.amendment_added',
        object_type='encounter', object_id=encounter.id, outcome='success',
    )
    return amendment
