from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import ChargeKind, PaymentCategory, Receivable, ReceivableStatus
from .pricing import NoApplicableFeeSchedule, resolve_price, snapshot_from_fee_schedule

DUE_DAYS = 30


def _active_coverage(patient, at):
    for coverage in patient.coverages.all():
        if coverage.starts_on and coverage.starts_on > at:
            continue
        if coverage.ends_on and coverage.ends_on < at:
            continue
        return coverage
    return None


@transaction.atomic
def create_receivable_for_encounter(encounter, actor_id, charge_kind=ChargeKind.CONSULTATION):
    """Idempotent on (tenant, encounter, charge_kind): a redelivered
    `clinical.encounter_finalized` event (or a direct re-call) never
    creates a second charge for the same encounter.
    """
    existing = Receivable.objects.filter(tenant=encounter.tenant, encounter=encounter, charge_kind=charge_kind).first()
    if existing is not None:
        return existing

    occurred_date = encounter.occurred_at.date()
    coverage = _active_coverage(encounter.patient, occurred_date)
    payment_category = PaymentCategory.INSURANCE if coverage else PaymentCategory.PRIVATE
    try:
        # De que tipo foi este atendimento -- primeira consulta,
        # seguimento, retorno. Vem do agendamento que o originou, que e
        # onde a agenda ja registra isso.
        #
        # Encaixe e paciente que chega sem marcar nao tem agendamento:
        # passam nulo, caem na regra que vale para qualquer tipo, e e
        # exatamente o que acontecia com todo atendimento antes deste
        # campo existir.
        tipo_de_atendimento = encounter.appointment.type if encounter.appointment_id else None
        fee_schedule = resolve_price(
            encounter.tenant, encounter.physician_membership, payment_category, occurred_date,
            plan=coverage.plan if coverage else None,
            appointment_type=tipo_de_atendimento,
        )
    except NoApplicableFeeSchedule:
        record_audit_event(
            actor_id, encounter.tenant_id, 'finance.receivable_pricing_missing',
            object_type='encounter', object_id=encounter.id, outcome='failure',
        )
        return None

    snapshot = snapshot_from_fee_schedule(fee_schedule)
    today = timezone.now().date()
    try:
        with transaction.atomic():
            receivable = Receivable.objects.create(
                tenant=encounter.tenant, patient=encounter.patient, encounter=encounter, charge_kind=charge_kind,
                fee_snapshot=snapshot, expected_amount=fee_schedule.gross_amount,
                charged_amount=fee_schedule.gross_amount, due_date=today + timedelta(days=DUE_DAYS),
                competence_date=occurred_date, status=ReceivableStatus.PENDING,
            )
    except IntegrityError:
        # Lost a race against a concurrent call for the same encounter --
        # the unique constraint is the real guarantee, this is just a
        # graceful return instead of a 500.
        return Receivable.objects.get(tenant=encounter.tenant, encounter=encounter, charge_kind=charge_kind)

    record_audit_event(
        actor_id, encounter.tenant_id, 'finance.receivable_created',
        object_type='receivable', object_id=receivable.id, outcome='success',
    )
    return receivable


def cancel_receivable(receivable, actor_id, reason):
    receivable.status = ReceivableStatus.CANCELLED
    receivable.cancellation_reason = reason[:255]
    receivable.save(update_fields=['status', 'cancellation_reason'])
    record_audit_event(
        actor_id, receivable.tenant_id, 'finance.receivable_cancelled',
        object_type='receivable', object_id=receivable.id, outcome='success',
    )
    return receivable
