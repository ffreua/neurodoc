"""Agendas de exame por recurso: EEG, ENMG, polissonografia (Sprint 4 do TISS).

## Por que entidades novas, e não `Appointment`

A agenda médica é por **médico** (`Appointment.physician_membership`,
obrigatório) e por **dia**: a exclusão de sobreposição, a grade, a semana,
o mês, as estatísticas, os lembretes e a cobrança do check-in leem esse
campo — são cerca de duzentos pontos em oito apps. Um exame é de um
**equipamento**: o EEG da sala 2 não é um médico, e a polissonografia
começa às 21h e acaba às 7h do dia seguinte. Fazer `Appointment` aceitar
recurso seria tornar o médico opcional em todos esses pontos, ou inventar
um médico fictício — que consumiria vaga do plano e apareceria na agenda
dele. A decisão (Sprint 1, `docs/tiss/REVISAO_SPRINT1.md`) foi o contrário:
entidades aditivas, com a mesma garantia do banco que a agenda médica tem.

## O que é igual à agenda médica, e o que não é

- **Igual:** sobreposição recusada pelo banco (`ExclusionConstraint` no
  intervalo ocupado, por recurso), o paciente da mesma clínica pela chave
  composta, a forma de cobrança escolhida por reserva.
- **Diferente:** o intervalo é um instante de início e um de fim, sem dia
  embutido — a reserva das 21h às 7h é **uma** linha, e aparece nos dois
  dias da tela. A janela semanal pode atravessar a meia-noite (fim antes do
  início). Não há teto de 480 minutos: o teto é 24 horas.
- **O executante não bloqueia a agenda médica.** Quem acompanha a
  polissonografia é técnico; o laudo é do médico, depois. Reservar o
  médico por uma noite inteira por suposição tiraria consultas dele que
  ninguém pediu para tirar. O executante é registrado na realização, e é
  ele que vai na guia.
"""

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel

#: O teto de uma reserva. A polissonografia mais longa (titulação + basal)
#: cabe em 12 h; 24 h deixa folga sem permitir uma reserva de semanas.
DURACAO_MAXIMA_MINUTOS = 24 * 60


class TipoRecurso(models.TextChoices):
    EEG = 'eeg', 'Eletroencefalograma (EEG)'
    ENMG = 'enmg', 'Eletroneuromiografia (ENMG)'
    PSG = 'psg', 'Polissonografia (PSG)'
    OUTRO = 'outro', 'Outro exame'


class Recurso(TenantModel):
    """Uma agenda de exame: um equipamento, uma sala, uma capacidade."""

    nome = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=TipoRecurso.choices, default=TipoRecurso.OUTRO)
    duracao_padrao = models.PositiveSmallIntegerField('duração padrão (minutos)', default=60)
    intervalo = models.PositiveSmallIntegerField('intervalo depois de cada exame (minutos)', default=0)
    #: O procedimento que a reserva sugere e que a guia leva. Texto: a
    #: release TUSS troca; o código fica.
    codigo_tuss = models.CharField('código TUSS padrão', max_length=10, blank=True)
    descricao_tuss = models.CharField('descrição do procedimento', max_length=150, blank=True)
    #: Quem costuma executar — sugestão para a realização, nunca obrigação.
    executante_padrao = models.ForeignKey(
        'tiss.ProfissionalTiss', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    ativo = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        verbose_name = 'agenda de exame'
        verbose_name_plural = 'agendas de exame'
        constraints = TenantModel.Meta.constraints + [
            models.CheckConstraint(
                condition=models.Q(duracao_padrao__gte=5, duracao_padrao__lte=DURACAO_MAXIMA_MINUTOS),
                name='agenda_exames_recurso_duracao',
            ),
        ]

    def __str__(self):
        return self.nome


class Janela(TenantModel):
    """Horário semanal em que o recurso atende.

    `fim <= inicio` é **atravessar a meia-noite**: segunda, 20h às 7h, é da
    segunda 20h até a terça 7h. O dia da semana é o do início.
    """

    recurso = models.ForeignKey(Recurso, on_delete=models.CASCADE, related_name='janelas')
    dia_semana = models.PositiveSmallIntegerField(choices=[
        (0, 'Segunda'), (1, 'Terça'), (2, 'Quarta'), (3, 'Quinta'), (4, 'Sexta'), (5, 'Sábado'), (6, 'Domingo'),
    ])
    inicio = models.TimeField()
    fim = models.TimeField()
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_ate = models.DateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ['dia_semana', 'inicio']

    def clean(self):
        if self.inicio == self.fim:
            raise ValidationError({'fim': 'O fim tem de ser diferente do início.'})
        if self.vigente_desde and self.vigente_ate and self.vigente_ate < self.vigente_desde:
            raise ValidationError({'vigente_ate': 'O fim da vigência não pode ser antes do início.'})

    @property
    def atravessa_meia_noite(self):
        return self.fim <= self.inicio


class Bloqueio(TenantModel):
    """Equipamento em manutenção, sala ocupada, feriado — instante a instante."""

    recurso = models.ForeignKey(Recurso, on_delete=models.CASCADE, related_name='bloqueios')
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    motivo = models.CharField(max_length=255)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.CheckConstraint(condition=models.Q(fim__gt=models.F('inicio')), name='agenda_exames_bloqueio_ordem'),
        ]


class EstadoReserva(models.TextChoices):
    AGENDADA = 'agendada', 'Agendado'
    CONFIRMADA = 'confirmada', 'Confirmado'
    CHEGOU = 'chegou', 'Paciente chegou'
    REALIZADA = 'realizada', 'Realizado'
    FALTOU = 'faltou', 'Faltou'
    CANCELADA = 'cancelada', 'Cancelado'


#: Estados que ocupam o recurso. Falta e cancelamento liberam o horário.
OCUPAM = [EstadoReserva.AGENDADA, EstadoReserva.CONFIRMADA, EstadoReserva.CHEGOU, EstadoReserva.REALIZADA]

TRANSICOES = {
    EstadoReserva.AGENDADA: {EstadoReserva.CONFIRMADA, EstadoReserva.CHEGOU, EstadoReserva.REALIZADA,
                             EstadoReserva.FALTOU, EstadoReserva.CANCELADA},
    EstadoReserva.CONFIRMADA: {EstadoReserva.CHEGOU, EstadoReserva.REALIZADA, EstadoReserva.FALTOU,
                               EstadoReserva.CANCELADA},
    EstadoReserva.CHEGOU: {EstadoReserva.REALIZADA, EstadoReserva.CANCELADA},
    EstadoReserva.REALIZADA: set(),
    EstadoReserva.FALTOU: set(),
    EstadoReserva.CANCELADA: set(),
}


class Cobranca(models.TextChoices):
    """A forma de cobrança da reserva — igual à do agendamento médico."""

    PARTICULAR = 'particular', 'Particular'
    CONVENIO = 'convenio', 'Convênio'


class Reserva(TenantModel):
    """Um exame marcado num recurso.

    **Realizar é o que prova o exame**: marcar, confirmar e chegar não
    viram cobrança nem guia. Na realização, o executante é registrado e a
    cobrança nasce (`agenda_exames.services.realizar`) — uma por reserva,
    pelo banco (`finance_receivable_reserva_uniq`).
    """

    recurso = models.ForeignKey(Recurso, on_delete=models.PROTECT, related_name='reservas')
    paciente = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='+')
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    #: `[inicio, fim + intervalo)` — o que o recurso fica indisponível.
    ocupacao = DateTimeRangeField()
    estado = models.CharField(max_length=12, choices=EstadoReserva.choices, default=EstadoReserva.AGENDADA)
    codigo_tuss = models.CharField('código TUSS', max_length=10, blank=True)
    descricao = models.CharField('procedimento', max_length=150, blank=True)
    cobranca = models.CharField('forma de cobrança', max_length=12, choices=Cobranca.choices, blank=True)
    cobertura = models.ForeignKey(
        'patients.PatientCoverage', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    solicitante = models.ForeignKey(
        'tiss.ProfissionalTiss', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name='quem pediu o exame',
    )
    executante = models.ForeignKey(
        'tiss.ProfissionalTiss', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name='quem executou',
    )
    observacao = models.CharField('observação para a recepção', max_length=500, blank=True)
    encaixe = models.BooleanField(default=False)
    motivo_encaixe = models.CharField(max_length=255, blank=True)
    motivo_cancelamento = models.CharField(max_length=255, blank=True)
    realizada_em = models.DateTimeField(null=True, blank=True)
    #: Sobe a cada remarcação: o lembrete de uma versão velha não sai.
    versao_lembrete = models.PositiveIntegerField(default=1)
    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        verbose_name = 'exame agendado'
        verbose_name_plural = 'exames agendados'
        constraints = TenantModel.Meta.constraints + [
            models.CheckConstraint(condition=models.Q(fim__gt=models.F('inicio')), name='agenda_exames_reserva_ordem'),
            ExclusionConstraint(
                name='agenda_exames_reserva_sem_sobreposicao',
                expressions=[('recurso', RangeOperators.EQUAL), ('ocupacao', RangeOperators.OVERLAPS)],
                condition=models.Q(estado__in=[str(e) for e in OCUPAM]),
            ),
        ]
        indexes = [models.Index(fields=['tenant', 'recurso', 'inicio'], name='agenda_exames_reserva_idx')]

    def __str__(self):
        return f'{self.recurso} — {self.inicio:%d/%m %H:%M}'

    @property
    def ativa(self):
        return self.estado in OCUPAM and self.estado != EstadoReserva.REALIZADA
