from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel


class AppointmentType(models.TextChoices):
    """Tipos de atendimento, que é o que determina a duração.

    `follow_up` passou a se chamar "Seguimento" e `return_visit` entrou como
    "Retorno": são coisas diferentes na prática e têm durações diferentes —
    o seguimento é uma consulta completa de um caso em acompanhamento; o
    retorno é a volta curta para mostrar exames. Enquanto os dois se
    chamavam "Retorno" não havia como declarar duas durações.
    """

    FIRST_VISIT = 'first_visit', 'Primeira consulta'
    FOLLOW_UP = 'follow_up', 'Seguimento'
    RETURN_VISIT = 'return_visit', 'Retorno'
    PROCEDURE = 'procedure', 'Procedimento'
    OTHER = 'other', 'Outro'


#: Duração padrão de cada tipo, em minutos, quando o médico não configurou a
#: dele. São os valores que a maioria usa; cada médico ajusta os seus em
#: `AppointmentTypeDuration`.
DEFAULT_TYPE_MINUTES = {
    AppointmentType.FIRST_VISIT: 80,
    AppointmentType.FOLLOW_UP: 80,
    AppointmentType.RETURN_VISIT: 40,
    AppointmentType.PROCEDURE: 40,
    AppointmentType.OTHER: 40,
}


class AppointmentTypeDuration(TenantModel):
    """Duração de um tipo de atendimento para um médico (RF-06.02).

    Fica por médico porque é decisão dele: 80 minutos de primeira consulta
    num consultório de neurologia e 30 em outra especialidade são ambos
    corretos.

    A grade da agenda usa o **maior divisor comum** das durações do médico
    como célula base — é o que permite mostrar um calendário em que uma
    primeira consulta de 80 minutos ocupa duas células de 40 e um retorno
    ocupa uma. Sem isso não existe grade visual: cada tipo pediria uma régua
    de horários diferente.
    """

    physician_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.CASCADE, related_name='appointment_durations',
    )
    appointment_type = models.CharField(max_length=40, choices=AppointmentType.choices)
    minutes = models.PositiveSmallIntegerField()

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'physician_membership', 'appointment_type'],
                name='scheduling_typeduration_uniq',
            ),
        ]
        ordering = ['appointment_type']

    def clean(self):
        if self.minutes is not None and not (5 <= self.minutes <= 480):
            raise ValidationError({'minutes': 'A duração deve ficar entre 5 e 480 minutos.'})

    def __str__(self):
        return f'{self.get_appointment_type_display()}: {self.minutes} min'


class AvailabilityRule(TenantModel):
    physician_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='availability_rules',
    )
    weekday = models.PositiveSmallIntegerField()  # 0=Monday .. 6=Sunday (date.weekday())
    local_start = models.TimeField()
    local_end = models.TimeField()
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    slot_minutes = models.PositiveSmallIntegerField()
    buffer_minutes = models.PositiveSmallIntegerField(default=0)
    appointment_type = models.CharField(max_length=40, choices=AppointmentType.choices, default=AppointmentType.OTHER)

    def clean(self):
        if not (0 <= self.weekday <= 6):
            raise ValidationError({'weekday': 'Must be between 0 (Monday) and 6 (Sunday)'})
        if self.local_start >= self.local_end:
            raise ValidationError({'local_end': 'Must be after local_start'})
        if self.slot_minutes <= 0:
            raise ValidationError({'slot_minutes': 'Must be positive'})
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({'ends_on': 'Cannot precede starts_on'})

    def __str__(self):
        return f'{self.physician_membership_id} weekday={self.weekday} {self.local_start}-{self.local_end}'


class ScheduleBlockKind(models.TextChoices):
    BLOCK = 'block', 'Bloqueio'
    VACATION = 'vacation', 'Férias'
    HOLIDAY = 'holiday', 'Feriado'
    EXTRA_AVAILABILITY = 'extra_availability', 'Atendimento extra'


class ScheduleBlock(TenantModel):
    physician_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='schedule_blocks',
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    kind = models.CharField(max_length=40, choices=ScheduleBlockKind.choices)
    reason = models.CharField(max_length=255, blank=True)
    override_rule = models.BooleanField(default=True)

    def clean(self):
        if self.start_at >= self.end_at:
            raise ValidationError({'end_at': 'Must be after start_at'})

    def __str__(self):
        return f'{self.kind} {self.start_at}—{self.end_at}'


class AppointmentStatus(models.TextChoices):
    SCHEDULED = 'scheduled', 'Agendado'
    CONFIRMED = 'confirmed', 'Confirmado'
    CHECKED_IN = 'checked_in', 'Check-in feito'
    IN_PROGRESS = 'in_progress', 'Em atendimento'
    COMPLETED = 'completed', 'Concluído'
    CANCELLED = 'cancelled', 'Cancelado'
    NO_SHOW = 'no_show', 'Falta'


OCCUPYING_STATUSES = [
    AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED,
    AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_PROGRESS,
]

ALLOWED_TRANSITIONS = {
    AppointmentStatus.SCHEDULED: {
        AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED,
        AppointmentStatus.CHECKED_IN, AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.CONFIRMED: {
        AppointmentStatus.CANCELLED, AppointmentStatus.CHECKED_IN, AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.CHECKED_IN: {AppointmentStatus.IN_PROGRESS},
    AppointmentStatus.IN_PROGRESS: {AppointmentStatus.COMPLETED},
    AppointmentStatus.COMPLETED: set(),
    AppointmentStatus.CANCELLED: set(),
    AppointmentStatus.NO_SHOW: set(),
}


class Appointment(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='appointments')
    physician_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='appointments',
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    occupied_range = DateTimeRangeField()
    status = models.CharField(max_length=40, choices=AppointmentStatus.choices, default=AppointmentStatus.SCHEDULED)
    type = models.CharField(max_length=40, choices=AppointmentType.choices, default=AppointmentType.OTHER)
    is_overbook = models.BooleanField(default=False)
    override_reason = models.CharField(max_length=255, blank=True)
    override_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            ExclusionConstraint(
                name='scheduling_appointment_no_overlap',
                expressions=[
                    ('physician_membership', RangeOperators.EQUAL),
                    ('occupied_range', RangeOperators.OVERLAPS),
                ],
                condition=models.Q(status__in=list(OCCUPYING_STATUSES), is_overbook=False),
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'physician_membership', 'starts_at'], name='sched_appt_physician_idx'),
            models.Index(fields=['tenant', 'status', 'starts_at'], name='sched_appt_status_idx'),
        ]

    def clean(self):
        if self.starts_at >= self.ends_at:
            raise ValidationError({'ends_at': 'Must be after starts_at'})

    def __str__(self):
        return f'{self.patient_id} @ {self.starts_at}'


class HolidayScope(models.TextChoices):
    NATIONAL = 'national', 'Nacional'
    STATE = 'state', 'Estadual'
    MUNICIPAL = 'municipal', 'Municipal'


class Holiday(TenantModel):
    """Um feriado numa data, para a agenda poder oferecer o bloqueio.

    Os feriados nacionais são **calculados**, não baixados: os fixos são
    fixos, e os móveis (Carnaval, Sexta-feira Santa, Corpus Christi) derivam
    da Páscoa por aritmética. Isso vale para qualquer ano, funciona sem rede
    e não depende de um serviço externo continuar existindo.

    Estadual e municipal não são calculáveis — variam por lei local. Esses
    são cadastrados pela organização, e por isso existe `recurring`: a
    maioria tem data fixa, então cadastrar uma vez cobre todos os anos.

    O feriado **não bloqueia sozinho**. Ele entra numa tela de revisão em que
    o médico marca o que quer bloquear, porque atender em feriado é decisão
    dele — plantão, mutirão, reposição de agenda.
    """

    date = models.DateField()
    name = models.CharField(max_length=120)
    scope = models.CharField(max_length=20, choices=HolidayScope.choices, default=HolidayScope.NATIONAL)
    state = models.CharField(max_length=2, blank=True)
    city = models.CharField(max_length=120, blank=True)
    #: Repete na mesma data todos os anos. Falso para os móveis (Carnaval).
    recurring = models.BooleanField(default=True)
    #: 'computed' para nacional calculado, 'manual' para o que a clínica
    #: cadastrou. Serve para o recálculo saber o que pode substituir.
    source = models.CharField(max_length=20, default='computed')
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'date', 'name'], name='scheduling_holiday_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'date'], name='scheduling_holiday_date_idx'),
        ]
        ordering = ['date']

    def applies_to(self, state='', city=''):
        """Se este feriado vale para o lugar onde o médico atende.

        Nacional vale sempre. Estadual só na UF. Municipal só no município —
        e comparado sem acento e sem caixa, porque "São Paulo" e "SAO PAULO"
        são o mesmo lugar.
        """
        if self.scope == HolidayScope.NATIONAL:
            return True
        if self.scope == HolidayScope.STATE:
            return bool(state) and self.state.upper() == state.upper()
        return bool(city) and _fold(self.city) == _fold(city)

    def __str__(self):
        return f'{self.date} — {self.name}'


def _fold(text):
    """Texto sem acento e em maiúsculas, para comparar nome de município."""
    import unicodedata

    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).upper().strip()
