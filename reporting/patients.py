import datetime
from decimal import Decimal

from django.db.models import Count, Min

from clinical.models import Encounter, EncounterDiagnosis, EncounterStatus
from patients.models import Patient, PatientStatus
from scheduling.models import Appointment, AppointmentStatus

SMALL_CELL_THRESHOLD = 5


def active_patients_count(tenant):
    """"Carteira ativa" -- current PatientStatus.ACTIVE count. Status is
    not versioned over time, so this is always "as of now", never a true
    historical point-in-time reconstruction (documented limitation).
    """
    return Patient.objects.filter(tenant=tenant, status=PatientStatus.ACTIVE).count()


def patients_seen(tenant, start, end, physician_membership=None):
    """COUNT DISTINCT(patient_id) em encounters finalizados no período."""
    qs = Encounter.objects.filter(
        tenant=tenant, status=EncounterStatus.FINALIZED, occurred_at__date__gte=start, occurred_at__date__lte=end,
    )
    if physician_membership is not None:
        qs = qs.filter(physician_membership=physician_membership)
    return qs.values('patient_id').distinct().count()


def _first_finalized_date_per_patient(tenant, patient_ids=None):
    qs = Encounter.objects.filter(tenant=tenant, status=EncounterStatus.FINALIZED)
    if patient_ids is not None:
        qs = qs.filter(patient_id__in=patient_ids)
    return dict(
        qs.values('patient_id').annotate(first_at=Min('occurred_at')).values_list('patient_id', 'first_at'),
    )


def new_patients_count(tenant, start, end):
    """Primeira consulta finalizada no TENANT (não por médico) ocorrida no
    período -- a data de referência é a primeira data em qualquer médico.
    """
    encounters_in_period = Encounter.objects.filter(
        tenant=tenant, status=EncounterStatus.FINALIZED, occurred_at__date__gte=start, occurred_at__date__lte=end,
    )
    patient_ids = list(encounters_in_period.values_list('patient_id', flat=True).distinct())
    first_dates = _first_finalized_date_per_patient(tenant, patient_ids)
    return sum(1 for pid, first_at in first_dates.items() if start <= first_at.date() <= end)


def returning_patients_count(tenant, start, end):
    """Atendimentos cujo paciente já tinha consulta finalizada anterior no
    escopo escolhido -- nunca inferido pelo tipo de agendamento.
    """
    encounters_in_period = Encounter.objects.filter(
        tenant=tenant, status=EncounterStatus.FINALIZED, occurred_at__date__gte=start, occurred_at__date__lte=end,
    )
    count = 0
    for encounter in encounters_in_period.select_related(None).only('id', 'patient_id', 'occurred_at'):
        earlier_exists = Encounter.objects.filter(
            tenant=tenant, status=EncounterStatus.FINALIZED, patient_id=encounter.patient_id,
            occurred_at__lt=encounter.occurred_at,
        ).exists()
        if earlier_exists:
            count += 1
    return count


def no_show_rate(tenant, start, end, physician_membership=None):
    """no_show / (completed + no_show) de consultas com desfecho no
    período -- canceladas/futuras/em andamento excluídas; `n` sempre
    retornado ao lado da taxa.
    """
    qs = Appointment.objects.filter(
        tenant=tenant, status__in=[AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW],
        starts_at__date__gte=start, starts_at__date__lte=end,
    )
    if physician_membership is not None:
        qs = qs.filter(physician_membership=physician_membership)
    completed = qs.filter(status=AppointmentStatus.COMPLETED).count()
    no_show = qs.filter(status=AppointmentStatus.NO_SHOW).count()
    n = completed + no_show
    rate = Decimal(no_show) / Decimal(n) if n else None
    return {'rate': rate, 'n': n, 'completed': completed, 'no_show': no_show}


def age_distribution(tenant, as_of_date):
    """Idade na data de corte; desconhecidos (sem birth_date) separados,
    nunca misturados na mediana/IQR.
    """
    patients = Patient.objects.filter(tenant=tenant)
    known_ages = []
    unknown_count = 0
    for patient in patients.only('birth_date', 'estimated_birth_year'):
        if patient.birth_date:
            age = (as_of_date - patient.birth_date).days / 365.25
            known_ages.append(age)
        else:
            unknown_count += 1
    known_ages.sort()
    n = len(known_ages)
    median = None
    iqr = None
    if n:
        median = known_ages[n // 2] if n % 2 else (known_ages[n // 2 - 1] + known_ages[n // 2]) / 2
        q1 = known_ages[n // 4]
        q3 = known_ages[(3 * n) // 4] if (3 * n) // 4 < n else known_ages[-1]
        iqr = (q1, q3)
    return {'n_known': n, 'n_unknown': unknown_count, 'median_years': median, 'iqr_years': iqr}


def location_distribution(tenant):
    """Pacientes distintos por município/UF; sem endereço exato; células
    pequenas (< SMALL_CELL_THRESHOLD) agregadas em "outros" para reduzir
    risco de reidentificação por subtração de totais.
    """
    rows = (
        Patient.objects.filter(tenant=tenant)
        .values('city', 'state').annotate(n=Count('id')).order_by('-n')
    )
    visible, suppressed_total = [], 0
    for row in rows:
        if not row['city'] and not row['state']:
            visible.append({'city': 'Desconhecido', 'state': '', 'n': row['n']})
        elif row['n'] < SMALL_CELL_THRESHOLD:
            suppressed_total += row['n']
        else:
            visible.append({'city': row['city'], 'state': row['state'], 'n': row['n']})
    if suppressed_total:
        visible.append({'city': 'Outros (células pequenas agregadas)', 'state': '', 'n': suppressed_total})
    return visible


def diagnosis_distribution(tenant, start, end):
    """Pacientes distintos por código e certeza clínica -- hipóteses e
    confirmados sempre em séries separadas, nunca somados.
    """
    qs = EncounterDiagnosis.objects.filter(
        tenant=tenant, encounter__status=EncounterStatus.FINALIZED,
        encounter__occurred_at__date__gte=start, encounter__occurred_at__date__lte=end,
    )
    result = {}
    for certainty in ('suspected', 'confirmed', 'refuted'):
        rows = (
            qs.filter(certainty=certainty)
            .values('code_snapshot').annotate(n=Count('encounter__patient_id', distinct=True))
            .order_by('-n')
        )
        result[certainty] = list(rows)
    return result


def _period_bounds(start, end):
    """As datas como `date`, venham da tela ou de um parâmetro JSON do Celery."""
    if isinstance(start, str):
        start = datetime.date.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.date.fromisoformat(end)
    return start, end


def patients_seen_detail_count(tenant, start, end):
    """Quantas linhas o relatório teria, sem montar nenhuma.

    É o que decide se a exportação cabe na requisição ou vai para o worker
    (`reporting/services.py`), e por isso não pode ser "conta montando":
    um `COUNT(DISTINCT)` no banco custa o mesmo para dez ou dez mil
    pacientes.
    """
    start, end = _period_bounds(start, end)
    return (
        Encounter.objects
        .filter(tenant_id=tenant, status=EncounterStatus.FINALIZED,
                occurred_at__date__gte=start, occurred_at__date__lte=end)
        .values('patient_id').distinct().count()
    )


def patients_seen_detail_rows(tenant, start, end):
    """Row-level export backing the "Pacientes atendidos" indicator --
    one row per distinct patient with their earliest finalized encounter
    in the window. `start`/`end` arrive as ISO date strings when this runs
    through the export registry (Celery task params are plain JSON).
    """
    start, end = _period_bounds(start, end)
    encounters = Encounter.objects.filter(
        tenant_id=tenant, status=EncounterStatus.FINALIZED, occurred_at__date__gte=start, occurred_at__date__lte=end,
    ).select_related('patient').values('patient_id', 'patient__full_name').annotate(
        first_at=Min('occurred_at'),
    ).order_by('patient__full_name')
    return [
        {'patient_id': str(row['patient_id']), 'full_name': row['patient__full_name'], 'first_encounter_at': row['first_at'].isoformat()}
        for row in encounters
    ]


def followup_duration_years(tenant, patient_id):
    """Última menos primeira consulta finalizada, em dias/365,25. Paciente
    com uma única consulta tem duração observada ZERO -- nunca é
    apresentado como "perda de seguimento confirmada".
    """
    encounters = Encounter.objects.filter(
        tenant=tenant, patient_id=patient_id, status=EncounterStatus.FINALIZED,
    ).order_by('occurred_at')
    if not encounters.exists():
        return None
    first_at = encounters.first().occurred_at
    last_at = encounters.last().occurred_at
    return (last_at - first_at).days / 365.25
