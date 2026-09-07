"""Campos de formulário que aceitam o número como se escreve aqui.

`forms.DecimalField` recusa "82,5" e devolve "Informe um número" — mesmo com
o campo prometendo "Ex.: 82,5" no placeholder. Quem digita peso digita com
vírgula, e ser recusado por causa do separador decimal é o tipo de atrito que
não tem razão de existir.

A conversão acontece antes da validação, então o resto do campo (mínimo,
máximo, casas decimais) continua valendo igual.
"""

from django import forms


class BrazilianDecimalField(forms.DecimalField):
    """Decimal que aceita vírgula e ponto como separador decimal.

    Também tolera o separador de milhar em ponto ("1.234,5"), que aparece
    quando o valor vem colado de outra tela. A regra é: se há vírgula, ela é
    o separador decimal e o ponto é milhar; se não há, o ponto é decimal.
    """

    def to_python(self, value):
        if isinstance(value, str):
            text = value.strip()
            if ',' in text:
                text = text.replace('.', '').replace(',', '.')
            value = text
        return super().to_python(value)
