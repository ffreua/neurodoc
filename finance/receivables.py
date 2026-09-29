from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
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


def _price_for(tenant, patient, physician, occurred_date, appointment_type=None):
    coverage = _active_coverage(patient, occurred_date)
    payment_category = PaymentCategory.INSURANCE if coverage else PaymentCategory.PRIVATE
    fee_schedule = resolve_price(
        tenant, physician, payment_category, occurred_date,
        plan=coverage.plan if coverage else None,
        appointment_type=appointment_type,
    )
    return fee_schedule


def _create_receivable(*, tenant, patient, encounter, appointment, charge_kind,
                       fee_schedule, competence_date, actor_id, audit_object_type,
                       audit_object_id):
    snapshot = snapshot_from_fee_schedule(fee_schedule)
    today = timezone.now().date()
    receivable = Receivable.objects.create(
        tenant=tenant, patient=patient, encounter=encounter, appointment=appointment,
        charge_kind=charge_kind, fee_snapshot=snapshot,
        expected_amount=fee_schedule.gross_amount, charged_amount=fee_schedule.gross_amount,
        due_date=today + timedelta(days=DUE_DAYS), competence_date=competence_date,
        status=ReceivableStatus.PENDING,
    )
    record_audit_event(
        actor_id, tenant.id, 'finance.receivable_created',
        object_type='receivable', object_id=receivable.id, outcome='success',
        integrity_metadata={
            'origin_type': audit_object_type,
            'origin_id': str(audit_object_id),
        },
    )
    return receivable


@transaction.atomic
def create_receivable_for_appointment(appointment, actor_id, charge_kind=ChargeKind.CONSULTATION):
    """Cria no check-in e é idempotente por agendamento/tipo de cobrança."""
    occurred_date = timezone.localtime(appointment.starts_at).date()
    from clinical.models import Encounter

    compatible_encounters = list(
        Encounter.objects.select_for_update().filter(
            tenant=appointment.tenant,
            patient=appointment.patient,
            physician_membership=appointment.physician_membership,
            occurred_at__date=occurred_date,
        ).filter(
            Q(appointment__isnull=True) | Q(appointment=appointment),
        ).order_by('occurred_at')
    )
    # A ordem dos locks é intencional e igual à finalização: atendimento
    # primeiro, cobrança depois. Inverter uma das duas abre deadlock quando
    # check-in e fechamento acontecem ao mesmo tempo.
    existing = Receivable.objects.select_for_update().filter(
        tenant=appointment.tenant, appointment=appointment, charge_kind=charge_kind,
    ).first()
    if existing is not None:
        return existing
    historical_receivables = list(
        Receivable.objects.select_for_update().filter(
            tenant=appointment.tenant,
            encounter__in=compatible_encounters,
            appointment__isnull=True,
            charge_kind=charge_kind,
        )
    )
    if len(historical_receivables) == 1:
        historical = historical_receivables[0]
        historical.appointment = appointment
        historical.save(update_fields=['appointment', 'updated_at'])
        if historical.encounter.appointment_id is None:
            historical.encounter.appointment = appointment
            historical.encounter.save(update_fields=['appointment', 'updated_at'])
        record_audit_event(
            actor_id, appointment.tenant_id, 'finance.receivable_origin_reconciled',
            object_type='receivable', object_id=historical.id, outcome='success',
            integrity_metadata={'appointment_id': str(appointment.id)},
        )
        return historical
    if len(historical_receivables) > 1 or len(compatible_encounters) > 1:
        # Não há como saber qual prontuário pertence a este horário. Criar
        # mais uma linha seria pior: transformaria ambiguidade em cobrança
        # duplicada. A auditoria deixa o caso para conciliação manual.
        record_audit_event(
            actor_id, appointment.tenant_id, 'finance.receivable_origin_ambiguous',
            object_type='appointment', object_id=appointment.id, outcome='failure',
            integrity_metadata={
                'encounters': len(compatible_encounters),
                'receivables': len(historical_receivables),
            },
        )
        return None

    matched_encounter = compatible_encounters[0] if compatible_encounters else None
    if matched_encounter is not None and matched_encounter.appointment_id is None:
        matched_encounter.appointment = appointment
        matched_encounter.save(update_fields=['appointment', 'updated_at'])
    try:
        fee_schedule = _price_for(
            appointment.tenant, appointment.patient, appointment.physician_membership,
            occurred_date, appointment.type,
        )
    except NoApplicableFeeSchedule:
        record_audit_event(
            actor_id, appointment.tenant_id, 'finance.receivable_pricing_missing',
            object_type='appointment', object_id=appointment.id, outcome='failure',
        )
        return None
    try:
        with transaction.atomic():
            return _create_receivable(
                tenant=appointment.tenant, patient=appointment.patient,
                encounter=matched_encounter, appointment=appointment, charge_kind=charge_kind,
                fee_schedule=fee_schedule, competence_date=occurred_date,
                actor_id=actor_id, audit_object_type='appointment',
                audit_object_id=appointment.id,
            )
    except IntegrityError:
        return Receivable.objects.get(
            tenant=appointment.tenant, appointment=appointment, charge_kind=charge_kind,
        )


@transaction.atomic
def create_receivable_for_encounter(encounter, actor_id, charge_kind=ChargeKind.CONSULTATION):
    """Idempotent on (tenant, encounter, charge_kind): a redelivered
    `clinical.encounter_finalized` event (or a direct re-call) never
    creates a second charge for the same encounter.
    """
    # Serializa com a reconciliação do check-in. Receber uma instância do
    # chamador não a torna bloqueada; ela precisa ser relida nesta transação.
    encounter = (
        encounter.__class__.objects.select_for_update(of=('self',))
        .get(id=encounter.id)
    )
    existing = Receivable.objects.select_for_update().filter(
        tenant=encounter.tenant, encounter=encounter, charge_kind=charge_kind,
    ).first()
    if existing is not None:
        return existing

    if encounter.appointment_id:
        appointment_receivable = Receivable.objects.select_for_update().filter(
            tenant=encounter.tenant, appointment_id=encounter.appointment_id,
            charge_kind=charge_kind,
        ).first()
        if appointment_receivable is not None:
            if appointment_receivable.encounter_id is None:
                appointment_receivable.encounter = encounter
                appointment_receivable.save(update_fields=['encounter', 'updated_at'])
            return appointment_receivable

    occurred_date = timezone.localtime(encounter.occurred_at).date()
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
        fee_schedule = _price_for(
            encounter.tenant, encounter.patient, encounter.physician_membership,
            occurred_date, tipo_de_atendimento,
        )
    except NoApplicableFeeSchedule:
        record_audit_event(
            actor_id, encounter.tenant_id, 'finance.receivable_pricing_missing',
            object_type='encounter', object_id=encounter.id, outcome='failure',
        )
        return None

    try:
        with transaction.atomic():
            receivable = _create_receivable(
                tenant=encounter.tenant, patient=encounter.patient,
                encounter=encounter, appointment=encounter.appointment,
                charge_kind=charge_kind, fee_schedule=fee_schedule,
                competence_date=occurred_date, actor_id=actor_id,
                audit_object_type='encounter', audit_object_id=encounter.id,
            )
    except IntegrityError:
        # A constraint é a última garantia. Reconciliamos pelas duas origens
        # porque a corrida pode ter sido vencida pelo check-in ou pela
        # finalização histórica.
        concurrent = Receivable.objects.filter(
            tenant=encounter.tenant, encounter=encounter, charge_kind=charge_kind,
        ).first()
        if concurrent is None and encounter.appointment_id:
            concurrent = Receivable.objects.filter(
                tenant=encounter.tenant, appointment_id=encounter.appointment_id,
                charge_kind=charge_kind,
            ).first()
        if concurrent is None:
            raise
        if concurrent.encounter_id is None:
            concurrent.encounter = encounter
            concurrent.save(update_fields=['encounter', 'updated_at'])
        return concurrent

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
