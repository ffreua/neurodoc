from django import forms

from tenancy.plans import PERIODICIDADES, Periodicidade, brl, preco_na_periodicidade


class ContratarForm(forms.Form):
    """O mínimo para abrir o pagamento: forma de pagamento, nome e e-mail.

    CPF, CNPJ, telefone e endereço de cobrança são pedidos **pela Asaas**, na
    página dela, e não aqui: o checkout recusa dados de cliente pela metade, e
    pedir tudo duas vezes seria dado pessoal passando por um lugar a mais. O
    CNPJ ou CPF da clínica continua sendo pedido no cadastro, como sempre.

    O e-mail é o que recebe o link de cadastro, e por isso é conferido aqui
    contra as duas recusas que o cadastro faria **depois** do pagamento: conta
    já existente e e-mail descartável. Descobrir isso com o dinheiro já pago
    seria o pior momento.
    """

    website = forms.CharField(required=False, widget=forms.HiddenInput())
    periodicidade = forms.ChoiceField(label='Forma de pagamento', widget=forms.RadioSelect)
    nome = forms.CharField(
        label='Seu nome', max_length=150,
        widget=forms.TextInput(attrs={'autocomplete': 'name', 'placeholder': 'Ex.: Dra. Ana Souza'}),
    )
    email = forms.EmailField(
        label='E-mail', max_length=254,
        help_text='O link para criar a clínica chega neste endereço, que será o seu acesso.',
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'placeholder': 'voce@suaclinica.com.br'}),
    )
    li_o_contrato = forms.BooleanField(
        label='Li o contrato de adesão e as condições acima. O aceite formal é feito ao criar a clínica.',
        error_messages={'required': 'Marque que leu o contrato de adesão.'},
    )

    def __init__(self, *args, plano, **kwargs):
        super().__init__(*args, **kwargs)
        self.plano = plano
        opcoes = []
        for codigo, regra in PERIODICIDADES.items():
            preco = preco_na_periodicidade(plano, codigo)
            if codigo == Periodicidade.ANUAL:
                como = 'Pix ou cartão, pagamento único'
            else:
                como = f'{regra["pagamento"]} no cartão de crédito'
            opcoes.append((str(codigo), f'{codigo.label}: {brl(preco["pagamento"])} {regra["por"]} '
                                        f'({como}; total do ano {brl(preco["ano"])})'))
        self.fields['periodicidade'].choices = opcoes

    def clean_email(self):
        from accounts.models import User
        from catalogs.descartaveis import e_descartavel

        email = self.cleaned_data['email'].strip().lower()
        if e_descartavel(email):
            raise forms.ValidationError(
                'Este endereço é de um serviço de e-mail temporário. Use um e-mail que você '
                'vai continuar acessando: é por ele que se entra no sistema.'
            )
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                'Este e-mail já tem conta no NeuroDoc. Para contratar um plano para a clínica '
                'que você já usa, fale conosco pelo formulário de contato; para uma clínica '
                'nova, use outro e-mail.'
            )
        return email
