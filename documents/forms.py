from django import forms

from .models import AttachmentClassification


class AttachmentUploadForm(forms.Form):
    file = forms.FileField()
    classification = forms.ChoiceField(choices=AttachmentClassification.choices)
    document_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    encounter_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
