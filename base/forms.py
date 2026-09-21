import re

from django import forms
from django.contrib.auth.password_validation import validate_password

from base.validators import validate_cnpj
from tenancy.models import Tenant
from tenancy.plans import plan_choices


class InvitationCodeForm(forms.Form):
    code = forms.CharField(label='Código de convite', max_length=128)


class OrganizationSignupForm(forms.Form):
    email = forms.EmailField(label='E-mail')
    password = forms.CharField(label='Senha', widget=forms.PasswordInput)
    #: A senha digitada duas vezes.
    #:
    #: Esta é a única senha do sistema que não tem como ser recuperada
    #: pelo caminho normal no minuto seguinte: quem a cria está criando
    #: **junto** a conta e a clínica, e um erro de digitação aqui tranca a
    #: pessoa fora de uma organização que acabou de nascer — com o e-mail
    #: de recuperação indo para o endereço que ela também acabou de
    #: digitar. Conferir duas vezes custa um campo.
    password_confirm = forms.CharField(label='Confirme a senha', widget=forms.PasswordInput)
    legal_name = forms.CharField(label='Razão social', max_length=255)
    trade_name = forms.CharField(label='Nome fantasia', max_length=255, required=False)
    cnpj = forms.CharField(label='CNPJ', max_length=18)

    #: A versão do contrato que estava na tela quando a pessoa leu.
    #:
    #: Vai e volta escondido para que uma publicação entre o carregamento
    #: e o envio não faça alguém aceitar um texto que não viu. O servidor
    #: não confia neste valor para gravar nada — ele só compara com a
    #: versão corrente e, se diferirem, devolve o formulário com o texto
    #: novo à vista. O que fica registrado é sempre `contract.VERSAO`.
    contract_version = forms.CharField(widget=forms.HiddenInput(), required=False)

    #: O aceite. `required=True` num `BooleanField` significa marcado:
    #: desmarcado o formulário não passa, e é essa a intenção -- criar uma
    #: clínica sem aceite registrado é criar uma clínica sem contrato.
    accept_contract = forms.BooleanField(
        label='Li e aceito o Contrato de Adesão e o tratamento de dados nele descrito',
        error_messages={'required': 'É preciso aceitar o contrato para criar a clínica.'},
    )

    #: Declaração de poderes para contratar (cláusula 2.2, "i").
    #:
    #: Campo separado da caixa de aceite, e não uma frase dentro dela.
    #: São duas declarações diferentes — "li e aceito" e "posso assinar
    #: por esta clínica" —, e a segunda é a que se discute quando alguém
    #: alega que quem clicou não tinha poderes. Juntas numa caixa só, não
    #: haveria como mostrar que a pergunta foi feita.
    #:
    #: Obrigatória: quem cria a organização vira o responsável dela, e
    #: responsável que não pode assinar pela clínica não deveria estar
    #: criando a clínica.
    declare_powers = forms.BooleanField(
        label='Declaro que possuo poderes para contratar em nome desta clínica',
        error_messages={
            'required': 'É preciso declarar que você pode contratar em nome da clínica.',
        },
    )

    def clean_contract_version(self):
        """A versão lida é a versão corrente?

        Se não for, o texto mudou entre abrir a página e enviar o
        formulário. Recusar aqui custa um reenvio; aceitar em silêncio
        registraria como lido um texto que ninguém leu -- que é
        exatamente o vício que anula uma cláusula de adesão.
        """
        from tenancy import contract

        lida = (self.cleaned_data.get('contract_version') or '').strip()
        if lida and lida != contract.VERSAO:
            raise forms.ValidationError(
                'O contrato foi atualizado enquanto você preenchia. '
                'Leia a versão nova abaixo e aceite de novo.'
            )
        return contract.VERSAO

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password

    def clean(self):
        """As duas senhas conferem?

        O erro fica no campo da confirmação, e não no topo do formulário:
        é lá que está o olho de quem acabou de digitar, e é lá que o
        conserto acontece.

        `clean_password` já rodou quando isto executa, então uma senha
        fraca aparece como senha fraca; a divergência só é cobrada quando
        há o que comparar — senão a pessoa receberia dois avisos sobre o
        mesmo campo, e o segundo esconderia o primeiro.
        """
        dados = super().clean()
        senha = dados.get('password')
        confirmacao = dados.get('password_confirm')
        if senha and confirmacao and senha != confirmacao:
            self.add_error('password_confirm', 'As duas senhas não são iguais.')
        return dados

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
    #: Plano de interesse. Era um campo escondido, preenchido so quando a
    #: pessoa chegava pelo botao de um cartao; quem rolava a pagina ate o
    #: formulario mandava o pedido sem dizer o que queria, e a resposta
    #: comecava por uma pergunta que a tela podia ter feito.
    #:
    #: As opcoes saem de `tenancy.plans`, e nao de uma lista aqui: um plano
    #: novo aparece no menu sem ninguem lembrar de uma segunda lista.
    #:
    #: Continua opcional -- exigir a escolha para responder a um "quanto
    #: custa?" seria barrar justamente quem ainda nao sabe.
    #: `CharField` com widget de menu, e **nao** `ChoiceField`.
    #:
    #: A diferenca e o que acontece com um valor que nao esta na lista.
    #: `ChoiceField` recusa o formulario inteiro -- e um codigo de plano
    #: antigo, vindo de uma pagina que ficou aberta ou em cache depois de
    #: renomearmos um plano, custaria o lead. Lead perdido e a unica falha
    #: desta tela que ninguem percebe: quem preencheu ve a mesma mensagem
    #: de sucesso.
    #:
    #: O menu guia quem esta olhando; o servidor nunca recusa por causa
    #: dele. Valor desconhecido vira "nao indicado" em `clean_plan`.
    plan = forms.CharField(
        label='Plano de interesse', required=False,
        widget=forms.Select(choices=plan_choices),
    )
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

        O campo virou um menu visivel, mas a regra do servidor nao mudou e
        nao deve mudar: recusar o formulario por causa dele puniria quem
        nao fez nada. O caso real nao e adulteracao -- e uma pagina que
        ficou aberta, ou em cache, com o codigo de um plano que desde
        entao foi renomeado.

        Plano e informacao de interesse, nao compromisso. Vazio le-se como
        "nao indicado", e o lead chega.
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
