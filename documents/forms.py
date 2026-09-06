from django import forms

from base.widgets import HTML5DateInput

from .models import AttachmentClassification, MedicalDocumentKind
from .signing_sessions import ALLOWED_DURATIONS_HOURS


class AttachmentUploadForm(forms.Form):
    file = forms.FileField(label='Arquivo')
    classification = forms.ChoiceField(label='Classificação', choices=AttachmentClassification.choices)
    document_date = forms.DateField(
        label='Data do documento', required=False, widget=HTML5DateInput(),
    )
    encounter_id = forms.UUIDField(required=False, widget=forms.HiddenInput)


class MedicalDocumentForm(forms.Form):
    kind = forms.ChoiceField(label='Tipo de documento', choices=MedicalDocumentKind.choices)
    prescription_text = forms.CharField(
        label='Prescrição', required=False, widget=forms.Textarea(attrs={'rows': 5}),
    )
    special_instructions = forms.CharField(
        label='Instruções especiais', required=False, widget=forms.Textarea(attrs={'rows': 3}),
    )
    report_text = forms.CharField(
        label='Texto do relatório', required=False, widget=forms.Textarea(attrs={'rows': 6}),
    )
    requested_procedure = forms.CharField(
        label='Procedimento solicitado', required=False, widget=forms.Textarea(attrs={'rows': 3}),
    )
    justification = forms.CharField(
        label='Justificativa', required=False, widget=forms.Textarea(attrs={'rows': 3}),
    )
    referral_specialty = forms.CharField(label='Especialidade do encaminhamento', required=False, max_length=255)
    reason = forms.CharField(label='Motivo', required=False, widget=forms.Textarea(attrs={'rows': 2}))


class CredentialUploadForm(forms.Form):
    pfx_file = forms.FileField(label='Arquivo PFX (A1)')
    password = forms.CharField(label='Senha do PFX', widget=forms.PasswordInput)


class SigningSessionStartForm(forms.Form):
    credential_id = forms.UUIDField(widget=forms.HiddenInput)
    duration_hours = forms.ChoiceField(
        label='Duração da sessão', choices=[(h, f'{h}h') for h in ALLOWED_DURATIONS_HOURS],
    )
    password = forms.CharField(label='Senha do PFX', widget=forms.PasswordInput)
