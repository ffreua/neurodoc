"""As duas entradas de dinheiro do produto.

Existem porque não existiam: `RecordPaymentView` e `ApplyAdjustmentView`
liam `request.POST.get('amount')` e entregavam o texto cru a
`quantize_brl`, que faz `Decimal(valor)`. Medido na auditoria pré-deploy
de 2026-09-24:

    '150,00'          -> InvalidOperation   (o jeito brasileiro de digitar)
    ''                -> InvalidOperation
    campo ausente     -> TypeError
    '1e999'           -> InvalidOperation
    'NaN'             -> **passa**, e viraria um pagamento NaN no banco
    '99999999999999'  -> passa, e estoura o numeric(12,2) no INSERT

As views capturavam `except ValueError` — e `decimal.InvalidOperation`
herda de `ArithmeticError`, não de `ValueError`. Nenhuma das linhas acima
era capturada: todas viravam 500 na cara de quem estava lançando o
pagamento.

O resto do produto já fazia certo — `finance/fee_forms.py` usa
`DecimalField(max_digits=12, decimal_places=2)`, e o cadastro do paciente
usa `BrazilianDecimalField` justamente porque "quem digita peso digita com
vírgula". Estas duas rotas foram as que ficaram de fora, e são as que
mexem em dinheiro.

`max_digits=12` e `decimal_places=2` não são enfeite: são exatamente as
colunas `numeric(12,2)` de `Payment.amount` e `FinancialAdjustment.amount`.
Divergir daqui devolve o erro para o Postgres, que responde com 500 em vez
de com uma mensagem no campo.
"""
from decimal import Decimal

from django import forms

from base.fields import BrazilianDecimalField

from .models import AdjustmentType


class _ValorMonetarioForm(forms.Form):
    """O campo de valor, com os limites da coluna.

    `min_value` maior que zero, e não `>= 0`: os dois serviços já recusam
    valor não-positivo levantando `ValueError`, e recusar no formulário
    transforma o 403 numa mensagem ao lado do campo.
    """

    amount = BrazilianDecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'), label='Valor',
        error_messages={
            'invalid': 'Informe o valor em reais, com vírgula ou ponto (ex.: 150,00).',
            'required': 'Informe o valor.',
        },
    )


class PaymentForm(_ValorMonetarioForm):
    """Baixa de um recebível."""

    #: `max_length=40` é o tamanho da coluna `Payment.method`. A função
    #: `record_payment` já trunca `external_reference` em 100 e a razão do
    #: ajuste em 255, mas deixava `method` passar inteiro — um texto longo
    #: chegava ao banco e voltava como erro de coluna.
    method = forms.CharField(max_length=40, required=False, label='Forma')
    external_reference = forms.CharField(max_length=100, required=False, label='Referência')

    def clean_method(self):
        # Vazio vira 'other', que é o que a view passava como padrão.
        return (self.cleaned_data.get('method') or '').strip() or 'other'


class AdjustmentForm(_ValorMonetarioForm):
    """Desconto, glosa, acréscimo ou estorno sobre um recebível."""

    type = forms.ChoiceField(choices=AdjustmentType.choices, label='Tipo')
    reason = forms.CharField(max_length=255, label='Motivo')

    def clean_reason(self):
        motivo = (self.cleaned_data.get('reason') or '').strip()
        if not motivo:
            # Ajuste sem motivo é o que ninguém consegue explicar um ano
            # depois — e o motivo já vai para a trilha de auditoria.
            raise forms.ValidationError('Diga por que o valor está sendo ajustado.')
        return motivo
