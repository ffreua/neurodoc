"""O dia que o produto enxerga e o da clinica, e nao o do processo.

O conteiner roda em `Etc/UTC` e o produto em `America/Sao_Paulo`. Entre
21h e meia-noite, horario de Brasilia, o UTC **ja esta no dia seguinte** --
e todo codigo que pergunta "que dia e hoje" ao relogio do processo
responde amanha, por tres horas, toda noite.

O sintoma e discreto e constante: a agenda do mes marca o dia errado como
hoje; o financeiro abre o periodo padrao em "amanha" e, no ultimo dia do
mes, ja no mes seguinte com tudo zerado -- que o usuario le como "nao
houve movimento"; a fila de retornos conta como atrasado quem vence
amanha. Nenhum desses vira chamado de suporte. Viram desconfianca.

**Por que a assercao e estrutural, e nao comparativa.** O defeito so
aparece em tres horas do dia. Um roteiro que comparasse datas passaria nas
outras vinte e uma e daria a impressao de que o codigo esta certo. Entao
este roteiro **le o codigo-fonte** e proibe as chamadas que perguntam ao
processo.

**Por que varre tudo, e nao uma lista.** A versao anterior desta
verificacao vivia em `check_dinheiro.py`, procurava so `date.today()` e so
em seis arquivos escritos a mao. Quinze ocorrencias de
`timezone.now().date()` passaram por baixo dela, inclusive as nove da
agenda -- a tela em que o usuario viu o defeito. Lista escrita a mao nao
cobre o arquivo que ninguem lembrou de acrescentar, e o esquecimento e o
caso comum, nao a excecao.

A funcao certa e `django.utils.timezone.localdate()`, que converte para o
fuso do produto antes de tirar a data.
"""
import re
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:60} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


print('\n1. O produto esta no fuso da clinica')
conferir('TIME_ZONE', dj_settings.TIME_ZONE, 'America/Sao_Paulo')
conferir('USE_TZ ligado', dj_settings.USE_TZ, True)
conferir('o Celery segue o mesmo fuso',
         getattr(dj_settings, 'CELERY_TIMEZONE', None), 'America/Sao_Paulo')

print('\n2. `localdate()` e `now().date()` nao sao a mesma coisa')
# Prova deterministica, que vale em qualquer hora do dia: tres fusos
# cobrindo 25 horas nao podem concordar sobre que dia e hoje. Se
# concordassem, `localdate()` estaria ignorando o fuso -- que e exatamente
# o defeito que este roteiro existe para impedir.
em_utc = timezone.now().date()
with timezone.override('Pacific/Kiritimati'):          # UTC+14
    adiantado = timezone.localdate()
with timezone.override('Pacific/Midway'):              # UTC-11
    atrasado = timezone.localdate()
print(f'      UTC={em_utc}  UTC+14={adiantado}  UTC-11={atrasado}')
conferir('os tres fusos nao concordam sobre o dia',
         len({em_utc, adiantado, atrasado}) > 1, True)
conferir('e localdate() respeita o fuso pedido', adiantado >= atrasado, True)

print('\n3. Nenhum codigo pergunta o dia ao relogio do processo')
# `timezone.now()` devolve o instante em UTC; `.date()` nele devolve o dia
# em UTC. `date.today()` e `datetime.now()` leem o relogio do conteiner,
# que tambem e UTC.
PROIBIDAS = [
    (r'timezone\.now\(\)\.date\(\)', 'timezone.now().date()'),
    (r'(?<![\w.])date\.today\(\)', 'date.today()'),
    (r'datetime\.date\.today\(\)', 'datetime.date.today()'),
    (r'(?<![\w.])datetime\.now\(\)', 'datetime.now()'),
    (r'(?<![\w.])datetime\.today\(\)', 'datetime.today()'),
]

#: Pastas que nao servem requisicao nem tarefa, e cujo relogio nao decide
#: nada que o usuario veja.
FORA = {'.venv', 'migrations', 'node_modules', '.git', 'checks', 'site'}

raiz = Path(dj_settings.BASE_DIR)
achados = []
for arquivo in sorted(raiz.rglob('*.py')):
    if any(parte in FORA for parte in arquivo.parts):
        continue
    fonte = arquivo.read_text(encoding='utf-8')
    # Comentario e docstring podem citar a funcao proibida para explicar
    # por que ela e proibida -- e `finance/views.py` faz exatamente isso.
    codigo = re.sub(r'(?s)""".*?"""', '', fonte)
    codigo = re.sub(r"(?s)'''.*?'''", '', codigo)
    codigo = re.sub(r'(?m)^\s*#.*$', '', codigo)
    codigo = re.sub(r'(?m)\s+#.*$', '', codigo)
    for padrao, nome in PROIBIDAS:
        for linha_num, linha in enumerate(codigo.splitlines(), 1):
            if re.search(padrao, linha):
                achados.append(f'{arquivo.relative_to(raiz)}: {nome}')

for item in sorted(set(achados)):
    print(f'      {item}')
conferir('nenhuma chamada que ignora o fuso', len(achados), 0)

print('\n4. A agenda marca como hoje o dia da clinica')
# Lido do HTML, e nao do contexto: o `response.context` do cliente de teste
# so existe com a instrumentacao de teste ligada, e ligar isso aqui trocaria
# o backend de e-mail no meio de um roteiro que roda ao lado dos outros. O
# HTML e o que o usuario ve, que e a pergunta de qualquer forma.
from django.test import Client
from django.urls import reverse

from tenancy.models import Membership, MembershipStatus, Tenant

tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()
cliente = Client()
cliente.force_login(vinculo.user)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

hoje_da_clinica = timezone.localdate()
print(f'      hoje, para a clinica: {hoje_da_clinica}')
print(f'      hoje, em UTC        : {timezone.now().date()}')
if hoje_da_clinica != timezone.now().date():
    print('      (estamos na janela em que os dois discordam -- o defeito'
          ' aparecia AGORA)')

mes = cliente.get(reverse('scheduling:month')).content.decode()
# A celula de hoje e a unica com `bg-soft-primary` **na classe da celula**, e
# o link dentro dela carrega a data no rotulo de acessibilidade. A ancora e
# `nd-month-day` de proposito: um `bg-soft-primary` solto casaria com o
# primeiro cracha da pagina e leria a data da celula errada -- foi o que
# aconteceu na primeira versao deste roteiro, que acusou falha onde nao
# havia.
celulas = [
    m for m in re.finditer(r'nd-month-day[^"]*"', mes)
    if 'bg-soft-primary' in m.group(0)
]
conferir('exatamente uma celula marcada como hoje', len(celulas), 1)
if celulas:
    from datetime import datetime as _dt

    # 800 e nao 400: desde a 1.13 o numero do dia divide a linha com o
    # botao "Incluir horario", num `<div>` a mais antes do link.
    trecho = mes[celulas[0].start():celulas[0].start() + 800]
    rotulo = re.search(r'aria-label="Abrir a semana de (\d{2}/\d{2}/\d{4})"', trecho)
    conferir('a celula marcada diz que dia e', rotulo is not None, True)
    if rotulo:
        marcado = _dt.strptime(rotulo.group(1), '%d/%m/%Y').date()
        conferir('e o dia marcado e o da clinica', marcado, hoje_da_clinica)

# O botao "Hoje" do balcao leva para a data que o servidor considera hoje.
balcao = cliente.get(reverse('scheduling:desk')).content.decode()
botao = re.search(r"\?date=(\d{4}-\d{2}-\d{2})'?\">Hoje", balcao) or \
    re.search(r'\?date=(\d{4}-\d{2}-\d{2})">\s*Hoje', balcao)
if botao:
    from datetime import date as _date

    conferir('o botao "Hoje" do balcao aponta para o dia da clinica',
             _date.fromisoformat(botao.group(1)), hoje_da_clinica)

print('\n5. A fila de retornos conta o atraso pelo dia da clinica')
fila = cliente.get(reverse('scheduling:returns'))
conferir('a tela abre', fila.status_code, 200)

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o dia que o produto enxerga e o da clinica, e nenhum codigo')
print('    pergunta a data ao relogio do processo.')
