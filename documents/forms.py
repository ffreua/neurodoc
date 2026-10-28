from django import forms

from base.widgets import HTML5DateInput

from .models import AttachmentClassification, MedicalDocumentKind
from .pdf.prescription import (
    FORMAT_CHOICES as PRESCRIPTION_FORMAT_CHOICES, SIMPLE, SPECIAL_CONTROL,
)
from .signing_sessions import ALLOWED_DURATIONS_HOURS


class AttachmentUploadForm(forms.Form):
    file = forms.FileField(label='Arquivo')
    classification = forms.ChoiceField(label='Classificação', choices=AttachmentClassification.choices)
    document_date = forms.DateField(
        label='Data do documento', required=False, widget=HTML5DateInput(),
    )
    encounter_id = forms.UUIDField(required=False, widget=forms.HiddenInput)


#: Os tipos que o formulário genérico emite. Pedido de exames e
#: solicitação de cirurgia ficam de fora de propósito: o conteúdo deles é
#: lista (exames, procedimentos, materiais), e este formulário só carrega
#: texto — escolhê-los aqui geraria um documento vazio. Nascem da tela de
#: emissão por modelo (`modelos/emissao.py`), e a retificação deles também
#: não passa por aqui.
TIPOS_DO_FORMULARIO = [
    (valor, rotulo) for valor, rotulo in MedicalDocumentKind.choices
    if valor not in (MedicalDocumentKind.EXAM_REQUEST, MedicalDocumentKind.SURGERY_REQUEST)
]


class MedicalDocumentForm(forms.Form):
    kind = forms.ChoiceField(label='Tipo de documento', choices=TIPOS_DO_FORMULARIO)
    prescription_format = forms.ChoiceField(
        label='Formato da receita', required=False,
        choices=PRESCRIPTION_FORMAT_CHOICES, initial=SIMPLE,
        help_text='O controle especial (Portaria 344/98) sai em duas vias — uma fica '
                  'retida na farmácia — e exige o endereço completo do paciente.',
    )
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
    classificacao_confirmada = forms.BooleanField(
        label='Confirmo a classificação desta receita', required=False,
        help_text='Marque quando o NeuroDoc não encontrar o medicamento na lista oficial, ou quando '
                  'ele só vai para a Receita de Controle Especial pelo adendo da lista (dose e forma). '
                  'A confirmação fica gravada com a receita.',
    )

    def __init__(self, *args, locked_kind=None, **kwargs):
        """`locked_kind` trava o tipo — é o caso da retificação.

        A retificação corrige o conteúdo de um documento já emitido; o tipo
        é o do original. Deixar o seletor aberto ali permitia escolher
        "Relatório" para corrigir uma receita, e o servidor, que usa o tipo
        do original, lia campos que o formulário não pediu.
        """
        super().__init__(*args, **kwargs)
        self._acrescentar_receita_eletronica()
        if locked_kind:
            self.fields['kind'].initial = locked_kind
            self.fields['kind'].disabled = True
            self.fields['kind'].help_text = (
                'O tipo é o do documento que está sendo retificado e não muda.'
            )

    def _acrescentar_receita_eletronica(self):
        """Os itens estruturados e, com o SNCR ligado, os formatos eletrônicos.

        Os campos dos itens existem sempre (o formulário tem um conjunto
        fixo de nomes), mas as opções de formato eletrônico só aparecem com a
        integração ligada (`sncr.models.Configuracao.ativo`): desligada, o
        valor `sncr_rce` enviado à mão é "escolha inválida", e o servidor
        nunca começa uma receita que não pode numerar.
        """
        from sncr import receita
        from sncr.models import Configuracao

        exemplos = {
            'nome': 'Ex.: Sertralina (nome da substância, DCB)', 'concentracao': 'Ex.: 50 mg',
            'forma': 'Ex.: comprimido revestido', 'quantidade': 'Ex.: 60 comprimidos',
            'posologia': 'Ex.: 1 comprimido pela manhã',
        }
        for n in range(1, receita.LIMITE_MEDICAMENTOS + 1):
            for campo in receita.CAMPOS_DO_ITEM:
                self.fields[f'item{n}_{campo}'] = forms.CharField(
                    label=receita.ROTULOS_DO_ITEM[campo], required=False,
                    max_length=receita.TAMANHO_MAXIMO[campo],
                    widget=(forms.Textarea(attrs={'rows': 2, 'placeholder': exemplos[campo]}) if campo == 'posologia'
                            else forms.TextInput(attrs={'placeholder': exemplos[campo]})),
                )
        if Configuracao.carregar().ativo:
            self.fields['prescription_format'].choices = (
                list(PRESCRIPTION_FORMAT_CHOICES) + list(receita.FORMAT_CHOICES)
            )

    def itens_do_sncr(self):
        """Os campos de cada item, agrupados para o template desenhar por linha."""
        from sncr import receita

        return [
            (n, [self[f'item{n}_{campo}'] for campo in receita.CAMPOS_DO_ITEM])
            for n in range(1, receita.LIMITE_MEDICAMENTOS + 1)
        ]

    def clean(self):
        """Exige os campos do tipo escolhido — e só os dele.

        Todos os campos são `required=False` porque cada tipo usa um
        subconjunto. Sem esta verificação, a ausência só era percebida em
        `issuance.create_draft`, que devolve `ValueError` sem apontar o
        campo: o médico recebia "Missing required fields for prescription"
        em inglês, sem marcação no campo que faltava.
        """
        from . import document_kinds

        cleaned = super().clean()
        kind = cleaned.get('kind')
        if not kind or kind not in document_kinds.REQUIRED_FIELDS:
            return cleaned
        from sncr import receita

        eletronica = cleaned.get('prescription_format') in receita.FORMATOS
        for name in document_kinds.REQUIRED_FIELDS[kind]:
            # Na receita eletrônica a prescrição em texto é montada dos itens.
            if eletronica and name == 'prescription_text':
                continue
            if not (cleaned.get(name) or '').strip():
                self.add_error(name, 'Este campo é obrigatório para o tipo escolhido.')
        if kind == 'prescription' and eletronica:
            for campo in receita.CAMPOS_DO_ITEM:
                if not (cleaned.get(f'item1_{campo}') or '').strip():
                    self.add_error(f'item1_{campo}', 'Preencha o primeiro medicamento por inteiro.')
        return cleaned


class CredentialUploadForm(forms.Form):
    pfx_file = forms.FileField(label='Arquivo PFX (A1)')
    password = forms.CharField(label='Senha do PFX', widget=forms.PasswordInput)


class SigningSessionStartForm(forms.Form):
    credential_id = forms.UUIDField(widget=forms.HiddenInput)
    duration_hours = forms.ChoiceField(
        label='Duração da sessão', choices=[(h, f'{h}h') for h in ALLOWED_DURATIONS_HOURS],
    )
    password = forms.CharField(label='Senha do PFX', widget=forms.PasswordInput)
