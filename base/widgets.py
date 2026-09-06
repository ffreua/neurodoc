"""Campos nativos de data/hora do navegador, renderizados em ISO 8601.

Um `<input type="date">` só aceita `AAAA-MM-DD` como valor. Sem `format`
explícito, o Django renderiza a data no formato da localidade pt-BR
("15/07/1990"), que o navegador descarta em silêncio: ao abrir um cadastro
para edição o campo aparece **vazio**, e salvar assim apaga a data que já
estava gravada. O mesmo vale para `datetime-local` e `time`.

A leitura continua tolerante — `DATE_INPUT_FORMATS` do pt-BR aceita tanto
`15/07/1990` quanto `1990-07-15` —, então só a renderização precisa ser
fixada.
"""
from django import forms


class HTML5DateInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, attrs=None, format=None):  # noqa: A002 - assinatura do Django
        super().__init__(attrs=attrs, format=format or '%Y-%m-%d')


class HTML5DateTimeInput(forms.DateTimeInput):
    input_type = 'datetime-local'

    def __init__(self, attrs=None, format=None):  # noqa: A002 - assinatura do Django
        super().__init__(attrs=attrs, format=format or '%Y-%m-%dT%H:%M')


class HTML5TimeInput(forms.TimeInput):
    input_type = 'time'

    def __init__(self, attrs=None, format=None):  # noqa: A002 - assinatura do Django
        super().__init__(attrs=attrs, format=format or '%H:%M')
