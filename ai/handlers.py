import uuid

from django.conf import settings

from clinical.models import Encounter
from tenancy.context import AccessContext

from . import services
from .models import AIJobKind, AIJobStatus
from .tasks import run_ai_job


def handle_encounter_finalized(event):
    """RF-11.01: analysis only runs when both the platform (AI_ENABLED)
    and the tenant (Tenant.settings['ai_encounter_summary_enabled']) opt
    in -- neither alone is enough. A tenant that never turned this on gets
    no AIJob at all, not a disabled one.
    """
    if not settings.AI_ENABLED:
        return
    encounter = Encounter.objects.filter(id=event.payload_minimal['encounter_id']).first()
    if encounter is None or encounter.finalized_by_id is None:
        return
    tenant = encounter.tenant
    if not (tenant.settings or {}).get('ai_encounter_summary_enabled', False):
        return

    fake_context = AccessContext(
        user_id=encounter.finalized_by.user_id, tenant_id=tenant.id,
        membership_id=encounter.finalized_by_id, permissions=frozenset(), request_id=uuid.uuid4(),
    )
    job = services.create_job(
        fake_context, AIJobKind.ENCOUNTER_SUMMARY, purpose='Resumo automático ao finalizar atendimento',
        patient_id=encounter.patient_id, encounter_id=encounter.id,
    )
    if job.status == AIJobStatus.QUEUED:
        run_ai_job.delay(str(job.id))
