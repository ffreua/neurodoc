"""Conclusão visível de jobs e revisão tardia de laudo como adendo."""
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import Client

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
settings.SECURE_SSL_REDIRECT = False

from ai import services, tasks
from ai.models import AIArtifact, AIJob, AIJobKind, AIJobStatus
from clinical.models import ClinicalAmendment, Encounter, EncounterStatus, ExamResult, ExtractionStatus
from notifications.models import Notification
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant


falhas = []
tenant = Tenant.objects.get(slug="demo-clinica-a")
doctor = next((
    membership for membership in Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).select_related("user")
    if membership.can_practice_clinically()
), None)
encounter = Encounter.objects.filter(
    tenant=tenant, physician_membership=doctor, status=EncounterStatus.FINALIZED,
).first() if doctor else None
if doctor is None or encounter is None:
    print("PULADO: demonstração sem médico verificado e atendimento finalizado")
    raise SystemExit(0)

ctx = AccessContext(
    user_id=doctor.user_id, tenant_id=tenant.id, membership_id=doctor.id,
    permissions=frozenset(), request_id=uuid.uuid4(),
)
client = Client()
client.force_login(doctor.user)
session = client.session
session["tenant_id"] = str(tenant.id)
session.save()

created_jobs = []
created_results = []
created_amendments = []

print("=== 1. laudo tem prazo apropriado para documento ===")
limits = services._limits_for(AIJobKind.LAB_EXTRACTION)
print("  timeout=", limits["timeout_seconds"])
if limits["timeout_seconds"] < 180:
    falhas.append("a leitura documental ainda expira em menos de 180 segundos")

print("=== 2. tela de job ativo se atualiza sozinha ===")
job = AIJob.objects.create(
    tenant=tenant, user=doctor.user, membership=doctor,
    patient=encounter.patient, encounter=encounter,
    kind=AIJobKind.ENCOUNTER_SUMMARY, source_version=encounter.row_version,
    purpose="roteiro de atualização", status=AIJobStatus.QUEUED,
    limits={"timeout_seconds": 30, "max_output_chars": 20000},
    idempotency_key=f"roteiro-async-{uuid.uuid4()}",
)
created_jobs.append(job)
html = client.get(f"/app/ai/jobs/{job.id}/").content.decode("utf-8", "replace")
atualiza = "job-status.js" in html and "data-nd-ai-job-pending" in html
print("  atualização presente=", atualiza)
if not atualiza:
    falhas.append("a tela do job não acompanha a conclusão enquanto está aberta")

print("=== 3. tarefa concluída cria notificação navegável ===")
def concluir(job_id):
    current = AIJob.objects.get(id=job_id)
    artifact = AIArtifact.objects.create(
        tenant=tenant, job=current, schema_version="v1", provider="roteiro",
        model="roteiro", prompt_version="v3", result={"summary": "Resumo"},
    )
    current.status = AIJobStatus.SUCCEEDED
    current.save(update_fields=["status"])
    return artifact

with patch("ai.tasks.run_job", side_effect=concluir):
    tasks.run_ai_job(str(job.id))
notified = Notification.objects.filter(
    tenant=tenant, user=doctor.user, target_type="ai_job", target_id=job.id,
).exists()
print("  notificação=", notified)
if not notified:
    falhas.append("a conclusão do resumo não cria notificação para quem pediu")

print("=== 4. rascunho concluído após finalização entra como adendo ===")
exam = ExamResult.objects.create(
    tenant=tenant, encounter=encounter, patient=encounter.patient,
    category="laboratory", name="Hemograma do roteiro", extraction_status=ExtractionStatus.READY,
)
created_results.append(exam)
lab_job = AIJob.objects.create(
    tenant=tenant, user=doctor.user, membership=doctor,
    patient=encounter.patient, encounter=encounter,
    kind=AIJobKind.LAB_EXTRACTION, target_ref={"exam_result_id": str(exam.id)},
    source_version=0, purpose="roteiro de laudo", status=AIJobStatus.SUCCEEDED,
    limits={"timeout_seconds": 180, "max_output_chars": 60000},
    idempotency_key=f"roteiro-laudo-{uuid.uuid4()}",
)
created_jobs.append(lab_job)
artifact = AIArtifact.objects.create(
    tenant=tenant, job=lab_job, schema_version="v1", provider="roteiro", model="roteiro",
    prompt_version="v3", result={
        "analytes": [{
            "analyte": "Hemoglobina", "value_text": "13,5", "numeric_value": 13.5,
            "unit": "g/dL", "reference_low": 12, "reference_high": 16,
            "reference_text": "12 a 16",
        }],
        "disclaimer": "Revisão médica obrigatória.",
    },
)
antes = encounter.amendments.count()
response = client.post(
    f"/app/clinical/{encounter.id}/exames/{exam.id}/rascunho/", {"action": "accept"},
)
depois = encounter.amendments.count()
artifact.refresh_from_db()
exam.refresh_from_db()
print(
    "  status=", response.status_code, "adendos=", antes, "->", depois,
    "revisão=", artifact.review_state, "exame imutável=", exam.extraction_status == ExtractionStatus.READY,
)
if (
    response.status_code not in (302, 303)
    or depois != antes + 1
    or artifact.review_state != "accepted"
    or exam.extraction_status != ExtractionStatus.READY
):
    falhas.append("a revisão tardia do laudo não foi incorporada como adendo")
else:
    created_amendments.extend(encounter.amendments.order_by("-created_at")[:1])

Notification.objects.filter(target_type="ai_job", target_id__in=[j.id for j in created_jobs]).delete()
for amendment in created_amendments:
    amendment.delete()
AIArtifact.objects.filter(job__in=created_jobs).delete()
AIJob.objects.filter(id__in=[j.id for j in created_jobs]).delete()
ExamResult.objects.filter(id__in=[r.id for r in created_results]).delete()

print("---")
if falhas:
    for falha in falhas:
        print("FALHA:", falha)
    raise SystemExit(1)
print("OK: jobs avisam e laudos tardios entram por adendo revisado.")
