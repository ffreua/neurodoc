import re

from django import forms
from django.contrib.auth.password_validation import validate_password

from base.validators import validate_cnpj
from tenancy.models import Tenant


class InvitationCodeForm(forms.Form):
    code = forms.CharField(label='Código de convite', max_length=128)


class OrganizationSignupForm(forms.Form):
    email = forms.EmailField(label='E-mail')
    password = forms.CharField(label='Senha', widget=forms.PasswordInput)
    legal_name = forms.CharField(label='Razão social', max_length=255)
    trade_name = forms.CharField(label='Nome fantasia', max_length=255, required=False)
    cnpj = forms.CharField(label='CNPJ', max_length=18)

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password

    def clean_cnpj(self):
        digits = re.sub(r'\D', '', self.cleaned_data['cnpj'] or '')
        validate_cnpj(digits)
        if Tenant.objects.filter(cnpj=digits).exists():
            raise forms.ValidationError('CNPJ already registered.')
        return digits


class LeadForm(forms.Form):
    """Pedido de contato da pagina de vendas.

    Formulario publico, sem conta, entao ele carrega as mesmas defesas do
    portal do paciente: limite por IP na view, e o campo-armadilha abaixo.

    Nao e `ModelForm` de proposito. O modelo tem `status`, `source_ip`,
    `notified_at` e `notify_error`, que sao do servidor; um `ModelForm`
    com `exclude` deixaria a decisao de quais campos sao do publico
    dependendo de alguem lembrar de atualizar a lista quando um campo
    novo aparecesse. Declarado, o formulario so aceita o que esta escrito
    aqui.
    """

    #: Campo-armadilha. Invisivel e sem rotulo para pessoa nenhuma, mas
    #: preenchido por robo que completa tudo o que encontra. Nome
    #: plausivel (`website`) porque `honeypot` entrega o truque aos robos
    #: que leem o HTML.
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    name = forms.CharField(
        label='Seu nome', max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: Dra. Ana Souza', 'autocomplete': 'name'}),
    )
    email = forms.EmailField(
        label='E-mail', max_length=254,
        widget=forms.EmailInput(attrs={'placeholder': 'voce@suaclinica.com.br', 'autocomplete': 'email'}),
    )
    phone = forms.CharField(
        label='Telefone ou WhatsApp', max_length=32, required=False,
        widget=forms.TextInput(attrs={'placeholder': '(11) 99999-0000', 'autocomplete': 'tel'}),
    )
    clinic_name = forms.CharField(
        label='Clinica ou consultorio', max_length=255, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: Clinica Neuro Paulista'}),
    )
    plan = forms.CharField(required=False, widget=forms.HiddenInput())
    message = forms.CharField(
        label='O que voce precisa', max_length=2000, required=False,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'Quantos medicos atendem, quantos pacientes voce acompanha, '
                           'o que usa hoje.',
        }),
    )

    def clean_name(self):
        nome = (self.cleaned_data.get('name') or '').strip()
        if len(nome) < 2:
            raise forms.ValidationError('Informe seu nome.')
        return nome

    def clean_plan(self):
        """Plano desconhecido vira vazio, e nao erro.

        O campo e oculto e vem do botao que a pessoa clicou. Se ele
        chegar adulterado, recusar o formulario puniria quem nao fez nada
        -- e o plano e informacao de interesse, nao compromisso. Vazio le-se
        como "nao indicado".
        """
        from tenancy.plans import PLANS

        escolhido = (self.cleaned_data.get('plan') or '').strip()
        return escolhido if escolhido in PLANS else ''

    def clean(self):
        dados = super().clean()
        if (dados.get('website') or '').strip():
            # Mensagem generica: dizer "isto parece um robo" ensina o robo
            # qual campo evitar na proxima tentativa.
            raise forms.ValidationError('Nao foi possivel enviar o formulario. Tente novamente.')
        return dados
