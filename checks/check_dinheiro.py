"""As duas entradas de dinheiro do produto aceitam o que o brasileiro digita?

Nasceu de um defeito real, encontrado na auditoria pre-deploy de
2026-09-24. `RecordPaymentView` e `ApplyAdjustmentView` -- as duas unicas
rotas que lancam dinheiro -- liam `request.POST.get('amount')` e entregavam
o texto cru a `quantize_brl`, que faz `Decimal(valor)`. As views capturavam
`except ValueError`, e `decimal.InvalidOperation` herda de
`ArithmeticError`, nao de `ValueError`.

Medido antes da correcao:

    '150,00'          -> InvalidOperation   (o jeito brasileiro de digitar)
    ''                -> InvalidOperation
    campo ausente     -> TypeError
    '1e999'           -> InvalidOperation
    'NaN'             -> **passava**, e viraria um pagamento NaN no banco
    '99999999999999'  -> passava, e estouraria o numeric(12,2) no INSERT

Nenhuma dessas linhas era capturada: todas viravam 500 na cara de quem
estava lancando o pagamento.

Tenta quebrar. As perguntas sao:

- virgula decimal e aceita? e o separador de milhar?
- valor vazio, ausente, NaN, infinito e de 14 digitos sao recusados **com
  mensagem**, e nao com 500?
- valor negativo e zero sao recusados?
- o tipo do ajuste ainda e conferido contra a lista?
- ajuste sem motivo passa? (o motivo vai para a trilha; sem ele, ninguem
  explica o desconto um ano depois)
- a forma de pagamento cabe na coluna?
"""
from decimal import Decimal

from finance.forms import AdjustmentForm, PaymentForm
from finance.models import AdjustmentType, Payment

falhas = []

print('=== 1. o que o usuario digita de verdade ===')
ACEITOS = [
    ('150,00', Decimal('150.00')),
    ('1.234,50', Decimal('1234.50')),
    ('150.00', Decimal('150.00')),
    ('0,01', Decimal('0.01')),
]
for texto, esperado in ACEITOS:
    formulario = PaymentForm({'amount': texto})
    valido = formulario.is_valid()
    obtido = formulario.cleaned_data['amount'] if valido else None
    print(f'  {texto:12} -> {obtido}')
    if not valido or obtido != esperado:
        falhas.append(f'{texto!r} devia virar {esperado} e deu {obtido!r}')

print('=== 2. o que tem de ser recusado COM MENSAGEM, e nao com 500 ===')
RECUSADOS = ['', 'NaN', 'Infinity', '1e999', '99999999999999', '-50', '0', 'abc', '1,2,3']
for texto in RECUSADOS:
    formulario = PaymentForm({'amount': texto})
    valido = formulario.is_valid()
    print(f'  {texto!r:18} -> {"ACEITOU (nao deveria)" if valido else "recusado"}')
    if valido:
        falhas.append(f'{texto!r} foi aceito como valor de pagamento')

formulario = PaymentForm({})
print(f'  campo ausente      -> {"ACEITOU (nao deveria)" if formulario.is_valid() else "recusado"}')
if formulario.is_valid():
    falhas.append('pagamento sem o campo de valor foi aceito')

print('=== 3. a forma de pagamento cabe na coluna ===')
coluna = Payment._meta.get_field('method').max_length
formulario = PaymentForm({'amount': '10', 'method': 'x' * (coluna + 10)})
print(f'  coluna={coluna}  texto com {coluna + 10} chars -> '
      f'{"ACEITOU (nao deveria)" if formulario.is_valid() else "recusado"}')
if formulario.is_valid():
    falhas.append(
        f'forma de pagamento maior que a coluna ({coluna}) passou — o erro '
        f'apareceria so no INSERT, como 500'
    )

formulario = PaymentForm({'amount': '10'})
vazio_vira = formulario.cleaned_data.get('method') if formulario.is_valid() else None
print(f'  forma vazia vira   -> {vazio_vira!r} (era o padrao da view antiga)')
if vazio_vira != 'other':
    falhas.append(f'forma de pagamento vazia virou {vazio_vira!r} e nao "other"')

print('=== 4. ajuste: tipo da lista e motivo obrigatorio ===')
for rotulo, dados, deve_passar in [
    ('tipo fora da lista', {'amount': '10', 'type': 'inventado', 'reason': 'x'}, False),
    ('motivo so com espaco', {'amount': '10', 'type': AdjustmentType.values[0], 'reason': '   '}, False),
    ('sem motivo', {'amount': '10', 'type': AdjustmentType.values[0]}, False),
    ('valido, com virgula', {'amount': '10,50', 'type': AdjustmentType.values[0], 'reason': 'glosa'}, True),
]:
    formulario = AdjustmentForm(dados)
    passou = formulario.is_valid()
    print(f'  {rotulo:22} -> {"aceito" if passou else "recusado"}')
    if passou != deve_passar:
        falhas.append(f'ajuste "{rotulo}": esperava {"aceito" if deve_passar else "recusado"}')

print('=== 5. os limites batem com a coluna do banco ===')
# Divergir daqui devolve o erro para o Postgres, que responde com 500 em vez
# de com uma mensagem ao lado do campo.
campo = PaymentForm().fields['amount']
coluna_valor = Payment._meta.get_field('amount')
print(f'  formulario: max_digits={campo.max_digits} decimal_places={campo.decimal_places}')
print(f'  coluna    : max_digits={coluna_valor.max_digits} decimal_places={coluna_valor.decimal_places}')
if (campo.max_digits, campo.decimal_places) != (coluna_valor.max_digits, coluna_valor.decimal_places):
    falhas.append('o formulario e a coluna discordam sobre o tamanho do valor')

print('=== 6. a data que o produto enxerga e a do fuso da clinica ===')
# O conteiner roda em Etc/UTC e o produto em America/Sao_Paulo. Das 21h a
# meia-noite, `datetime.date.today()` ja devolve o dia seguinte -- e o
# periodo padrao do financeiro e do painel abria em "amanha". No ultimo dia
# do mes, abria ja no mes que vem, com tudo zerado, e o usuario lia isso
# como "nao houve movimento".
#
# A asserção e estrutural porque o defeito so aparece em tres horas do dia:
# um roteiro que comparasse datas passaria nas outras vinte e uma.
import re

from django.conf import settings

SERVEM_REQUISICAO = [
    'finance/views.py', 'finance/fee_views.py', 'finance/fee_forms.py',
    'reporting/views.py', 'scheduling/forms.py', 'catalogs/cmed.py',
]
for relativo in SERVEM_REQUISICAO:
    fonte = (settings.BASE_DIR / relativo).read_text(encoding='utf-8')
    codigo = re.sub(r'(?m)^\s*#.*$', '', fonte)
    codigo = re.sub(r'""".*?"""', '', codigo, flags=re.S)
    usa = re.search(r'date\.today\(\)', codigo)
    print(f'  {relativo:24} usa date.today(): {bool(usa)}')
    if usa:
        falhas.append(
            f'{relativo} usa date.today(), que devolve a data do processo (UTC) '
            f'e nao a do fuso da clinica — use timezone.localdate()'
        )

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o dinheiro entra validado, e o que nao entra vira mensagem e nao 500.')
