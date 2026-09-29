"""Check-in gera uma única cobrança e o atendimento reaproveita sua origem."""
import datetime
import uuid

from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

from clinical.models import Encounter, EncounterKind, EncounterStatus
from finance import receivables as receivable_services
from finance.models import ChargeKind, FeeSchedule, PaymentCategory, Receivable
from patients.models import Patient, PatientStatus, RegistrationStage
from scheduling.models import Appointment, AppointmentStatus
from scheduling.models import AppointmentType
from scheduling.services import check_in
from tenancy.models import Tenant


falhas = []
tenant = Tenant.objects.get(slug="demo-clinica-a")
today = timezone.localdate()
fee = (
    FeeSchedule.objects.filter(
        tenant=tenant,
        payment_category=PaymentCategory.PRIVATE,
        physician__isnull=False,
        effective_from__lte=today,
    )
    .filter(effective_to__isnull=True)
    .select_related("physician")
    .first()
    or FeeSchedule.objects.filter(
        tenant=tenant,
        payment_category=PaymentCategory.PRIVATE,
        physician__isnull=False,
        effective_from__lte=today,
        effective_to__gte=today,
    ).select_related("physician").first()
)
if fee is None or fee.physician_id is None:
    print("PULADO: demonstração sem honorário particular vigente por médico")
    raise SystemExit(0)
temporary_fee = None
if not fee.appointment_type:
    temporary_fee = FeeSchedule.objects.create(
        tenant=tenant,
        physician=fee.physician,
        payment_category=PaymentCategory.PRIVATE,
        appointment_type=AppointmentType.FIRST_VISIT,
        gross_amount=fee.gross_amount,
        doctor_share_amount=fee.doctor_share_amount,
        effective_from=today,
        effective_to=today,
    )
    fee = temporary_fee

patient = Patient.objects.create(
    tenant=tenant,
    full_name=f"Cobrança roteiro {uuid.uuid4().hex[:8]}",
    birth_date=datetime.date(1980, 1, 1),
    registration_stage=RegistrationStage.COMPLETE,
    status=PatientStatus.ACTIVE,
)
starts_at = timezone.now()
ends_at = starts_at + datetime.timedelta(minutes=40)
appointment = Appointment.objects.create(
    tenant=tenant,
    patient=patient,
    physician_membership=fee.physician,
    starts_at=starts_at,
    ends_at=ends_at,
    occupied_range=DateTimeTZRange(starts_at, ends_at, bounds="[)"),
    status=AppointmentStatus.SCHEDULED,
    type=fee.appointment_type,
    is_overbook=True,
    override_reason="Roteiro automatizado",
    override_by=fee.physician,
)

print("=== 1. check-in gera a cobrança pela modalidade agendada ===")
check_in(appointment, fee.physician.user_id)
receivables = Receivable.objects.filter(tenant=tenant, patient=patient)
print("  cobranças após check-in=", receivables.count())
if receivables.count() != 1:
    falhas.append("o check-in não gerou exatamente uma cobrança")
elif receivables.first().fee_snapshot.get("appointment_type") != appointment.type:
    falhas.append("a cobrança não usou o tipo da agenda")

print("=== 2. geração é idempotente e o prontuário adota a mesma origem ===")
create_for_appointment = getattr(receivable_services, "create_receivable_for_appointment", None)
if create_for_appointment is None:
    falhas.append("ainda não existe geração de cobrança por agendamento")
else:
    create_for_appointment(appointment, fee.physician.user_id)
    create_for_appointment(appointment, fee.physician.user_id)

encounter = Encounter.objects.create(
    tenant=tenant,
    patient=patient,
    physician_membership=fee.physician,
    appointment=appointment,
    occurred_at=starts_at,
    kind=EncounterKind.FREE_TEXT,
    status=EncounterStatus.FINALIZED,
    finalized_at=timezone.now(),
    finalized_by=fee.physician,
)
linked = receivable_services.create_receivable_for_encounter(
    encounter, fee.physician.user_id, ChargeKind.CONSULTATION,
)
print("  cobranças após repetição e prontuário=", receivables.count())
if receivables.count() != 1:
    falhas.append("a cobrança do check-in foi duplicada pelo prontuário")
if linked is not None and getattr(linked, "appointment_id", None) != appointment.id:
    falhas.append("a cobrança não preservou o agendamento como origem")
if linked is not None and linked.encounter_id != encounter.id:
    falhas.append("o atendimento não foi associado à cobrança já criada")

print("=== 3. cobrança histórica do prontuário é reconciliada, não duplicada ===")
patient2 = Patient.objects.create(
    tenant=tenant,
    full_name=f"Reconciliação roteiro {uuid.uuid4().hex[:8]}",
    birth_date=datetime.date(1981, 2, 2),
    registration_stage=RegistrationStage.COMPLETE,
    status=PatientStatus.ACTIVE,
)
starts2 = timezone.now()
ends2 = starts2 + datetime.timedelta(minutes=40)
appointment2 = Appointment.objects.create(
    tenant=tenant, patient=patient2, physician_membership=fee.physician,
    starts_at=starts2, ends_at=ends2,
    occupied_range=DateTimeTZRange(starts2, ends2, bounds="[)"),
    status=AppointmentStatus.SCHEDULED, type=fee.appointment_type,
    is_overbook=True, override_reason="Roteiro de reconciliação", override_by=fee.physician,
)
encounter2 = Encounter.objects.create(
    tenant=tenant, patient=patient2, physician_membership=fee.physician,
    occurred_at=starts2, kind=EncounterKind.STRUCTURED,
    status=EncounterStatus.FINALIZED, finalized_at=timezone.now(), finalized_by=fee.physician,
)
historic = receivable_services.create_receivable_for_encounter(encounter2, fee.physician.user_id)
check_in(appointment2, fee.physician.user_id)
historic.refresh_from_db()
historic_count = Receivable.objects.filter(tenant=tenant, patient=patient2).count()
print("  cobranças=", historic_count, "agendamento reconciliado=", historic.appointment_id == appointment2.id)
if historic_count != 1 or historic.appointment_id != appointment2.id:
    falhas.append("o check-in duplicou ou não reconciliou a cobrança histórica do atendimento")

Receivable.objects.filter(tenant=tenant, patient=patient).delete()
Receivable.objects.filter(tenant=tenant, patient=patient2).delete()
Encounter.objects.filter(id=encounter.id).delete()
Encounter.objects.filter(id=encounter2.id).delete()
Appointment.objects.filter(id=appointment.id).delete()
Appointment.objects.filter(id=appointment2.id).delete()
Patient.objects.filter(id=patient.id).delete()
Patient.objects.filter(id=patient2.id).delete()
if temporary_fee is not None:
    temporary_fee.delete()

print("---")
if falhas:
    for falha in falhas:
        print("FALHA:", falha)
    raise SystemExit(1)
print("OK: check-in cobra uma vez e o atendimento reaproveita a cobrança.")
