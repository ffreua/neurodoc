from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import ClinicProfile, Role

#: Texto que explica cada papel na hora de concedê-lo.
#:
#: O nome do papel não diz o que ele abre. "Gestor" e "Secretaria" soam
#: parecidos para quem está cadastrando a equipe, e a diferença — quem vê
#: faturamento, quem não vê — só aparece depois, quando alguém abre uma tela
#: que não devia. A matriz do PRD resumida aqui é o que torna a escolha
#: informada no momento em que ela é feita.
ROLE_HELP = {
    Role.OWNER: 'Administra a organização: convida, concede papel e revoga vínculo. '
                'Não lê prontuário — a menos que também tenha o papel de médico.',
    Role.DOCTOR: 'Atende, lê e escreve prontuário, emite e assina documento. '
                 'Assinar exige ainda o registro profissional verificado.',
    Role.SECRETARY: 'Recepção: agenda, cadastro de paciente, contato e cobrança. '
                    'Não abre prontuário, exame nem anexo clínico.',
    Role.MANAGER: 'Operação da clínica: indicadores, financeiro e credenciais de '
                  'provedor (SMS, e-mail, IA). Não abre prontuário.',
}


def _role_choices():
    return [(value, f'{label} — {ROLE_HELP[value]}') for value, label in Role.choices]


class CollaboratorInvitationForm(forms.Form):
    email = forms.EmailField(label='E-mail')
    roles = forms.MultipleChoiceField(
        label='Papéis', choices=_role_choices, widget=forms.CheckboxSelectMultiple,
    )

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()


class MembershipRolesForm(forms.Form):
    """Troca os papéis de um vínculo que já existe.

    Existe porque a equipe muda sem que as pessoas mudem: a secretária passa
    a cuidar do financeiro, o médico assume a administração. Sem isto, a
    única saída era revogar o vínculo e convidar de novo — o que apaga a
    trilha de quem fez o quê e obriga a pessoa a criar acesso outra vez.
    """

    #: `required=False` para que a recusa seja a mensagem escrita abaixo.
    #: Com `required=True` o Django rejeita antes de `clean_roles` rodar e
    #: responde "Este campo é obrigatório.", que não diz o que fazer com um
    #: vínculo que não deve mais ter acesso.
    roles = forms.MultipleChoiceField(
        label='Papéis', choices=_role_choices, widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    def clean_roles(self):
        roles = self.cleaned_data.get('roles')
        if not roles:
            # Vínculo sem papel nenhum entra no sistema e não alcança nada:
            # é um acesso que existe e não serve. Revogar é a ação para
            # isso, e ela é explícita.
            raise forms.ValidationError(
                'Escolha ao menos um papel. Para tirar o acesso, revogue o vínculo.',
            )
        return roles


class PhysicianProfileForm(forms.ModelForm):
    """Registro profissional do médico, para o cabeçalho e para a assinatura.

    Estes campos não são enfeite de PDF: CFM 2.381/2024 exige identificação
    do médico emissor em todo documento — nome, CRM e UF —, e o RQE quando
    houver especialidade registrada. Sem eles a montagem do documento
    quebra ao procurar `physician_profile`, o que hoje acontece **na hora de
    assinar**, com o atendimento já finalizado.
    """

    class Meta:
        from accounts.models import PhysicianProfile

        model = PhysicianProfile
        fields = [
            'professional_name', 'crm_number', 'crm_state', 'rqe',
            'professional_phone', 'professional_email', 'professional_address',
        ]
        labels = {
            'professional_name': 'Nome profissional',
            'crm_number': 'CRM',
            'crm_state': 'UF do CRM',
            'rqe': 'RQE',
            'professional_phone': 'Telefone profissional',
            'professional_email': 'E-mail profissional',
            'professional_address': 'Endereço profissional',
        }
        help_texts = {
            'professional_name': 'Como assina — é o nome que sai no documento.',
            'rqe': 'Registro de Qualificação de Especialista, se houver.',
        }
        widgets = {
            'crm_state': forms.TextInput(attrs={'maxlength': '2', 'placeholder': 'SP'}),
            'professional_phone': forms.TextInput(attrs={'inputmode': 'tel'}),
        }

    def clean_crm_state(self):
        return (self.cleaned_data.get('crm_state') or '').upper()

    def clean_crm_number(self):
        number = (self.cleaned_data.get('crm_number') or '').strip()
        if not number.isdigit():
            raise forms.ValidationError('O CRM é só o número, sem UF nem pontuação.')
        return number


class ClinicProfileForm(forms.ModelForm):
    """Identidade da clínica — o que sai no cabeçalho do documento."""

    class Meta:
        model = ClinicProfile
        fields = [
            'address_line', 'address_district', 'city', 'state', 'postal_code',
            'phone', 'email', 'website',
        ]
        labels = {
            'address_line': 'Endereço',
            'address_district': 'Bairro',
            'city': 'Município',
            'state': 'UF',
            'postal_code': 'CEP',
            'phone': 'Telefone',
            'email': 'E-mail de contato',
            'website': 'Site',
        }
        help_texts = {
            'email': 'Aparece no cabeçalho do documento. Não é o remetente do '
                     'sistema — esse fica em Mensageria.',
        }
        widgets = {
            'address_line': forms.TextInput(attrs={'placeholder': 'Rua, número, complemento'}),
            'state': forms.TextInput(attrs={'maxlength': '2', 'placeholder': 'SP'}),
            'postal_code': forms.TextInput(attrs={'placeholder': '01310-100'}),
            'phone': forms.TextInput(attrs={'inputmode': 'tel', 'placeholder': '(11) 3333-0000'}),
        }

    def clean_state(self):
        return (self.cleaned_data.get('state') or '').upper()


class ClinicPortalForm(forms.ModelForm):
    """Publicação do portal de solicitações.

    Separado do cabeçalho do documento porque as duas telas fazem coisas de
    natureza diferente. Trocar o CEP corrige uma impressão; ligar o portal
    publica na internet um endereço que aceita CPF e data de nascimento de
    pacientes. Misturar as duas coisas num botão "Salvar" só faz a segunda
    acontecer por acidente.
    """

    class Meta:
        model = ClinicProfile
        fields = ['patient_portal_enabled', 'patient_portal_notice']
        labels = {
            'patient_portal_enabled': 'Publicar o portal de solicitações',
            'patient_portal_notice': 'Aviso exibido no portal',
        }
        help_texts = {
            'patient_portal_enabled': 'Enquanto estiver desligado, o endereço responde '
                                      'como inexistente — nem a existência da clínica é '
                                      'confirmada a quem o acessa.',
            'patient_portal_notice': 'Prazo de resposta, o que este canal não atende, '
                                     'orientações. Aparece antes do formulário.',
        }
        widgets = {
            'patient_portal_notice': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Ex.: pedidos são respondidos em até 3 dias úteis. '
                               'Este canal não atende urgências.',
            }),
        }


class AcceptInvitationAccountForm(forms.Form):
    email = forms.EmailField(label='E-mail')
    password = forms.CharField(label='Senha', widget=forms.PasswordInput)

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password
