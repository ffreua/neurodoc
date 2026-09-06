from django import forms

from .models import AttachmentClassification, MedicalDocumentKind
from .signing_sessions import ALLOWED_DURATIONS_HOURS


class AttachmentUploadForm(forms.Form):
    file = forms.FileField()
    classification = forms.ChoiceField(choices=AttachmentClassification.choices)
    document_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    encounter_id = forms.UUIDField(required=False, widget=forms.HiddenInput)


class MedicalDocumentForm(forms.Form):
    kind = forms.ChoiceField(choices=MedicalDocumentKind.choices)
    prescription_text = forms.CharField(required=False, widget=forms.Textarea)
    special_instructions = forms.CharField(required=False, widget=forms.Textarea)
    report_text = forms.CharField(required=False, widget=forms.Textarea)
    requested_procedure = forms.CharField(required=False, widget=forms.Textarea)
    justification = forms.CharField(required=False, widget=forms.Textarea)
    referral_specialty = forms.CharField(required=False, max_length=255)
    reason = forms.CharField(required=False, widget=forms.Textarea)


class CredentialUploadForm(forms.Form):
    pfx_file = forms.FileField(label='Arquivo PFX (A1)')
    password = forms.CharField(widget=forms.PasswordInput)


class SigningSessionStartForm(forms.Form):
    credential_id = forms.UUIDField(widget=forms.HiddenInput)
    duration_hours = forms.ChoiceField(choices=[(h, f'{h}h') for h in ALLOWED_DURATIONS_HOURS])
    password = forms.CharField(widget=forms.PasswordInput)
