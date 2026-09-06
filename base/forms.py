import re

from django import forms
from django.contrib.auth.password_validation import validate_password

from base.validators import validate_cnpj
from tenancy.models import Tenant


class InvitationCodeForm(forms.Form):
    code = forms.CharField(label='Código de convite', max_length=128)


class OrganizationSignupForm(forms.Form):
    email = forms.EmailField(label='E-mail')
    password = forms.CharField(label='Senha', widget=forms.PasswordInput)
    legal_name = forms.CharField(label='Razão social', max_length=255)
    trade_name = forms.CharField(label='Nome fantasia', max_length=255, required=False)
    cnpj = forms.CharField(label='CNPJ', max_length=18)

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password

    def clean_cnpj(self):
        digits = re.sub(r'\D', '', self.cleaned_data['cnpj'] or '')
        validate_cnpj(digits)
        if Tenant.objects.filter(cnpj=digits).exists():
            raise forms.ValidationError('CNPJ already registered.')
        return digits
