"""RF-03.04: copy only `plan_text` (conduta) and diagnoses (hipóteses) from
the physician's own last finalized encounter for this patient — never exam
findings, never chief complaint/HPI, and never auto-generated prescriptions
or requests. An alternative source encounter must be passed explicitly by
the caller (never inferred), matching the "seleção explícita autorizada"
requirement.
"""
from django.db import transaction

from .models import CarryForwardItem, Encounter, EncounterStatus


def default_source_encounter(target_encounter):
    return (
        Encounter.objects
        .filter(
            tenant_id=target_encounter.tenant_id, patient_id=target_encounter.patient_id,
            physician_membership_id=target_encounter.physician_membership_id,
            status=EncounterStatus.FINALIZED, occurred_at__lt=target_encounter.occurred_at,
        )
        .exclude(id=target_encounter.id)
        .order_by('-occurred_at')
        .first()
    )


@transaction.atomic
def carry_forward(context, target_encounter, source_encounter=None):
    if source_encounter is None:
        source_encounter = default_source_encounter(target_encounter)
    if source_encounter is None:
        return []

    items = []
    if source_encounter.plan_text:
        item, _ = CarryForwardItem.objects.update_or_create(
            tenant_id=context.tenant_id, target_encounter=target_encounter, field_path='plan_text',
            defaults={
                'source_encounter': source_encounter,
                'source_version_hash': source_encounter.content_hash or source_encounter.compute_content_hash(),
                'copied_value': {'text': source_encounter.plan_text},
            },
        )
        items.append(item)

    for diagnosis in source_encounter.diagnoses.all():
        item, _ = CarryForwardItem.objects.update_or_create(
            tenant_id=context.tenant_id, target_encounter=target_encounter,
            field_path=f'diagnosis:{diagnosis.id}',
            defaults={
                'source_encounter': source_encounter,
                'source_version_hash': source_encounter.content_hash or source_encounter.compute_content_hash(),
                'copied_value': {
                    'code_snapshot': diagnosis.code_snapshot,
                    'description_snapshot': diagnosis.description_snapshot,
                    'certainty': diagnosis.certainty,
                    'rank': diagnosis.rank,
                },
            },
        )
        items.append(item)
    return items


def has_pending_review(target_encounter):
    from .models import ReviewAction
    return CarryForwardItem.objects.filter(
        target_encounter=target_encounter, review_action=ReviewAction.PENDING,
    ).exists()


def review_carry_forward_item(item, action, actor_membership_id):
    from django.utils import timezone

    from .models import ReviewAction

    item.review_action = action
    item.reviewed_at = timezone.now()
    item.reviewed_by_id = actor_membership_id
    item.full_clean()
    item.save()
    if action == ReviewAction.ACCEPTED and item.field_path == 'plan_text':
        item.target_encounter.plan_text = item.copied_value.get('text', '')
        item.target_encounter.save(update_fields=['plan_text'])
    return item
