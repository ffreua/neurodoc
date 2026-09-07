"""Leitura de laudo pela IA e a revisão que a transforma em registro.

O ponto central deste módulo é o que ele **não** faz: a IA não escreve no
prontuário. Ela produz um `AIArtifact` com estado de revisão pendente, e o
texto ou os analitos só entram no `ExamResult` quando um médico
identificado aceita o rascunho (RF-11-B). Foi isso que se pediu como
"transcrever o laudo automaticamente": a leitura é automática, a entrada no
registro é de um clique — com o rascunho na tela ao lado do que vai ser
gravado.

A diferença não é burocracia. Extração de PDF erra de formas silenciosas:
confunde a coluna de referência com a de resultado, perde o sinal de menor
que, junta duas linhas de um hemograma. Cada um desses erros, gravado direto
no prontuário sem ninguém olhar, é um dado clínico falso com aparência de
dado conferido.
"""

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import (
    DOCUMENT_SOURCED_KINDS, AIArtifact, AIJob, AIJobKind, AIJobStatus, AIReviewState,
)
from .services import create_job

#: Categoria do exame -> tarefa. Laboratorial vira tabela de analitos;
#: qualquer outro laudo é transcrito como texto.
_KIND_BY_CATEGORY = {
    'laboratory': AIJobKind.LAB_EXTRACTION,
}


class ExtractionUnavailable(Exception):
    pass


def kind_for(exam_result):
    return _KIND_BY_CATEGORY.get(exam_result.category, AIJobKind.REPORT_TRANSCRIPTION)


def request_extraction(access_context, exam_result, purpose='Leitura de laudo anexado'):
    """Enfileira a leitura do laudo deste resultado de exame.

    Devolve o `AIJob`. O estado do job é espelhado em
    `exam_result.extraction_status` para a tela não precisar consultar a
    tabela de jobs.
    """
    from clinical.models import ExtractionStatus

    if exam_result.attachment_id is None:
        raise ExtractionUnavailable('Anexe o laudo antes de pedir a leitura pela IA.')

    job = create_job(
        access_context, kind_for(exam_result), purpose,
        patient_id=exam_result.patient_id, encounter_id=exam_result.encounter_id,
        target_ref={'exam_result_id': str(exam_result.id)},
    )

    if job.status == AIJobStatus.QUEUED:
        from .tasks import prepare_document_and_run

        transaction.on_commit(lambda: prepare_document_and_run.delay(str(job.id)))
        status = ExtractionStatus.QUEUED
        detail = ''
    elif job.status == AIJobStatus.DISABLED:
        status = ExtractionStatus.DISABLED
        detail = 'A leitura por IA está desligada nesta instalação.'
    elif job.status == AIJobStatus.SUCCEEDED:
        status = ExtractionStatus.READY
        detail = ''
    else:
        status = ExtractionStatus.FAILED
        detail = job.status_detail

    exam_result.extraction_status = status
    exam_result.extraction_detail = detail[:255]
    exam_result.save(update_fields=['extraction_status', 'extraction_detail'])
    return job


def sync_exam_result_status(job):
    """Reflete o desfecho do job no resultado de exame."""
    from clinical.models import ExamResult, ExtractionStatus

    if job.kind not in DOCUMENT_SOURCED_KINDS:
        return None
    exam_result = ExamResult.objects.filter(
        tenant_id=job.tenant_id, id=(job.target_ref or {}).get('exam_result_id'),
    ).first()
    if exam_result is None:
        return None

    mapping = {
        AIJobStatus.QUEUED: ExtractionStatus.QUEUED,
        AIJobStatus.RUNNING: ExtractionStatus.RUNNING,
        AIJobStatus.SUCCEEDED: ExtractionStatus.READY,
        AIJobStatus.FAILED: ExtractionStatus.FAILED,
        AIJobStatus.STALE: ExtractionStatus.FAILED,
        AIJobStatus.CANCELLED: ExtractionStatus.NONE,
        AIJobStatus.BLOCKED_PRIVACY: ExtractionStatus.BLOCKED,
        AIJobStatus.DISABLED: ExtractionStatus.DISABLED,
    }
    # Rascunho já revisado não volta atrás: aceitar e depois reprocessar o
    # job não deve apagar da tela o fato de que alguém já conferiu aquilo.
    if exam_result.extraction_status in (ExtractionStatus.ACCEPTED, ExtractionStatus.REJECTED):
        return exam_result
    exam_result.extraction_status = mapping.get(job.status, ExtractionStatus.NONE)
    exam_result.extraction_detail = (job.status_detail or '')[:255]
    exam_result.save(update_fields=['extraction_status', 'extraction_detail'])
    return exam_result


def latest_draft(exam_result):
    """Último rascunho gerado para este resultado de exame, ou None."""
    job = AIJob.objects.filter(
        tenant_id=exam_result.tenant_id,
        kind__in=DOCUMENT_SOURCED_KINDS,
        target_ref__exam_result_id=str(exam_result.id),
    ).order_by('-created_at').first()
    if job is None:
        return None
    return AIArtifact.objects.filter(job=job).select_related('job').order_by('-created_at').first()


def _decimal_or_none(value):
    from decimal import Decimal, InvalidOperation

    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


@transaction.atomic
def accept_draft(artifact, exam_result, reviewer_membership, actor_id):
    """Grava o rascunho revisado no resultado de exame.

    Laboratorial vira linhas de analito; qualquer outro laudo entra como
    texto. Em nenhum dos casos o sistema decide se um valor é normal: a
    classificação sai da comparação com a faixa que o próprio laudo trazia,
    e analito sem faixa fica sem classificação.
    """
    from clinical.models import ExtractionStatus, LabValue

    if artifact.review_state != AIReviewState.PENDING:
        raise ExtractionUnavailable(f'Este rascunho já foi {artifact.get_review_state_display().lower()}.')

    result = artifact.result or {}
    kind = artifact.job.kind
    written = {}

    if kind == AIJobKind.LAB_EXTRACTION:
        LabValue.objects.filter(exam_result=exam_result, source='ai').delete()
        rows = []
        for order, item in enumerate(result.get('analytes') or []):
            rows.append(LabValue(
                tenant_id=exam_result.tenant_id, exam_result=exam_result, order=order,
                analyte=(item.get('analyte') or '')[:200],
                value_text=(item.get('value_text') or '')[:100],
                numeric_value=_decimal_or_none(item.get('numeric_value')),
                unit=(item.get('unit') or '')[:40],
                reference_low=_decimal_or_none(item.get('reference_low')),
                reference_high=_decimal_or_none(item.get('reference_high')),
                reference_text=(item.get('reference_text') or '')[:120],
                source='ai',
            ))
        for row in rows:
            # `save()` calcula o flag a partir da faixa; um `bulk_create`
            # passaria por cima disso e gravaria tudo como sem referência.
            row.save()
        written['analytes'] = len(rows)
        if not exam_result.service_name and result.get('service_name'):
            exam_result.service_name = result['service_name'][:255]
    else:
        exam_result.report_text = (result.get('report_text') or '')[:20000]
        exam_result.conclusion = (result.get('conclusion') or '')[:4000]
        if not exam_result.service_name and result.get('service_name'):
            exam_result.service_name = result['service_name'][:255]
        written['report_chars'] = len(exam_result.report_text)

    exam_result.extraction_status = ExtractionStatus.ACCEPTED
    exam_result.extraction_detail = ''
    exam_result.save()

    artifact.review_state = AIReviewState.ACCEPTED
    artifact.reviewer = reviewer_membership
    artifact.reviewed_at = timezone.now()
    artifact.save(update_fields=['review_state', 'reviewer', 'reviewed_at'])

    record_audit_event(
        actor_id, artifact.tenant_id, 'ai.extraction_accepted',
        object_type='exam_result', object_id=exam_result.id, outcome='success',
        integrity_metadata={'artifact_id': str(artifact.id), 'kind': kind, **written},
    )
    return exam_result


@transaction.atomic
def reject_draft(artifact, exam_result, reviewer_membership, actor_id, reason=''):
    from clinical.models import ExtractionStatus

    if artifact.review_state != AIReviewState.PENDING:
        raise ExtractionUnavailable(f'Este rascunho já foi {artifact.get_review_state_display().lower()}.')
    artifact.review_state = AIReviewState.REJECTED
    artifact.reviewer = reviewer_membership
    artifact.reviewed_at = timezone.now()
    artifact.save(update_fields=['review_state', 'reviewer', 'reviewed_at'])

    exam_result.extraction_status = ExtractionStatus.REJECTED
    exam_result.extraction_detail = reason[:255]
    exam_result.save(update_fields=['extraction_status', 'extraction_detail'])

    record_audit_event(
        actor_id, artifact.tenant_id, 'ai.extraction_rejected',
        object_type='exam_result', object_id=exam_result.id, outcome='success',
        integrity_metadata={'artifact_id': str(artifact.id), 'reason': reason[:255]},
    )
    return exam_result
