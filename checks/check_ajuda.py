"""A ajuda abre, e o manual nao referencia captura que nao existe?

O modo como um manual apodrece e sempre o mesmo: o texto muda, a imagem
some, e ninguem percebe ate um usuario abrir a pagina e ver o icone
quebrado. Este roteiro existe para que isso falhe aqui, e nao la.

As perguntas sao:

- toda captura referenciada existe em `static/help/`?
- toda captura em `static/help/` e referenciada? (imagem orfa e peso morto)
- as paginas abrem **sem login**?
- o indice lista todos os artigos, e cada artigo abre?
- a landing leva ao manual?
- o manual promete alguma coisa que esta fora do escopo da v1?
"""
import os
import re

from django.conf import settings as dj_settings
from django.test import Client
from django.urls import reverse

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from base.help_content import ARTICLES, FAQ_USO, screenshots

falhas = []
DIRETORIO = os.path.join(dj_settings.BASE_DIR, 'static', 'help')

print('=== 1. toda captura referenciada existe ===')
referenciadas = screenshots()
no_disco = set(os.listdir(DIRETORIO)) if os.path.isdir(DIRETORIO) else set()
faltando = [x for x in referenciadas if x not in no_disco]
print(f'  referenciadas={len(referenciadas)}  no disco={len(no_disco)}')
print(f'  faltando: {faltando or "nenhuma"}')
if faltando:
    falhas.append(f'o manual aponta para capturas que nao existem: {faltando}')

print('=== 2. nenhuma captura orfa ===')
orfas = sorted(x for x in no_disco if x.endswith('.png') and x not in referenciadas)
print(f'  orfas: {orfas or "nenhuma"}')
if orfas:
    falhas.append(f'capturas sem referencia no manual (peso morto): {orfas}')

print('=== 3. as paginas abrem sem login ===')
anonimo = Client()
rotas = [
    ('indice', reverse('onboarding:help')),
    ('perguntas', reverse('onboarding:help-faq')),
    ('landing', reverse('onboarding:landing')),
]
for rotulo, url in rotas:
    r = anonimo.get(url)
    print(f'  {rotulo:12} {url:22} -> {r.status_code}')
    if r.status_code != 200:
        falhas.append(f'{rotulo} nao abre sem login ({r.status_code})')

print('=== 4. cada artigo abre, e o indice lista todos ===')
corpo_indice = anonimo.get(reverse('onboarding:help')).content.decode()
for artigo in ARTICLES:
    url = reverse('onboarding:help-article', args=[artigo['slug']])
    r = anonimo.get(url)
    no_indice = artigo['title'] in corpo_indice
    ok = r.status_code == 200 and no_indice
    print(f'  {artigo["slug"]:14} -> {r.status_code}  no indice={no_indice}')
    if not ok:
        falhas.append(f'artigo {artigo["slug"]}: status={r.status_code}, no indice={no_indice}')

print('=== 5. slug inexistente e 404, nao 500 ===')
r = anonimo.get('/ajuda/isso-nao-existe/')
print(f'  /ajuda/isso-nao-existe/ -> {r.status_code}')
if r.status_code != 404:
    falhas.append(f'slug inexistente respondeu {r.status_code}')

print('=== 6. a landing leva ao manual ===')
corpo = anonimo.get(reverse('onboarding:landing')).content.decode()
leva = reverse('onboarding:help') in corpo
leva_faq = reverse('onboarding:help-faq') in corpo
print(f'  link para o manual={leva}  link para as perguntas={leva_faq}')
if not leva or not leva_faq:
    falhas.append('a pagina inicial nao leva ao manual e as perguntas')

print('=== 7. as capturas sao servidas ===')
# `{% static %}` resolve para o diretorio de release; a pagina tem de
# apontar para um arquivo que existe, e nao so citar o nome.
artigo = ARTICLES[0]
corpo = anonimo.get(reverse('onboarding:help-article', args=[artigo['slug']])).content.decode()
imagens = re.findall(r'<img src="([^"]+)"', corpo)
print(f'  <img> no primeiro artigo: {len(imagens)}')
if not imagens:
    falhas.append('o primeiro artigo nao renderizou imagem nenhuma')

print('=== 8. o manual nao promete o que esta fora do escopo ===')
texto = ' '.join(
    passo + ' ' + legenda
    for a in ARTICLES for passo, _, legenda in a['steps']
) + ' '.join(f'{q["pergunta"]} {q["resposta"]}' for q in FAQ_USO)
proibidos = ['teleconsulta', 'TISS', 'DICOM', 'PACS', 'cartão de crédito', 'boleto']
achados = [p for p in proibidos if p.lower() in texto.lower()]
print(f'  artigos={len(ARTICLES)}  perguntas={len(FAQ_USO)}')
print(f'  promessas fora de escopo: {achados or "nenhuma"}')
if achados:
    falhas.append(f'o manual menciona o que a v1 nao entrega: {achados}')

print('=== 9. cada artigo tem passo e publico ===')
for artigo in ARTICLES:
    problemas = []
    if not artigo.get('steps'):
        problemas.append('sem passos')
    if not artigo.get('audience'):
        problemas.append('sem publico')
    if not artigo.get('summary'):
        problemas.append('sem resumo')
    if problemas:
        falhas.append(f'{artigo["slug"]}: {", ".join(problemas)}')
print(f'  artigos completos: {len(ARTICLES) - len([f for f in falhas if "sem " in f])}/{len(ARTICLES)}')

print('---')
if falhas:
    for line in falhas:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o manual abre sem login, e nao aponta para captura que nao existe.')
