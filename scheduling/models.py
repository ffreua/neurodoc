from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel


class AppointmentType(models.TextChoices):
    FIRST_VISIT = 'first_visit', 'Primeira consulta'
    FOLLOW_UP = 'follow_up', 'Retorno'
    PROCEDURE = 'procedure', 'Procedimento'
    OTHER = 'other', 'Outro'


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
    BLOCK = 'block', 'Block'
    VACATION = 'vacation', 'Vacation'
    EXTRA_AVAILABILITY = 'extra_availability', 'Extra availability'


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
