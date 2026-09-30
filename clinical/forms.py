from decimal import Decimal

from django import forms
from django.urls import reverse

from base.widgets import HTML5DateInput

from .models import (
    DiagnosisCertainty, Encounter, ExaminationDomain,
    ExaminationState, ExamResult, LabValue, Medication, Side,
)


class EncounterForm(forms.ModelForm):
    class Meta:
        model = Encounter
        fields = [
            'chief_complaint', 'hpi', 'personal_history', 'family_history', 'habits_history',
            'consanguinity_state', 'consanguinity_details', 'neurological_exam_text',
            'plan_text', 'finalization_justification', 'free_text', 'impressions',
        ]
        labels = {
            'chief_complaint': 'Queixa principal',
            'hpi': 'História da doença atual',
            'personal_history': 'Antecedentes pessoais',
            'family_history': 'Antecedentes familiares',
            'habits_history': 'Hábitos e vícios',
            'consanguinity_state': 'Consanguinidade',
            'consanguinity_details': 'Detalhes da consanguinidade',
            'neurological_exam_text': 'Exame neurológico em texto livre',
            'plan_text': 'Conduta',
            'free_text': 'Texto livre',
            'impressions': 'Impressões',
            'finalization_justification': 'Justificativa da finalização',
        }
        widgets = {
            # A queixa principal é uma linha ("cefaleia há 3 meses"); a
            # história da doença atual é o texto longo da consulta. A área de
            # digitação segue essa proporção em vez de dar o mesmo espaço às
            # duas.
            'chief_complaint': forms.Textarea(attrs={
                'rows': 2, 'placeholder': 'Em uma frase, o motivo da consulta',
            }),
            'hpi': forms.Textarea(attrs={
                'rows': 10,
                'placeholder': 'Início, evolução, fatores de melhora e piora, sintomas associados, '
                               'tratamentos já tentados…',
            }),
            'personal_history': forms.Textarea(attrs={'rows': 4}),
            'family_history': forms.Textarea(attrs={'rows': 4}),
            'habits_history': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Tabagismo, álcool, outras substâncias, sono, atividade física…',
            }),
            'consanguinity_details': forms.Textarea(attrs={'rows': 2}),
            'neurological_exam_text': forms.Textarea(attrs={
                'rows': 7,
                'placeholder': 'Descreva livremente os achados do exame neurológico.',
            }),
            'plan_text': forms.Textarea(attrs={'rows': 8}),
            # A caixa de texto livre é o corpo da consulta inteira quando o
            # médico escolhe escrever corrido: nasce alta, e o JavaScript a
            # faz crescer com o que for digitado.
            'free_text': forms.Textarea(attrs={
                'rows': 18,
                'placeholder': 'Escreva a consulta como preferir — queixa, exame, raciocínio.',
            }),
            'impressions': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'O que você concluiu do caso. Este campo pode ser levado '
                               'para a próxima consulta.',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A página também contém textareas de medicação, hipótese, achado e
        # exame. Só estes campos pertencem ao corpo do atendimento e podem
        # virar rascunho local/restaurável.
        for field in self.fields.values():
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs['data-nd-encounter-draft'] = '1'


#: Identificador do formulário do atendimento em texto livre.
#:
#: A tela é uma coluna só, na ordem em que o médico pensa: texto, medicação,
#: impressões e conduta, hipóteses. Medicação e hipóteses trazem formulários
#: próprios, e HTML **não aninha formulário** — o `<form>` do atendimento não
#: pode envolvê-los.
#:
#: A saída é o atributo `form=` do HTML5: o campo aponta para o formulário a
#: que pertence e pode estar em qualquer lugar da página. A alternativa era
#: espalhar o atendimento em três formulários separados, com um botão de
#: salvar cada — e salvar o texto perdendo a conduta digitada logo abaixo é
#: pior do que qualquer arranjo de colunas.
FORMULARIO_TEXTO_LIVRE = 'nd-atendimento-livre'


class FreeTextEncounterForm(EncounterForm):
    """`EncounterForm` com os campos amarrados ao formulário por `form=`.

    Subclasse em vez de um parâmetro no `EncounterForm`: o atributo só faz
    sentido nesta tela, e estampá-lo no formulário compartilhado o levaria
    para a tela estruturada, onde os campos estão dentro do `<form>` e um
    `form=` apontando para um id inexistente os tiraria do envio.
    """

    CAMPOS_DA_TELA = ('free_text', 'impressions', 'plan_text')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome in self.CAMPOS_DA_TELA:
            self.fields[nome].widget.attrs['form'] = FORMULARIO_TEXTO_LIVRE


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
    """Hipótese diagnóstica, com busca no CID-10.

    A busca é por código **ou** por descrição, porque é assim que se procura
    de fato: quem sabe que é G40 digita G40, quem está pensando em "epilepsia
    focal" digita isso. Escolher um resultado preenche código e descrição.

    Nada obriga a usar o catálogo: uma hipótese ainda sem CID pode ser escrita
    à mão, e é justamente o caso mais comum na primeira consulta. O que não se
    aceita é hipótese vazia.
    """

    cid_search = forms.CharField(
        label='Buscar no CID-10', required=False, max_length=200,
        help_text='Digite o código (G40) ou parte da descrição (epilepsia focal).',
        widget=forms.TextInput(attrs={
            'placeholder': 'Ex.: G40, enxaqueca, esclerose múltipla…',
            'autocomplete': 'off', 'data-nd-cid-search': '1',
        }),
    )
    diagnosis_code_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    code_snapshot = forms.CharField(
        label='CID', max_length=20, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'G43.0'}),
    )
    description_snapshot = forms.CharField(
        label='Hipótese', max_length=4000, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Descrição da hipótese'}),
    )
    certainty = forms.ChoiceField(
        label='Certeza', choices=DiagnosisCertainty.choices, initial=DiagnosisCertainty.SUSPECTED,
    )
    rank = forms.IntegerField(label='Ordem', min_value=1, initial=1)
    physician_note = forms.CharField(
        label='Nota do médico', max_length=2000, required=False,
        widget=forms.Textarea(attrs={
            'rows': 2, 'placeholder': 'O que sustenta esta hipótese, o que falta investigar…',
        }),
    )

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get('description_snapshot') or '').strip():
            # Sem isto dava para gravar uma hipótese em branco, que aparecia no
            # prontuário como uma linha vazia com um grau de certeza ao lado.
            self.add_error(
                'description_snapshot',
                'Escolha um código no CID-10 ou escreva a hipótese.',
            )
        return cleaned


class AmendmentForm(forms.Form):
    reason = forms.CharField(label='Motivo do adendo', max_length=255)
    text = forms.CharField(label='Texto do adendo', max_length=20000, widget=forms.Textarea(attrs={'rows': 4}))


class MedicationForm(forms.ModelForm):
    class Meta:
        model = Medication
        fields = [
            'name', 'dose', 'route', 'frequency', 'started_on', 'indication',
            'status', 'prescriber', 'notes',
        ]
        labels = {
            'name': 'Medicamento',
            'dose': 'Dose',
            'route': 'Via',
            'frequency': 'Posologia',
            'started_on': 'Em uso desde',
            'indication': 'Indicação',
            'status': 'Situação',
            'prescriber': 'Prescritor',
            'notes': 'Observação',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex.: Topiramato'}),
            'dose': forms.TextInput(attrs={'placeholder': 'Ex.: 50 mg'}),
            'frequency': forms.TextInput(attrs={'placeholder': 'Ex.: 1 comprimido à noite'}),
            'indication': forms.TextInput(attrs={'placeholder': 'Ex.: profilaxia de migrânea'}),
            'prescriber': forms.TextInput(attrs={'placeholder': 'Quem prescreveu, se não foi você'}),
            'started_on': HTML5DateInput(),
            'notes': forms.Textarea(attrs={
                'rows': 2, 'placeholder': 'Efeito adverso, aderência, motivo da suspensão…',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'autocomplete': 'off',
            'data-nd-med-url': reverse('catalogs:medicamento-search'),
            # Seletor relativo ao `data-nd-med-grupo`: funciona nas duas
            # telas sem depender de id global ou de posição no HTML.
            'data-nd-med-dose': "[name='dose']",
        })


class ExamResultForm(forms.ModelForm):
    """Resultado de exame, com o laudo em PDF no mesmo envio.

    O arquivo é opcional: registrar "TSH 4,1 em 12/08" sem ter o PDF em mãos
    é um caso real e não deve travar o registro.
    """

    report_file = forms.FileField(
        label='Laudo em PDF ou imagem', required=False,
        help_text='Até 25 MB. Passa por verificação de malware antes de ficar disponível.',
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png,.tif,.tiff'}),
    )
    run_extraction = forms.BooleanField(
        label='Pedir à IA para ler o laudo', required=False, initial=True,
        help_text='Gera um rascunho para sua revisão. Nada entra no prontuário sem você aceitar.',
    )

    class Meta:
        model = ExamResult
        fields = ['category', 'name', 'performed_on', 'service_name', 'report_text', 'conclusion']
        labels = {
            'category': 'Tipo de exame',
            'name': 'Exame',
            'performed_on': 'Data de realização',
            'service_name': 'Serviço / laboratório',
            'report_text': 'Laudo',
            'conclusion': 'Conclusão',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex.: RM de encéfalo, hemograma, ENMG de MMII'}),
            'service_name': forms.TextInput(attrs={'placeholder': 'Onde foi realizado'}),
            'performed_on': HTML5DateInput(),
            'report_text': forms.Textarea(attrs={
                'rows': 6, 'placeholder': 'Transcrição do laudo. Pode ficar em branco e ser preenchido '
                                          'pela leitura do PDF depois da sua revisão.',
            }),
            'conclusion': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Impressão diagnóstica do laudo'}),
        }


class LabValueForm(forms.ModelForm):
    """Um analito lançado à mão.

    A faixa de referência é digitada junto porque é a do laudo em questão:
    ela muda com laboratório, método, idade e sexo, e o sistema classifica o
    resultado apenas contra a faixa que veio com ele.
    """

    class Meta:
        model = LabValue
        fields = [
            'analyte', 'value_text', 'numeric_value', 'unit',
            'reference_low', 'reference_high', 'reference_text',
        ]
        labels = {
            'analyte': 'Analito',
            'value_text': 'Resultado',
            'numeric_value': 'Valor numérico',
            'unit': 'Unidade',
            'reference_low': 'Referência mín.',
            'reference_high': 'Referência máx.',
            'reference_text': 'Referência (texto)',
        }
        help_texts = {
            'numeric_value': 'Preencha para o sistema comparar com a referência.',
            'reference_text': 'Quando a referência não é numérica (ex.: “não reagente”).',
        }
        widgets = {
            'analyte': forms.TextInput(attrs={'placeholder': 'Ex.: Vitamina B12'}),
            'value_text': forms.TextInput(attrs={'placeholder': 'Ex.: 187'}),
            'unit': forms.TextInput(attrs={'placeholder': 'Ex.: pg/mL'}),
        }
