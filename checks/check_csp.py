"""Politica de conteudo: o cabecalho, o nonce e o que sobrou inline.

CSP e a defesa que so vale se ninguem a contornar por comodidade. Uma
diretiva `unsafe-inline` acrescentada num aperto desliga a protecao inteira
sem quebrar tela nenhuma -- e por isso ninguem percebe.

O que este roteiro cobra, e onde da errado:

- **`script-src` sem `unsafe-inline`.** E a diretiva que justifica o
  trabalho. Sem ela, todo o resto e decoracao;
- **o nonce e imprevisivel e muda a cada resposta.** Nonce fixo e o mesmo
  que `unsafe-inline` com passo extra: o atacante le o nonce da pagina e
  usa;
- **nenhum atributo de evento sobrou no HTML.** `onclick` nao e coberto
  por nonce. Um unico que volte obriga quem for aplicar a politica a
  afrouxar `script-src`, e ai acabou;
- **todo `<script>` inline carrega o nonce**, senao a politica aplicada
  apaga a tela em silencio;
- **comeca em modo de relatorio.** Aplicar de saida quebra longe e sem
  aviso;
- **o coletor aceita o que o navegador manda** -- sem sessao e sem CSRF,
  que e como o navegador manda -- e nao vira canal de entupir o log;
- **a politica nao vai em resposta que nao e HTML.**
"""
import json
import re

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse

from base.csp import montar_politica
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []

RELATORIO = 'Content-Security-Policy-Report-Only'
APLICADA = 'Content-Security-Policy'


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:60} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


def diretivas(politica):
    saida = {}
    for pedaco in politica.split(';'):
        partes = pedaco.strip().split(' ', 1)
        if partes:
            saida[partes[0]] = partes[1] if len(partes) > 1 else ''
    return saida


print('\n1. As diretivas que importam')
politica = montar_politica('NONCE-DE-TESTE')
d = diretivas(politica)

# A assercao central deste roteiro.
conferir("script-src nao permite 'unsafe-inline'",
         "'unsafe-inline'" in d.get('script-src', ''), False)
conferir("script-src nao permite 'unsafe-eval'",
         "'unsafe-eval'" in d.get('script-src', ''), False)
conferir('script-src carrega o nonce',
         "'nonce-NONCE-DE-TESTE'" in d.get('script-src', ''), True)
conferir("script-src nao abre para '*'", '*' in d.get('script-src', ''), False)
conferir("default-src e 'self'", d.get('default-src'), "'self'")
conferir("object-src e 'none'", d.get('object-src'), "'none'")
conferir("base-uri e 'self'", d.get('base-uri'), "'self'")
conferir("form-action e 'self'", d.get('form-action'), "'self'")
conferir("frame-ancestors e 'none'", d.get('frame-ancestors'), "'none'")
conferir('upgrade-insecure-requests esta presente',
         'upgrade-insecure-requests' in d, True)
# A concessao consciente, que a documentacao explica. A assercao existe
# para que ela continue sendo uma escolha, e nao um esquecimento.
conferir("style-src concede 'unsafe-inline' (escolha declarada)",
         "'unsafe-inline'" in d.get('style-src', ''), True)
conferir('e nenhuma origem externa entrou na politica',
         'http://' in politica or 'https://' in politica, False)

print('\n2. O nonce: imprevisivel e novo a cada resposta')
cliente = Client()
vistos = set()
for _ in range(5):
    cabecalho = cliente.get('/').get(RELATORIO) or ''
    achado = re.search(r"'nonce-([^']+)'", cabecalho)
    if achado:
        vistos.add(achado.group(1))
conferir('cinco respostas, cinco nonces diferentes', len(vistos), 5)
conferir('e cada um tem entropia suficiente',
         all(len(n) >= 16 for n in vistos), True)

print('\n3. Comeca em modo de relatorio')
resposta = cliente.get('/')
conferir('a pagina publica traz o cabecalho de relatorio',
         RELATORIO in resposta, True)
conferir('e nao o aplicado, enquanto CSP_ENFORCE for falso',
         APLICADA in resposta, dj_settings.CSP_ENFORCE)
conferir('CSP_ENFORCE nasce desligado', dj_settings.CSP_ENFORCE, False)

print('\n4. Nenhum atributo de evento sobrou no HTML')
# Varre os templates de verdade, e nao o que foi renderizado: um `onclick`
# num canto que nenhuma assercao abre continuaria la, e apareceria no dia
# em que a politica fosse aplicada.
from pathlib import Path

raiz = Path(dj_settings.BASE_DIR) / 'templates'
padrao = re.compile(r'\son[a-z]+\s*=\s*"', re.IGNORECASE)
sobraram = []
for arquivo in raiz.rglob('*.html'):
    for numero, linha in enumerate(arquivo.read_text(encoding='utf-8').splitlines(), 1):
        for achado in padrao.finditer(linha):
            # `only` e outros atributos legitimos que comecam com "on" nao
            # existem em HTML; o filtro e o proprio padrao.
            trecho = achado.group(0).strip()
            if trecho.lower().startswith('on'):
                sobraram.append(f'{arquivo.relative_to(raiz)}:{numero} {trecho}')
for item in sobraram:
    print(f'      {item}')
conferir('nenhum manipulador inline nos templates', len(sobraram), 0)

print('\n5. Todo <script> inline carrega o nonce')
sem_nonce = []
for arquivo in raiz.rglob('*.html'):
    texto = arquivo.read_text(encoding='utf-8')
    for achado in re.finditer(r'<script(?![^>]*\ssrc=)([^>]*)>', texto):
        if 'nonce' not in achado.group(1):
            sem_nonce.append(f'{arquivo.relative_to(raiz)}: {achado.group(0)[:60]}')
for item in sem_nonce:
    print(f'      {item}')
conferir('nenhum bloco inline sem nonce', len(sem_nonce), 0)

print('\n6. O nonce do cabecalho e o do HTML sao o mesmo')
# Se divergirem, a politica aplicada apaga o script da tela sem uma
# mensagem sequer -- e a tela que falha e a que ninguem abriu ainda.
tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()
logado = Client()
logado.force_login(vinculo.user)
sessao = logado.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

pagina = logado.get(reverse('scheduling:settings'))
do_cabecalho = re.search(r"'nonce-([^']+)'", pagina.get(RELATORIO) or '')
do_html = re.search(r'<script nonce="([^"]+)"', pagina.content.decode())
conferir('a tela tem bloco inline com nonce', do_html is not None, True)
if do_html and do_cabecalho:
    conferir('e ele bate com o do cabecalho',
             do_html.group(1), do_cabecalho.group(1))

print('\n7. A politica nao vai em resposta que nao e HTML')
json_resposta = logado.get(reverse('clinical:cid-lookup'), {'q': 'G40'})
conferir('a busca de CID responde JSON',
         json_resposta['Content-Type'].startswith('application/json'), True)
conferir('e sem cabecalho de politica', RELATORIO in json_resposta, False)

print('\n8. O coletor de relatorios')
url = reverse('csp-report')
anonimo = Client()
valido = json.dumps({'csp-report': {
    'violated-directive': "script-src 'self'",
    'blocked-uri': 'inline',
    'document-uri': 'https://neurodoc.app.br/app/',
}})
resposta = anonimo.post(url, data=valido, content_type='application/csp-report')
conferir('aceita sem sessao e sem CSRF (que e como o navegador manda)',
         resposta.status_code, 204)
conferir('corpo que nao e JSON e recusado',
         anonimo.post(url, data=b'nao e json',
                      content_type='application/csp-report').status_code, 403)
conferir('JSON sem o envelope csp-report e recusado',
         anonimo.post(url, data=json.dumps({'oi': 1}),
                      content_type='application/csp-report').status_code, 403)

# Entupir o log e o risco de um endereco aberto. O teto tem de existir.
from base.csp_views import LIMITE_POR_IP

excedeu = False
for _ in range(LIMITE_POR_IP + 6):
    if anonimo.post(url, data=valido,
                    content_type='application/csp-report').status_code == 429:
        excedeu = True
        break
conferir(f'acima de {LIMITE_POR_IP} por minuto, para de aceitar', excedeu, True)

print('\n9. As telas continuam de pe com os data-nd-*')
from django.core.cache import cache

cache.clear()
for nome, endereco in [
    ('agenda', reverse('scheduling:week')),
    ('retornos', reverse('scheduling:returns')),
    ('configurar horarios', reverse('scheduling:settings')),
]:
    conferir(f'{nome} responde', logado.get(endereco).status_code, 200)

grade = logado.get(reverse('scheduling:settings')).content.decode()
conferir('o seletor que envia sozinho virou data-nd-autosubmit',
         'data-nd-autosubmit' in grade, True)
conferir('e o script que o faz funcionar esta na pagina',
         'nd-inline.js' in grade, True)
conferir('o <noscript> continua oferecendo o botao',
         '<noscript>' in logado.get(reverse('scheduling:week')).content.decode(), True)

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: script-src fechado, nonce novo a cada resposta, nenhum manipulador')
print('    inline sobrando, e a politica comeca so relatando.')
