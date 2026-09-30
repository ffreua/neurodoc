from django.db import models

from base.models import TenantModel
from scheduling.models import AppointmentType


class PaymentCategory(models.TextChoices):
    PRIVATE = 'private', 'Particular'
    INSURANCE = 'insurance', 'Plano'


class ChargeKind(models.TextChoices):
    CONSULTATION = 'consultation', 'Consulta'
    PROCEDURE = 'procedure', 'Procedimento'


class ReceivableStatus(models.TextChoices):
    PENDING = 'pending', 'Em aberto'
    PARTIAL = 'partial', 'Parcial'
    PAID = 'paid', 'Pago'
    CANCELLED = 'cancelled', 'Cancelado'


class AdjustmentType(models.TextChoices):
    DISCOUNT = 'discount', 'Desconto'
    SURCHARGE = 'surcharge', 'Acréscimo'
    REFUND = 'refund', 'Estorno'
    WRITEOFF = 'writeoff', 'Baixa'


class FeeSchedule(TenantModel):
    physician = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='fee_schedules',
    )
    plan = models.ForeignKey('patients.HealthPlan', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    procedure = models.ForeignKey(
        'catalogs.ProcedureCode', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    #: Primeira consulta, seguimento, retorno -- o que a agenda ja
    #: distingue, e que ate aqui nao tinha como custar diferente.
    #:
    #: A clinica cobra tres valores por aquilo que, para a TUSS, e um
    #: codigo so: "consulta em consultorio". A distincao e comercial, nao
    #: da ANS, entao amarra-la a `procedure` seria inventar codigo de
    #: tabela nacional para uso interno -- o mesmo codigo sairia numa guia
    #: de convenio e voltaria glosado.
    #:
    #: Nulo e "vale para qualquer tipo", como os tres campos acima, e e o
    #: que toda regra ja existente continua sendo. Atendimento sem
    #: agendamento (encaixe, paciente que chega sem marcar) tambem chega
    #: aqui com nulo e cai na regra geral, que e o comportamento de antes.
    appointment_type = models.CharField(
        max_length=40, choices=AppointmentType.choices, null=True, blank=True,
    )
    payment_category = models.CharField(max_length=20, choices=PaymentCategory.choices)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    doctor_share_amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(
                fields=['tenant', 'physician', 'plan', 'procedure', 'appointment_type'],
                name='finance_fee_lookup_idx',
            ),
        ]

    def __str__(self):
        return f'{self.payment_category} {self.gross_amount} ({self.effective_from})'


class Receivable(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='receivables')
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.PROTECT, null=True, blank=True,
        related_name='receivables',
    )
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.PROTECT, null=True, blank=True,
        related_name='receivables',
    )
    charge_kind = models.CharField(max_length=20, choices=ChargeKind.choices, default=ChargeKind.CONSULTATION)
    fee_snapshot = models.JSONField(default=dict)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    charged_amount = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField()
    competence_date = models.DateField()
    status = models.CharField(max_length=20, choices=ReceivableStatus.choices, default=ReceivableStatus.PENDING)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    fiscal_document_number = models.CharField(max_length=100, blank=True)
    doctor_share_paid_at = models.DateTimeField(null=True, blank=True)
    doctor_share_paid_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    doctor_share_paid_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True,
        related_name='+',
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True,
        related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.CheckConstraint(
                condition=models.Q(encounter__isnull=False) | models.Q(appointment__isnull=False),
                name='finance_receivable_has_origin',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'encounter', 'charge_kind'],
                condition=models.Q(encounter__isnull=False),
                name='finance_receivable_encounter_uniq',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'appointment', 'charge_kind'],
                condition=models.Q(appointment__isnull=False),
                name='finance_receivable_appointment_uniq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['tenant', 'archived_at', 'doctor_share_paid_at', 'competence_date'],
                name='fin_recv_visible_comp_idx',
            ),
        ]

    def __str__(self):
        origin = self.encounter_id or self.appointment_id
        return f'{origin}:{self.charge_kind} ({self.status})'


class Payment(TenantModel):
    receivable = models.ForeignKey(Receivable, on_delete=models.PROTECT, related_name='payments')
    paid_at = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=40)
    external_reference = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f'{self.receivable_id}: {self.amount}'


class FinancialAdjustment(TenantModel):
    receivable = models.ForeignKey(Receivable, on_delete=models.PROTECT, related_name='adjustments')
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, null=True, blank=True, related_name='adjustments')
    type = models.CharField(max_length=20, choices=AdjustmentType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    approved_by = models.ForeignKey('tenancy.Membership', on_delete=models.PROTECT, related_name='+')

    def __str__(self):
        return f'{self.type} {self.amount} on {self.receivable_id}'
