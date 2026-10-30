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
            raise ValidationError({'weekday': 'Informe um dia da semana entre 0 (segunda) e 6 (domingo).'})
        if self.local_start >= self.local_end:
            raise ValidationError({'local_end': 'O horário de término deve ser depois do de início.'})
        if self.slot_minutes <= 0:
            raise ValidationError({'slot_minutes': 'Informe um valor maior que zero.'})
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({'ends_on': 'A data de término não pode ser anterior à de início.'})

    def __str__(self):
        return f'{self.physician_membership_id} weekday={self.weekday} {self.local_start}-{self.local_end}'


class RecurringBreak(TenantModel):
    """Pausa que se repete toda semana, dentro da janela de atendimento.

    O intervalo que já existia — `AvailabilityRule.buffer_minutes` — é de
    outra natureza: ele reserva alguns minutos **depois de cada**
    atendimento, e serve para a consulta que estourou o horário não
    empurrar a seguinte. Não serve para o almoço.

    Isto aqui é a pausa de relógio: "segunda das 11h40 às 12h", "terça
    das 12h20 às 13h". O médico atende três pacientes seguidos e para
    vinte minutos — e esse intervalo cai em horário diferente a cada dia
    da semana, porque a grade de cada dia é diferente.

    **Modelo próprio, e não um campo na regra.** Três razões, e a
    terceira é a que decide:

    1. pode haver mais de uma pausa no mesmo dia (café e almoço), e campo
       não se repete;
    2. a pausa não tem célula nem tipo de atendimento — metade de
       `AvailabilityRule` não se aplicaria a ela;
    3. uma pausa pode atravessar duas regras do mesmo dia (manhã e
       tarde declaradas separadamente), e pendurada numa delas valeria
       só para metade da grade.

    **Não é `ScheduleBlock`**, que é bloqueio de **data** — férias, um
    congresso, um feriado. Aquele tem `start_at`/`end_at` com data; este
    tem dia da semana e vigência, como a regra que ele recorta. Misturar
    os dois obrigaria a criar 52 bloqueios por ano para um almoço.

    A vigência (`starts_on`/`ends_on`) acompanha a da regra pelo mesmo
    motivo dela: encurtar em vez de apagar preserva a agenda passada, e a
    grade de um dia já atendido continua sendo reconstruível como era.
    """

    physician_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='recurring_breaks',
    )
    weekday = models.PositiveSmallIntegerField()  # 0=segunda .. 6=domingo
    local_start = models.TimeField()
    local_end = models.TimeField()
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    #: "Almoço", "Café", "Reunião de equipe". Aparece na célula bloqueada
    #: da grade: buraco sem motivo na agenda faz a secretária ligar para
    #: perguntar se pode encaixar.
    reason = models.CharField(max_length=80, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints
        indexes = [
            models.Index(
                fields=['physician_membership', 'weekday'],
                name='sched_pausa_medico_dia_idx',
            ),
        ]
        ordering = ['weekday', 'local_start']

    def clean(self):
        if not (0 <= self.weekday <= 6):
            raise ValidationError({'weekday': 'Informe um dia da semana entre 0 (segunda) e 6 (domingo).'})
        if self.local_start >= self.local_end:
            raise ValidationError({'local_end': 'O fim do intervalo deve ser depois do início.'})
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({'ends_on': 'A data de término não pode ser anterior à de início.'})

    @property
    def label(self):
        inicio = self.local_start.strftime('%H:%M')
        fim = self.local_end.strftime('%H:%M')
        return f'{inicio}–{fim}' + (f' ({self.reason})' if self.reason else '')

    def __str__(self):
        return f'pausa {self.weekday} {self.label}'


class ScheduleBlockKind(models.TextChoices):
    BLOCK = 'block', 'Bloqueio'
    VACATION = 'vacation', 'Férias'
    HOLIDAY = 'holiday', 'Feriado'
    EXTRA_AVAILABILITY = 'extra_availability', 'Atendimento extra'
    # O horário tirado da agenda pelo modal de marcar. Fecha como o
    # bloqueio, mas a grade **não o desenha**: quem exclui um horário quer
    # que ele suma, e não uma célula "fechada" no lugar -- no mês, um dia
    # só com células assim aparecia como "fechado". E "Incluir horário" no
    # mesmo lugar o reabre (`services.include_extra_hours`), em vez de
    # recusar como "já é horário de atendimento".
    REMOVED_SLOT = 'removed_slot', 'Horário excluído'


#: O motivo que o botão "Bloquear este horário" grava. É o que a grade
#: mostra na célula, e o que `services.unblock_slot` exige para desfazer:
#: um bloqueio digitado em Configurar horários (férias de uma tarde, uma
#: cirurgia) não se desfaz por um clique na agenda.
MOTIVO_BLOQUEIO_PELA_AGENDA = 'Horário bloqueado pela agenda'


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
            raise ValidationError({'end_at': 'O fim do bloqueio deve ser depois do início.'})

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


class BillingMode(models.TextChoices):
    """Os mesmos valores de `finance.PaymentCategory`, de propósito.

    `patients.PaymentCategory` diz `plan` onde o financeiro diz `insurance`;
    nenhum dos dois é renomeado (há snapshot e relatório lendo a string).
    O agendamento fala a língua do financeiro, que é quem a consome.
    """

    PRIVATE = 'private', 'Particular'
    INSURANCE = 'insurance', 'Convênio'


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
    #: Como **este** atendimento é cobrado (1.30). Vazio é "não informado",
    #: que é o estado de todo agendamento anterior — e nele a cobrança segue
    #: a regra antiga (`finance.receivables._price_for`). A ficha do
    #: paciente sugere; o agendamento decide: o mesmo paciente pode vir por
    #: convênio num dia e particular no outro, e a cobertura vigente na
    #: ficha não pode transformar a consulta particular em cobrança de
    #: convênio. Ver `docs/tiss/REVISAO_SPRINT1.md` §4.2.
    billing_mode = models.CharField(
        'forma de cobrança', max_length=12, choices=BillingMode.choices, blank=True, default='',
    )
    #: A cobertura usada, quando é convênio. PROTECT: cobertura não se apaga
    #: no NeuroDoc, e a guia futura precisa dela.
    coverage = models.ForeignKey(
        'patients.PatientCoverage', on_delete=models.PROTECT, null=True, blank=True,
        related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.CheckConstraint(
                condition=(
                    models.Q(billing_mode='insurance', coverage__isnull=False)
                    | (~models.Q(billing_mode='insurance') & models.Q(coverage__isnull=True))
                ),
                name='scheduling_appointment_billing_coverage',
            ),
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
            raise ValidationError({'ends_at': 'O fim do atendimento deve ser depois do início.'})
        if self.billing_mode == BillingMode.INSURANCE:
            if self.coverage_id is None:
                raise ValidationError({'coverage': 'Escolha o convênio do paciente.'})
            if self.coverage.patient_id != self.patient_id:
                raise ValidationError({'coverage': 'Este convênio é de outro paciente.'})
        elif self.coverage_id is not None:
            raise ValidationError({'coverage': 'Convênio só se informa quando a cobrança é por convênio.'})

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


class ReturnStatus(models.TextChoices):
    """Onde está cada retorno previsto.

    Quatro estados, e o terceiro é o que evita a lista virar lixo: um
    retorno que já virou consulta sai da fila sozinho. Sem isso a
    secretária reencontra todo dia os mesmos nomes que ela já resolveu.
    """

    PENDING = 'pending', 'A agendar'
    SCHEDULED = 'scheduled', 'Agendado'
    DONE = 'done', 'Concluído'
    DISMISSED = 'dismissed', 'Dispensado'


class ScheduledReturn(TenantModel):
    """O retorno que o médico previu ao fechar o atendimento.

    Até aqui essa informação só existia na cabeça de quem atendeu. O médico
    pensava "volta em seis meses", fechava o prontuário, e ninguém mais
    sabia — o paciente com epilepsia estável sumia por dois anos até ter
    uma crise. Numa especialidade feita de doença crônica com seguimento
    longo, isso não é comodidade perdida: é paciente perdido.

    **É registro clínico com consequência administrativa**, e por isso mora
    aqui e não em `clinical`: quem decide é o médico, quem trabalha é a
    secretária, e o trabalho dela é agenda.

    O que **não** é: consulta marcada. Um retorno previsto é uma intenção
    com data — a consulta nasce quando alguém a agenda, e é o `appointment`
    abaixo que liga as duas.
    """

    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, related_name='scheduled_returns',
    )
    #: De quem é o paciente. O retorno é com **este** médico: em clínica de
    #: dois ou mais, devolver o paciente para a agenda de outro quebra o
    #: seguimento, que é justamente o que este registro existe para manter.
    physician_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='scheduled_returns',
    )
    #: Onde a decisão foi tomada. `SET_NULL` e não `PROTECT`: o atendimento
    #: é imutável e não se apaga, mas se um dia for anonimizado o retorno
    #: previsto continua valendo — ele é sobre o futuro, não sobre o
    #: registro de origem.
    origin_encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scheduled_returns',
    )
    #: O que o médico escolheu, em meses. Guardado além da data porque
    #: "seis meses" e "31/03" dizem coisas diferentes na tela: o primeiro é
    #: a conduta, o segundo é a consequência dela.
    interval_months = models.PositiveSmallIntegerField()
    due_on = models.DateField()
    status = models.CharField(
        max_length=20, choices=ReturnStatus.choices, default=ReturnStatus.PENDING,
    )
    #: Preenchido quando a consulta nasce. É o que tira a linha da fila.
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fulfils_returns',
    )
    #: Quando o aviso saiu para o paciente. Existe para o aviso **não sair
    #: duas vezes**: a tarefa roda todo dia, e sem esta marca ela mandaria
    #: um e-mail por dia durante os vinte dias que antecedem o retorno.
    notified_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True,
        related_name='+',
    )
    #: Por que foi dispensado, ou o que a secretária apurou ao ligar. A
    #: lista sem isto devolve o mesmo nome amanhã, e quem ligou ontem não
    #: tem como dizer "já tentei, não atende".
    note = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            # A consulta da tarefa diária e a da tela da secretária são a
            # mesma: pendentes por data. Sem índice, ela varre a tabela
            # inteira todo dia às seis da manhã.
            models.Index(fields=['tenant', 'status', 'due_on'], name='scheduling_return_fila_idx'),
        ]
        ordering = ['due_on', 'id']

    @property
    def is_overdue(self):
        """Passou da data e ninguém agendou."""
        from django.utils import timezone as _tz

        return self.status == ReturnStatus.PENDING and self.due_on < _tz.localdate()

    def __str__(self):
        return f'retorno de {self.patient_id} em {self.due_on}'
