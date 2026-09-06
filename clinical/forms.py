from decimal import Decimal

from django import forms

from .models import (
    ConsanguinityState, DiagnosisCertainty, Encounter, ExaminationDomain,
    ExaminationState, Side,
)


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
    """Registro de um item do exame.

    O item vem de um `<select>` agrupado por domínio (`dominio:item`), e não
    de dois campos de texto livre: digitar `sensory_superficial` à mão era
    a única forma de registrar um achado, e um código errado só aparecia
    como erro depois de enviar.
    """

    item = forms.ChoiceField(label='Item do exame', choices=())
    side = forms.ChoiceField(label='Lado', choices=Side.choices, initial=Side.NOT_APPLICABLE)
    state = forms.ChoiceField(
        label='Estado', choices=ExaminationState.choices, initial=ExaminationState.NOT_ASSESSED,
    )
    numeric_value = forms.ChoiceField(
        label='Grau (MRC)', required=False,
        choices=[('', '—')] + [(str(g), f'{g}') for g in range(6)],
        help_text='Somente para força: 0 a 5.',
    )
    body_site = forms.CharField(
        label='Local anatômico', max_length=100, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: território de C6'}),
    )
    qualifier = forms.CharField(
        label='Qualificador', max_length=255, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: extensor, hipertonia elástica'}),
    )
    note = forms.CharField(
        label='Observação', max_length=2000, required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Detalhe do achado, limitação do exame…'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .examination import grouped_item_choices

        self.fields['item'].choices = [('', 'Selecione o item')] + grouped_item_choices()

    def clean(self):
        cleaned = super().clean()
        raw = cleaned.get('item') or ''
        if ':' not in raw:
            if raw:
                self.add_error('item', 'Item inválido.')
            return cleaned
        domain, item_code = raw.split(':', 1)
        cleaned['domain'] = domain
        cleaned['item_code'] = item_code

        value = cleaned.get('numeric_value')
        if value in ('', None):
            cleaned['numeric_value'] = None
        elif domain != ExaminationDomain.STRENGTH:
            self.add_error('numeric_value', 'O grau MRC só se aplica a itens de força.')
        else:
            cleaned['numeric_value'] = Decimal(value)
        return cleaned


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
