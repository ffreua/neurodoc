from django.db import models

from base.models import TenantModel

# Django's app loader only auto-imports `<app>.models`; chat models live in
# their own module (ai/chat_models.py, per the PRD's component naming) and
# must be re-exported here so they register under the `ai` app label.
from .chat_models import (  # noqa: F401,E402
    ChatMessage, ChatMessageRole, ChatMessageState, ChatSession, ChatSessionStatus,
)


class AIJobKind(models.TextChoices):
    ENCOUNTER_SUMMARY = 'encounter_summary', 'Encounter summary'
    PATIENT_SUMMARY = 'patient_summary', 'Patient summary'


class AIJobStatus(models.TextChoices):
    DISABLED = 'disabled', 'Disabled'
    BLOCKED_PRIVACY = 'blocked_privacy', 'Blocked (privacy)'
    QUEUED = 'queued', 'Queued'
    RUNNING = 'running', 'Running'
    SUCCEEDED = 'succeeded', 'Succeeded'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'
    STALE = 'stale', 'Stale'


class AIReviewState(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACCEPTED = 'accepted', 'Accepted'
    EDITED = 'edited', 'Edited'
    REJECTED = 'rejected', 'Rejected'


class AIJob(TenantModel):
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='ai_jobs')
    membership = models.ForeignKey('tenancy.Membership', on_delete=models.PROTECT, related_name='ai_jobs')
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, null=True, blank=True, related_name='ai_jobs',
    )
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.PROTECT, null=True, blank=True, related_name='ai_jobs',
    )
    kind = models.CharField(max_length=40, choices=AIJobKind.choices)
    source_version = models.PositiveBigIntegerField()
    source_hash = models.CharField(max_length=64, blank=True)
    purpose = models.CharField(max_length=255)
    policy_version = models.CharField(max_length=20, default='v1')
    status = models.CharField(max_length=20, choices=AIJobStatus.choices, default=AIJobStatus.QUEUED)
    status_detail = models.CharField(max_length=255, blank=True)
    limits = models.JSONField(default=dict, blank=True)
    task_id = models.CharField(max_length=100, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=150)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'idempotency_key'], name='ai_aijob_idempotency_uniq'),
        ]

    def __str__(self):
        return f'{self.kind} ({self.status})'


class AIArtifact(TenantModel):
    job = models.ForeignKey(AIJob, on_delete=models.PROTECT, related_name='artifacts')
    schema_version = models.CharField(max_length=20)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=20)
    source_refs = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    review_state = models.CharField(max_length=20, choices=AIReviewState.choices, default=AIReviewState.PENDING)
    reviewer = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='superseded_by',
    )
    stale = models.BooleanField(default=False)

    def __str__(self):
        return f'artifact for job {self.job_id} ({self.review_state})'
