from django.db import models

from base.models import TenantModel


class CRMStage(TenantModel):
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField()
    active = models.BooleanField(default=True)
    color_token = models.CharField(max_length=60, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'name'], name='crm_stage_tenant_name_uniq'),
        ]
        ordering = ['order']

    def __str__(self):
        return self.name


class CRMCard(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='crm_cards')
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.PROTECT, null=True, blank=True, related_name='crm_cards',
    )
    stage = models.ForeignKey(CRMStage, on_delete=models.PROTECT, related_name='cards')
    assigned_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    due_at = models.DateTimeField(null=True, blank=True)
    administrative_summary = models.CharField(max_length=500, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'patient'], name='crm_card_patient_idx'),
        ]

    def __str__(self):
        return f'{self.patient_id} — {self.stage.name}'


class CRMTransition(TenantModel):
    card = models.ForeignKey(CRMCard, on_delete=models.PROTECT, related_name='transitions')
    from_stage = models.ForeignKey(CRMStage, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    to_stage = models.ForeignKey(CRMStage, on_delete=models.PROTECT, related_name='+')
    actor = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    reason = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f'{self.card_id}: {self.from_stage_id} -> {self.to_stage_id}'
