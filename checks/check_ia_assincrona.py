"""Conclusão visível de jobs de IA.

Até a 1.17 este roteiro cobria também a leitura de laudo pela IA (prazo do
job documental e o rascunho revisado depois da finalização entrando como
adendo). A leitura saiu na 1.18; o que a substitui é
`check_leitura_retirada.py`, que confere que ela saiu por inteiro.
"""
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import Client

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
settings.SECURE_SSL_REDIRECT = False

from ai import services, tasks
from ai.models import AIArtifact, AIJob, AIJobKind, AIJobStatus
from clinical.models import Encounter, EncounterStatus
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

print("=== 1. tela de job ativo se atualiza sozinha ===")
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

print("=== 2. tarefa concluída cria notificação navegável ===")
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

Notification.objects.filter(target_type="ai_job", target_id__in=[j.id for j in created_jobs]).delete()
AIArtifact.objects.filter(job__in=created_jobs).delete()
AIJob.objects.filter(id__in=[j.id for j in created_jobs]).delete()

print("---")
if falhas:
    for falha in falhas:
        print("FALHA:", falha)
    raise SystemExit(1)
print("OK: jobs de IA avisam quando terminam e a tela acompanha.")
