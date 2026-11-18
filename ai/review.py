from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinical.models import Encounter

from .models import TIPOS_APOSENTADOS, AIReviewState


class ArtifactStale(Exception):
    pass


class AlreadyReviewed(Exception):
    pass


def is_stale(artifact):
    job = artifact.job
    if job.encounter_id is None:
        return artifact.stale
    if job.kind in TIPOS_APOSENTADOS:
        # Leitura de laudo antiga (tipo aposentado na 1.18): a fonte era o
        # PDF, não o texto do atendimento, e o histórico segue lido assim.
        return artifact.stale
    encounter = Encounter.objects.filter(id=job.encounter_id).first()
    return artifact.stale or encounter is None or encounter.row_version != job.source_version


def _guard(artifact, conferir_versao=True):
    if artifact.review_state != AIReviewState.PENDING:
        raise AlreadyReviewed(
            f'Este rascunho já foi revisado ({artifact.get_review_state_display().lower()}).'
        )
    if conferir_versao and is_stale(artifact):
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
    # Recusar não confere a versão do atendimento, só aprovar. A conferência
    # existe para que um texto velho não entre no prontuário; recusar não
    # põe nada lá. Com ela, o salvamento automático — que muda a versão a
    # cada frase — tornava a recusa impossível: o médico recusava e recebia
    # "o prontuário mudou" (achado PD-2026-11-15-06 do ProntDoc,
    # `docs/intercambio/`).
    _guard(artifact, conferir_versao=False)
    artifact.review_state = AIReviewState.REJECTED
    artifact.reviewer = reviewer_membership
    artifact.reviewed_at = timezone.now()
    artifact.motivo_recusa = (reason or '').strip()
    artifact.save(update_fields=['review_state', 'reviewer', 'reviewed_at', 'motivo_recusa'])
    record_audit_event(
        reviewer_membership.user_id, artifact.tenant_id, 'ai.artifact_rejected',
        object_type='ai_artifact', object_id=artifact.id, outcome='success',
        # O motivo é texto livre sobre o caso: fica no rascunho, não na trilha.
        integrity_metadata={'motivo_informado': bool((reason or '').strip())},
    )
    return artifact
