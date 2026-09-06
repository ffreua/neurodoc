from django import forms

from .models import AppointmentType, AvailabilityRule


class AvailabilityRuleForm(forms.ModelForm):
    class Meta:
        model = AvailabilityRule
        fields = [
            'physician_membership', 'weekday', 'local_start', 'local_end',
            'starts_on', 'ends_on', 'slot_minutes', 'buffer_minutes', 'appointment_type',
        ]
        widgets = {
            'local_start': forms.TimeInput(attrs={'type': 'time'}),
            'local_end': forms.TimeInput(attrs={'type': 'time'}),
            'starts_on': forms.DateInput(attrs={'type': 'date'}),
            'ends_on': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        from tenancy.models import Membership, MembershipStatus, Role

        queryset = Membership.objects.none()
        if tenant_id is not None:
            queryset = Membership.objects.filter(
                tenant_id=tenant_id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
            ).select_related('user')
        self.fields['physician_membership'].queryset = queryset
        self.fields['physician_membership'].label_from_instance = (
            lambda membership: membership.user.get_full_name() or membership.user.email
        )


def _doctor_queryset(tenant_id):
    from tenancy.models import Membership, MembershipStatus, Role

    if tenant_id is None:
        return Membership.objects.none()
    return Membership.objects.filter(
        tenant_id=tenant_id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).select_related('user')


def _doctor_label(membership):
    return membership.user.get_full_name() or membership.user.email


class ReserveAppointmentForm(forms.Form):
    patient_id = forms.UUIDField(widget=forms.HiddenInput)
    physician_membership = forms.ModelChoiceField(queryset=None, label='Médico')
    starts_at = forms.DateTimeField(label='Início', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    ends_at = forms.DateTimeField(label='Fim', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    type = forms.ChoiceField(label='Tipo', choices=AppointmentType.choices)
    is_overbook = forms.BooleanField(label='Encaixe (overbook)', required=False)
    override_reason = forms.CharField(label='Justificativa do encaixe', max_length=255, required=False)

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['physician_membership'].queryset = _doctor_queryset(tenant_id)
        self.fields['physician_membership'].label_from_instance = _doctor_label

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('is_overbook') and not cleaned.get('override_reason'):
            raise forms.ValidationError('Encaixe exige justificativa.')
        return cleaned


class RescheduleAppointmentForm(forms.Form):
    starts_at = forms.DateTimeField(label='Novo início', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    ends_at = forms.DateTimeField(label='Novo fim', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    row_version = forms.IntegerField(widget=forms.HiddenInput)
