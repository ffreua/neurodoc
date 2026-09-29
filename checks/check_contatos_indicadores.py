"""Contato editável e pré-cadastro fora dos indicadores e da cota."""
import datetime
import uuid

from django.conf import settings
from django.test import Client

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
settings.SECURE_SSL_REDIRECT = False

from patients.contacts import SELF_RELATIONSHIP
from patients.models import Patient, PatientContact, PatientStatus, RegistrationStage
from reporting.patients import active_patients_count, age_distribution
from tenancy.limits import patient_usage
from tenancy.models import Membership, MembershipStatus, Role, Tenant


falhas = []
tenant = Tenant.objects.get(slug="demo-clinica-a")
operator = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.SECRETARY],
    user__email_verified_at__isnull=False,
).select_related("user").first()
if operator is None:
    operator = Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER],
        user__email_verified_at__isnull=False,
    ).select_related("user").first()
if operator is None:
    print("PULADO: demonstração sem operador de pacientes")
    raise SystemExit(0)

before_active = active_patients_count(tenant)
before_usage = patient_usage(tenant)
before_age = age_distribution(tenant, datetime.date.today())

preliminary = Patient.objects.create(
    tenant=tenant, full_name=f"Pré-cadastro roteiro {uuid.uuid4().hex[:8]}",
    birth_date_unknown_reason="Pré-cadastro de roteiro",
    registration_stage=RegistrationStage.PRELIMINARY,
    status=PatientStatus.ACTIVE,
)
complete = Patient.objects.create(
    tenant=tenant, full_name=f"Paciente roteiro {uuid.uuid4().hex[:8]}",
    birth_date=datetime.date(1985, 5, 20),
    registration_stage=RegistrationStage.COMPLETE,
    status=PatientStatus.ACTIVE,
)
contact = PatientContact.objects.create(
    tenant=tenant, patient=complete, name=complete.full_name,
    relationship=SELF_RELATIONSHIP, phone="11911112222",
    sms_enabled=True, authorized_for_documents=True,
)

print("=== 1. pré-cadastro não entra na carteira, idade nem cota ===")
after_active = active_patients_count(tenant)
after_usage = patient_usage(tenant)
after_age = age_distribution(tenant, datetime.date.today())
print(
    "  carteira", before_active, "->", after_active,
    "cota", before_usage, "->", after_usage,
    "idade desconhecida", before_age["n_unknown"], "->", after_age["n_unknown"],
)
if after_active != before_active + 1:
    falhas.append("a carteira não contou somente o paciente completo criado")
if after_usage != before_usage + 1:
    falhas.append("a cota do plano não contou somente o paciente completo criado")
if after_age["n_unknown"] != before_age["n_unknown"]:
    falhas.append("o pré-cadastro entrou na distribuição etária")

print("=== 2. contato é editável na ficha ===")
client = Client()
client.force_login(operator.user)
session = client.session
session["tenant_id"] = str(tenant.id)
session.save()
response = client.post(
    f"/app/patients/{complete.id}/contacts/{contact.id}/edit/",
    {
        "name": complete.full_name,
        "relationship": SELF_RELATIONSHIP,
        "phone": "11999998888",
        "email": "contato-atualizado@example.com",
        "authorized_for_documents": "on",
        "sms_enabled": "on",
        "email_enabled": "on",
    },
)
contact.refresh_from_db()
print("  status=", response.status_code, "telefone alterado=", contact.phone == "11999998888")
if response.status_code not in (302, 303) or contact.phone != "11999998888":
    falhas.append("a ficha não permite editar o contato existente")
if contact.verified_phone_at is None or contact.verified_email_at is None:
    falhas.append("os canais conferidos na edição não ficaram verificados")

print("=== 3. tabela de localização saiu do painel ===")
owner = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER],
).select_related("user").first()
client.force_login(owner.user)
session = client.session
session["tenant_id"] = str(tenant.id)
session.save()
dashboard_response = client.get("/app/reporting/")
dashboard = dashboard_response.content.decode("utf-8", "replace")
print("  status=", dashboard_response.status_code, "contém Localização=", "Localização" in dashboard)
if dashboard_response.status_code != 200 or "Localização" in dashboard:
    falhas.append("a tabela de Localização continua nos indicadores")

PatientContact.objects.filter(patient__in=[preliminary, complete]).delete()
Patient.objects.filter(id__in=[preliminary.id, complete.id]).delete()

print("---")
if falhas:
    for falha in falhas:
        print("FALHA:", falha)
    raise SystemExit(1)
print("OK: contato muda pela ficha e pré-cadastro não altera indicadores.")
