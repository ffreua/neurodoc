from django import forms

from .models import ConsanguinityState, DiagnosisCertainty, Encounter


class EncounterForm(forms.ModelForm):
    class Meta:
        model = Encounter
        fields = [
            'chief_complaint', 'hpi', 'personal_history', 'family_history',
            'consanguinity_state', 'consanguinity_details', 'plan_text', 'finalization_justification',
        ]
        labels = {
            'chief_complaint': 'Queixa principal',
            'hpi': 'História da doença atual',
            'personal_history': 'Antecedentes pessoais',
            'family_history': 'Antecedentes familiares',
            'consanguinity_state': 'Consanguinidade',
            'consanguinity_details': 'Detalhes da consanguinidade',
            'plan_text': 'Conduta',
            'finalization_justification': 'Justificativa da finalização',
        }
        widgets = {
            'chief_complaint': forms.Textarea(attrs={'rows': 3}),
            'hpi': forms.Textarea(attrs={'rows': 5}),
            'personal_history': forms.Textarea(attrs={'rows': 3}),
            'family_history': forms.Textarea(attrs={'rows': 3}),
            'consanguinity_details': forms.Textarea(attrs={'rows': 2}),
            'plan_text': forms.Textarea(attrs={'rows': 5}),
        }


class FindingForm(forms.Form):
    domain = forms.CharField(label='Domínio', max_length=40)
    item_code = forms.CharField(label='Item', max_length=60)
    side = forms.CharField(label='Lado', max_length=40, required=False)
    body_site = forms.CharField(label='Local anatômico', max_length=100, required=False)
    state = forms.CharField(label='Estado', max_length=40)
    numeric_value = forms.DecimalField(
        label='Valor numérico', max_digits=6, decimal_places=2, required=False,
    )
    qualifier = forms.CharField(label='Qualificador', max_length=255, required=False)
    note = forms.CharField(
        label='Observação', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}),
    )


class DiagnosisForm(forms.Form):
    diagnosis_code_id = forms.UUIDField(label='Código do catálogo', required=False)
    code_snapshot = forms.CharField(label='CID', max_length=20, required=False)
    description_snapshot = forms.CharField(
        label='Descrição', max_length=4000, required=False, widget=forms.Textarea(attrs={'rows': 2}),
    )
    certainty = forms.ChoiceField(label='Certeza', choices=DiagnosisCertainty.choices)
    rank = forms.IntegerField(label='Ordem', min_value=1, initial=1)
    physician_note = forms.CharField(
        label='Nota do médico', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}),
    )


class AmendmentForm(forms.Form):
    reason = forms.CharField(label='Motivo do adendo', max_length=255)
    text = forms.CharField(label='Texto do adendo', max_length=20000, widget=forms.Textarea(attrs={'rows': 4}))
