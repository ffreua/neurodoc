from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Role


class CollaboratorInvitationForm(forms.Form):
    email = forms.EmailField(label='E-mail')
    roles = forms.MultipleChoiceField(
        label='Papéis', choices=Role.choices, widget=forms.CheckboxSelectMultiple,
    )

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()


class AcceptInvitationAccountForm(forms.Form):
    email = forms.EmailField(label='E-mail')
    password = forms.CharField(label='Senha', widget=forms.PasswordInput)

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password
