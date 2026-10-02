from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinical.models import Encounter

from .models import DOCUMENT_SOURCED_KINDS, AIReviewState


class ArtifactStale(Exception):
    pass


class AlreadyReviewed(Exception):
    pass


def is_stale(artifact):
    job = artifact.job
    if job.encounter_id is None:
        return artifact.stale
    if job.kind in DOCUMENT_SOURCED_KINDS:
        # A fonte é o laudo anexado, não o texto do atendimento: corrigir a
        # conduta não invalida a leitura de um PDF que não mudou.
        return artifact.stale
    encounter = Encounter.objects.filter(id=job.encounter_id).first()
    return artifact.stale or encounter is None or encounter.row_version != job.source_version


def _guard(artifact):
    if artifact.review_state != AIReviewState.PENDING:
        raise AlreadyReviewed(
            f'Este rascunho já foi revisado ({artifact.get_review_state_display().lower()}).'
        )
    if is_stale(artifact):
        if not artifact.stale:
            artifact.stale = True
            artifact.save(update_fields=['stale'])
        raise ArtifactStale(
            'O prontuário mudou depois que este rascunho foi gerado. '
            'Gere outro antes de aprovar.'
        )


@transaction.atomic
def accept_artifact(artifact, reviewer_membership):
    """Accepting an AI draft is purely an editorial judgment on the text --
    it never signs, prescribes, or issues anything. A physician who wants
    the content in a real medical document still goes through the normal
    MedicalDocument draft/review/sign flow (S07), starting from this text
    as a starting point, not as a shortcut around it.
    """
    _guard(artifact)
    artifact.review_state = AIReviewState.ACCEPTED
    artifact.reviewer = reviewer_membership
    artifact.reviewed_at = timezone.now()
    artifact.save(update_fields=['review_state', 'reviewer', 'reviewed_at'])
    record_audit_event(
        reviewer_membership.user_id, artifact.tenant_id, 'ai.artifact_accepted',
        object_type='ai_artifact', object_id=artifact.id, outcome='success',
    )
    return artifact


@transaction.atomic
def edit_artifact(artifact, reviewer_membership, edited_result):
    _guard(artifact)
    artifact.result = edited_result
    artifact.review_state = AIReviewState.EDITED
    artifact.reviewer = reviewer_membership
    artifact.reviewed_at = timezone.now()
    artifact.save(update_fields=['result', 'review_state', 'reviewer', 'reviewed_at'])
    record_audit_event(
        reviewer_membership.user_id, artifact.tenant_id, 'ai.artifact_edited',
        object_type='ai_artifact', object_id=artifact.id, outcome='success',
    )
    return artifact


@transaction.atomic
def reject_artifact(artifact, reviewer_membership, reason):
    _guard(artifact)
    artifact.review_state = AIReviewState.REJECTED
    artifact.reviewer = reviewer_membership
    artifact.reviewed_at = timezone.now()
    artifact.save(update_fields=['review_state', 'reviewer', 'reviewed_at'])
    record_audit_event(
        reviewer_membership.user_id, artifact.tenant_id, 'ai.artifact_rejected',
        object_type='ai_artifact', object_id=artifact.id, outcome='success',
        integrity_metadata={'reason': reason[:255]},
    )
    return artifact
