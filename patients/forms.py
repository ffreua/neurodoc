import re

from django import forms

from base.validators import validate_cpf

from .models import (
    MaritalStatus, Patient, PatientContact, PaymentCategory, ReferralSource, SexAtRegistration,
)


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            'full_name', 'birth_date', 'birth_date_unknown_reason', 'estimated_birth_year',
            'sex_at_registration', 'cpf', 'identity_number', 'mother_name',
            'postal_code', 'street', 'number', 'complement', 'district', 'city', 'state', 'country',
            'referral_source', 'referral_details', 'marital_status', 'occupation',
            'payment_category', 'responsible_membership', 'administrative_notes',
        ]
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date'}),
            'administrative_notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        from tenancy.models import Membership, MembershipStatus, Role

        queryset = Membership.objects.none()
        if tenant_id is not None:
            queryset = Membership.objects.filter(
                tenant_id=tenant_id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
            ).select_related('user')
        self.fields['responsible_membership'].queryset = queryset
        self.fields['responsible_membership'].required = False
        self.fields['responsible_membership'].label_from_instance = (
            lambda membership: membership.user.get_full_name() or membership.user.email
        )

    def clean_full_name(self):
        name = (self.cleaned_data['full_name'] or '').strip()
        if not name:
            raise forms.ValidationError('Full name is required.')
        return name

    def clean_cpf(self):
        raw = (self.cleaned_data.get('cpf') or '').strip()
        if not raw:
            return None
        digits = re.sub(r'\D', '', raw)
        validate_cpf(digits)
        return digits

    def clean_birth_date(self):
        from django.utils import timezone
        value = self.cleaned_data.get('birth_date')
        if value and value > timezone.now().date():
            raise forms.ValidationError('Birth date cannot be in the future.')
        return value


class PatientContactForm(forms.ModelForm):
    class Meta:
        model = PatientContact
        fields = [
            'name', 'relationship', 'phone', 'email', 'authorized_for_documents',
            'sms_enabled', 'email_enabled', 'legal_authority', 'authority_evidence',
        ]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('phone') and not cleaned.get('email'):
            raise forms.ValidationError('Informe telefone ou e-mail.')
        return cleaned


class PatientCoverageForm(forms.Form):
    plan = forms.ModelChoiceField(queryset=None, label='Plano')
    member_number = forms.CharField(label='Matrícula', max_length=60, required=False)
    starts_on = forms.DateField(label='Início da vigência', widget=forms.DateInput(attrs={'type': 'date'}))
    ends_on = forms.DateField(
        label='Fim da vigência', widget=forms.DateInput(attrs={'type': 'date'}), required=False,
    )

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import HealthPlan

        queryset = HealthPlan.objects.none()
        if tenant_id is not None:
            queryset = HealthPlan.objects.filter(tenant_id=tenant_id, active=True).select_related('insurer')
        self.fields['plan'].queryset = queryset
        self.fields['plan'].label_from_instance = lambda plan: f'{plan.insurer.name} — {plan.name}'
