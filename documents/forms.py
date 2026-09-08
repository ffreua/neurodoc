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


class MedicalDocumentForm(forms.Form):
    kind = forms.ChoiceField(label='Tipo de documento', choices=MedicalDocumentKind.choices)
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

    def __init__(self, *args, locked_kind=None, **kwargs):
        """`locked_kind` trava o tipo — é o caso da retificação.

        A retificação corrige o conteúdo de um documento já emitido; o tipo
        é o do original. Deixar o seletor aberto ali permitia escolher
        "Relatório" para corrigir uma receita, e o servidor, que usa o tipo
        do original, lia campos que o formulário não pediu.
        """
        super().__init__(*args, **kwargs)
        if locked_kind:
            self.fields['kind'].initial = locked_kind
            self.fields['kind'].disabled = True
            self.fields['kind'].help_text = (
                'O tipo é o do documento que está sendo retificado e não muda.'
            )

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
        for name in document_kinds.REQUIRED_FIELDS[kind]:
            if not (cleaned.get(name) or '').strip():
                self.add_error(name, 'Este campo é obrigatório para o tipo escolhido.')
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
