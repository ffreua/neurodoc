import hashlib
import json
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinical.models import Encounter
from patients.models import Patient
from tenancy.context import AccessContext

from . import deidentification, privacy_policy
from .context import AIAuthorizationDenied, build_ai_authorization
from .graphs import build_summary_graph, build_summary_prompt
from .models import AIArtifact, AIJob, AIJobStatus
from .providers import ProviderUnavailable, get_chat_model
from .schemas import SCHEMA_VERSION
from .tools import clinical as clinical_tools

DEFAULT_LIMITS = {'timeout_seconds': 30, 'max_output_chars': 20000}


class JobNotRunnable(Exception):
    pass


@transaction.atomic
def create_job(access_context, kind, purpose, patient_id=None, encounter_id=None):
    authorization = build_ai_authorization(access_context, patient_id, encounter_id)

    encounter = Encounter.objects.filter(id=authorization.encounter_id).first() if authorization.encounter_id else None
    source_version = encounter.row_version if encounter else 0
    target = authorization.encounter_id or authorization.patient_id
    idempotency_key = f'{kind}:{target}:{source_version}'

    job, _ = AIJob.objects.get_or_create(
        tenant_id=access_context.tenant_id, idempotency_key=idempotency_key,
        defaults={
            'user_id': authorization.user_id, 'membership_id': authorization.membership_id,
            'patient_id': authorization.patient_id, 'encounter_id': authorization.encounter_id,
            'kind': kind, 'source_version': source_version, 'purpose': purpose[:255],
            'policy_version': privacy_policy.POLICY_VERSION,
            'status': AIJobStatus.QUEUED if settings.AI_ENABLED else AIJobStatus.DISABLED,
            'limits': DEFAULT_LIMITS,
        },
    )
    record_audit_event(
        authorization.user_id, access_context.tenant_id, 'ai.job_created',
        object_type='ai_job', object_id=job.id, outcome='success',
    )
    return job


def _gather_context(authorization, encounter):
    if encounter is None:
        return {}, []
    timeline = clinical_tools.get_patient_timeline(authorization, limit=5)
    findings = clinical_tools.get_examination_findings(authorization, encounter.id)
    diagnoses = clinical_tools.get_diagnoses(authorization, encounter.id)
    context = {'timeline': timeline, 'examination_findings': findings, 'diagnoses': diagnoses}
    source_refs = [{'type': 'encounter', 'id': str(encounter.id), 'version_or_hash': str(encounter.row_version)}]
    return context, source_refs


def _previous_artifact(job):
    qs = AIArtifact.objects.filter(job__tenant_id=job.tenant_id, job__kind=job.kind)
    if job.encounter_id:
        qs = qs.filter(job__encounter_id=job.encounter_id)
    else:
        qs = qs.filter(job__patient_id=job.patient_id, job__encounter_id__isnull=True)
    return qs.exclude(job_id=job.id).order_by('-created_at').first()


def _fail(job, status, detail, action):
    job.status = status
    job.status_detail = detail[:255]
    job.save(update_fields=['status', 'status_detail'])
    record_audit_event(job.user_id, job.tenant_id, action, object_type='ai_job', object_id=job.id, outcome='denied')
    return None


@transaction.atomic
def run_job(job_id):
    """Called from the Celery task, never inline in the request. Every
    authorization/staleness check is redone here against the current
    database state -- the job row is a *request*, not a pre-approved
    ticket: a membership revoked or an encounter changed after `create_job`
    must still block the actual external call.
    """
    job = AIJob.objects.select_for_update().get(id=job_id)
    if job.status != AIJobStatus.QUEUED:
        raise JobNotRunnable(f'Job {job.id} is {job.status}, not queued')

    fake_context = AccessContext(
        user_id=job.user_id, tenant_id=job.tenant_id, membership_id=job.membership_id,
        permissions=frozenset(), request_id=uuid.uuid4(),
    )
    try:
        authorization = build_ai_authorization(fake_context, job.patient_id, job.encounter_id)
    except AIAuthorizationDenied as exc:
        return _fail(job, AIJobStatus.FAILED, str(exc), 'ai.job_authorization_denied')

    encounter = Encounter.objects.filter(id=job.encounter_id).first() if job.encounter_id else None
    if job.encounter_id and (encounter is None or encounter.row_version != job.source_version):
        return _fail(job, AIJobStatus.STALE, 'Source changed since the job was queued', 'ai.job_stale')

    patient = Patient.objects.filter(id=job.patient_id).first() if job.patient_id else None
    context, source_refs = _gather_context(authorization, encounter)
    deidentified_text = deidentification.deidentify_text(json.dumps(context, ensure_ascii=False), patient)

    decision = privacy_policy.evaluate_privacy_policy(encounter, deidentified_text)
    if not decision.allowed:
        return _fail(job, AIJobStatus.BLOCKED_PRIVACY, decision.reason, 'ai.job_blocked_privacy')

    job.source_hash = hashlib.sha256(deidentified_text.encode()).hexdigest()
    job.status = AIJobStatus.RUNNING
    job.save(update_fields=['source_hash', 'status'])

    try:
        chat_model = get_chat_model()
    except ProviderUnavailable as exc:
        return _fail(job, AIJobStatus.FAILED, str(exc), 'ai.job_provider_unavailable')

    prompt = build_summary_prompt(deidentified_text)
    graph = build_summary_graph(chat_model, max_output_chars=job.limits.get('max_output_chars', 20000))
    result_state = graph.invoke({
        'prompt': prompt, 'timeout_seconds': job.limits.get('timeout_seconds', 30),
        'raw_response': None, 'artifact': None, 'error': None,
    })

    if result_state.get('error'):
        return _fail(job, AIJobStatus.FAILED, result_state['error'], 'ai.job_failed')

    artifact_data = dict(result_state['artifact'])
    artifact_data['source_refs'] = source_refs or artifact_data.get('source_refs', [])
    artifact = AIArtifact.objects.create(
        tenant_id=job.tenant_id, job=job, schema_version=SCHEMA_VERSION, provider=settings.AI_PROVIDER,
        model=settings.AI_MODEL, prompt_version='v1', source_refs=artifact_data['source_refs'],
        result=artifact_data, supersedes=_previous_artifact(job),
    )
    job.status = AIJobStatus.SUCCEEDED
    job.save(update_fields=['status'])
    record_audit_event(
        job.user_id, job.tenant_id, 'ai.job_succeeded',
        object_type='ai_job', object_id=job.id, outcome='success',
    )
    return artifact


def cancel_job(job, actor_id):
    job.cancel_requested_at = timezone.now()
    if job.status in (AIJobStatus.QUEUED, AIJobStatus.RUNNING):
        job.status = AIJobStatus.CANCELLED
    job.save(update_fields=['cancel_requested_at', 'status'])
    record_audit_event(
        actor_id, job.tenant_id, 'ai.job_cancelled', object_type='ai_job', object_id=job.id, outcome='success',
    )
    return job
