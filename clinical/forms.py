from django import forms

from .models import ConsanguinityState, DiagnosisCertainty, Encounter


class EncounterForm(forms.ModelForm):
    class Meta:
        model = Encounter
        fields = [
            'chief_complaint', 'hpi', 'personal_history', 'family_history',
            'consanguinity_state', 'consanguinity_details', 'plan_text', 'finalization_justification',
        ]
        widgets = {
            'chief_complaint': forms.Textarea(attrs={'rows': 3}),
            'hpi': forms.Textarea(attrs={'rows': 5}),
            'personal_history': forms.Textarea(attrs={'rows': 3}),
            'family_history': forms.Textarea(attrs={'rows': 3}),
            'consanguinity_details': forms.Textarea(attrs={'rows': 2}),
            'plan_text': forms.Textarea(attrs={'rows': 5}),
        }


class FindingForm(forms.Form):
    domain = forms.CharField(max_length=40)
    item_code = forms.CharField(max_length=60)
    side = forms.CharField(max_length=40, required=False)
    body_site = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=40)
    numeric_value = forms.DecimalField(max_digits=6, decimal_places=2, required=False)
    qualifier = forms.CharField(max_length=255, required=False)
    note = forms.CharField(max_length=2000, required=False, widget=forms.Textarea)


class DiagnosisForm(forms.Form):
    diagnosis_code_id = forms.UUIDField(required=False)
    code_snapshot = forms.CharField(max_length=20, required=False)
    description_snapshot = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)
    certainty = forms.ChoiceField(choices=DiagnosisCertainty.choices)
    rank = forms.IntegerField(min_value=1, initial=1)
    physician_note = forms.CharField(max_length=2000, required=False, widget=forms.Textarea)


class AmendmentForm(forms.Form):
    reason = forms.CharField(max_length=255)
    text = forms.CharField(max_length=20000, widget=forms.Textarea)
