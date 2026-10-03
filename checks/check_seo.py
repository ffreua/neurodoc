"""O que o Google e o navegador veem antes de qualquer pessoa ver.

Este roteiro existe porque o defeito que ele cobre ficou no ar a vida
inteira do produto sem ninguem notar: `partials/head.html` entra por
`{% include %}`, o `<title>` morava la dentro de um `{% block %}`, e bloco
nao atravessa include. Toda pagina servia `<title>NeuroDoc</title>` --
inclusive a de vendas, que declarava o proprio titulo tres linhas acima.
Nada quebra, nada aparece no log, e o sintoma so existe no resultado de
busca e na aba do navegador, que sao justamente os dois lugares onde
ninguem olha ao conferir uma tela.

O que este roteiro cobra, e onde da errado:

- **o titulo da pagina de vendas e o do catalogo**, e nao a palavra
  "NeuroDoc" sozinha. E a assercao que teria pego o defeito acima;
- **o titulo que o template declara chega a pagina.** Uma tela de dentro
  de `/app/` tem de mostrar o proprio, senao o conserto foi so na raiz;
- **toda pagina que nao esta em `base/seo.PAGINAS` sai `noindex`.** A
  lista e de permissao: rota nova nasce privada. Conferido na tela de
  entrada, numa rota de dentro de `/app/` e na verificacao por token --
  esta ultima mostra tipo de documento, medico e data;
- **o sitemap e o `robots` nao se contradizem.** Toda URL listada no
  `sitemap.xml` responde 200 **e** sai `index`. Um sitemap que anuncia
  pagina `noindex` e o erro classico, e o Search Console so o reporta
  semanas depois;
- **a canonica e absoluta e vem de `PUBLIC_BASE_URL`**, nunca do `Host:`
  da requisicao -- que e um cabecalho do cliente, e com ele um pedido
  forjado faria a pagina declarar que o original esta noutro dominio;
- **o `robots.txt` deixa passar `/verificar/` e barra `/verificar/<token>/`**
  -- `Allow` com `$` **antes** do `Disallow` da pasta, nessa ordem;
- **o JSON-LD e JSON valido, carrega o nonce e nao inventa numero.** O
  preco de cada oferta tem de bater com `tenancy.plans`, e a quantidade
  de perguntas com `base.content.FAQ`. Sem o nonce, `script-src` descarta
  o bloco inteiro em silencio;
- **`</script>` dentro de qualquer texto do catalogo nao fecha o bloco**;
- **os icones respondem na raiz**, com os bytes certos: o `.ico` e um ICO
  de verdade e o cartao do Open Graph mede 1200x630 -- o tamanho que o
  WhatsApp e o LinkedIn esperam;
- **a pagina diz que serve a outras especialidades**, com a ressalva de
  que nao ha roteiro de exame fora da neurologia. E a secao que impede um
  ortopedista de ir embora na primeira tela -- e a ressalva e o que a
  torna verdadeira.
"""
import json
import re
import struct

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.test import Client
from django.urls import reverse

from base import seo
from base.content import ESPECIALIDADES, FAQ
from base.help_content import ARTICLES
from tenancy.models import Membership, MembershipStatus, Tenant
from tenancy.plans import MESES_NO_ANO, PLANS, PUBLIC_ORDER

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


def titulo_de(html):
    achado = re.search(r'<title>(.*?)</title>', html, re.S)
    return achado.group(1).strip() if achado else ''


def meta(html, nome):
    achado = re.search(r'<meta name="%s" content="([^"]*)"' % nome, html)
    return achado.group(1) if achado else ''


def canonica_de(html):
    achado = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    return achado.group(1) if achado else ''


def jsonld_de(html):
    achado = re.search(
        r'<script type="application/ld\+json" nonce="([^"]*)">(.*?)</script>',
        html, re.S)
    if achado is None:
        return '', None
    try:
        return achado.group(1), json.loads(achado.group(2))
    except ValueError as erro:                              # noqa: BLE001
        return achado.group(1), {'erro': str(erro)}


anonimo = Client()

print('\n1. O titulo chega a pagina (o defeito do include)')
home = anonimo.get('/')
conferir('a raiz responde', home.status_code, 200)
html = home.content.decode()
conferir('o titulo da raiz e o do catalogo',
         titulo_de(html), seo.PAGINAS['onboarding:landing'].titulo)
conferir('e nao a palavra solta que o include servia', titulo_de(html) == 'NeuroDoc', False)
conferir('o titulo cabe no resultado de busca (<= 65)',
         len(titulo_de(html)) <= 65, True)

login = anonimo.get(reverse('accounts:login'))
conferir('a tela de entrada mostra o titulo que ela declara',
         titulo_de(login.content.decode()), 'Entrar — NeuroDoc')

print('\n2. A lista e de permissao: o que nao esta no catalogo sai noindex')
conferir('a raiz e indexavel', meta(html, 'robots'), seo.INDEXAVEL)
conferir('a tela de entrada nao', meta(login.content.decode(), 'robots'), seo.OCULTO)

verificar = anonimo.get('/verificar/')
conferir('o formulario de verificacao em branco e indexavel',
         meta(verificar.content.decode(), 'robots'), seo.INDEXAVEL)
por_token = anonimo.get('/verificar/NAO-EXISTE-ESTE-TOKEN/')
conferir('a verificacao por token nao',
         meta(por_token.content.decode(), 'robots'), seo.OCULTO)
conferir('e o titulo dela continua escrito, sem catalogo',
         titulo_de(por_token.content.decode()),
         'Verificação de documento médico — NeuroDoc')

# Uma tela de dentro de `/app/`, com sessao: e o caso que mais importa, e
# o unico que o anonimo nao alcanca.
tenant = Tenant.objects.filter(slug='demo-clinica-a').first()
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first() if tenant else None
if vinculo is None:
    falhas.append('sem vinculo de medico na clinica de demonstracao; rode seed_demo')
    print('  FALHA  sem vinculo de medico na clinica de demonstracao')
else:
    logado = Client()
    logado.force_login(vinculo.user)
    sessao = logado.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()
    pacientes = logado.get(reverse('patients:list'))
    conferir('a lista de pacientes responde', pacientes.status_code, 200)
    dentro = pacientes.content.decode()
    conferir('e sai noindex', meta(dentro, 'robots'), seo.OCULTO)
    conferir('e sem canonica', canonica_de(dentro), '')
    conferir('e sem cartao de compartilhamento',
             'og:title' in dentro, False)
    conferir('mas com o titulo que o template declara',
             titulo_de(dentro) not in ('', 'NeuroDoc'), True)

print('\n3. robots.txt')
robots = anonimo.get('/robots.txt')
conferir('responde', robots.status_code, 200)
conferir('como texto', robots['Content-Type'].split(';')[0], 'text/plain')
texto = robots.content.decode()
for linha in ('Disallow: /app/', 'Disallow: /accounts/', 'Disallow: /instalacao/',
              'Disallow: /d/', 'Disallow: /solicitacoes/', 'Disallow: /admin/'):
    conferir('barra %s' % linha.split(': ')[1], linha in texto.splitlines(), True)
conferir('anuncia o sitemap absoluto',
         ('Sitemap: ' + seo.absoluta('/sitemap.xml')) in texto, True)
# A ordem importa: `Allow` especifico tem de vir antes do `Disallow` da
# pasta para o formulario em branco continuar rastreavel.
conferir('libera o formulario de verificacao antes de barrar a pasta',
         texto.index('Allow: /verificar/$') < texto.index('Disallow: /verificar/'), True)

print('\n4. sitemap.xml nao contradiz o robots de cada pagina')
mapa = anonimo.get('/sitemap.xml')
conferir('responde', mapa.status_code, 200)
conferir('como XML', mapa['Content-Type'].split(';')[0], 'application/xml')
xml = mapa.content.decode()
locais = re.findall(r'<loc>([^<]+)</loc>', xml)
conferir('lista a raiz, a ajuda, as perguntas, o contrato e a verificacao',
         len(locais) >= 5 + len(ARTICLES), True)
conferir('um <url> para cada <loc>', xml.count('<url>'), len(locais))
raiz_absoluta = seo.absoluta('/')
conferir('todo endereco e absoluto e do dominio configurado',
         all(endereco.startswith(raiz_absoluta) for endereco in locais), True)
conferir('todo artigo do manual esta listado',
         all(seo.absoluta('/ajuda/%s/' % a['slug']) in locais for a in ARTICLES), True)
conferir('nenhum endereco repetido', len(set(locais)), len(locais))

prefixo = len(seo.absoluta(''))
problemas = []
for endereco in locais:
    caminho = endereco[prefixo:]
    resposta = anonimo.get(caminho)
    if resposta.status_code != 200:
        problemas.append('%s -> %s' % (caminho, resposta.status_code))
        continue
    corpo = resposta.content.decode()
    if meta(corpo, 'robots') != seo.INDEXAVEL:
        problemas.append('%s -> noindex' % caminho)
    elif canonica_de(corpo) != endereco:
        problemas.append('%s -> canonica %s' % (caminho, canonica_de(corpo)))
conferir('toda URL do sitemap abre, sai index e aponta a si mesma', problemas, [])

print('\n5. Canonica e cartao de compartilhamento')
conferir('a canonica da raiz e absoluta', canonica_de(html), seo.absoluta('/'))
# `Host:` forjado nao pode mudar a canonica: ela sai de `PUBLIC_BASE_URL`.
forjado = Client(HTTP_HOST='testserver')
conferir('e nao segue o cabecalho Host do pedido',
         canonica_de(forjado.get('/').content.decode()), seo.absoluta('/'))
for propriedade in ('og:title', 'og:description', 'og:image', 'og:url', 'og:type'):
    conferir('a raiz declara %s' % propriedade,
             ('property="%s"' % propriedade) in html, True)
conferir('o cartao aponta para a imagem da raiz',
         ('content="%s"' % seo.absoluta('/og-image.png')) in html, True)
conferir('e pede o formato grande no Twitter/X',
         meta(html, 'twitter:card'), 'summary_large_image')

print('\n6. Descricao de cada pagina do catalogo')
curtas, longas, titulos = [], [], []
for pagina in seo.paginas_do_sitemap():
    if not 70 <= len(pagina.descricao) <= 175:
        (curtas if len(pagina.descricao) < 70 else longas).append(
            '%s (%d)' % (pagina.caminho, len(pagina.descricao)))
    if len(pagina.titulo) > 70:
        titulos.append('%s (%d)' % (pagina.caminho, len(pagina.titulo)))
conferir('nenhuma descricao curta demais para o resultado de busca', curtas, [])
conferir('nenhuma descricao longa demais (o Google corta)', longas, [])
conferir('nenhum titulo longo demais', titulos, [])
conferir('a descricao da raiz esta na pagina',
         meta(html, 'description'), seo.PAGINAS['onboarding:landing'].descricao)

print('\n7. Dados estruturados')
nonce, grafo = jsonld_de(html)
conferir('a raiz traz JSON-LD', grafo is not None, True)
conferir('com nonce (sem ele a CSP descarta o bloco em silencio)',
         bool(nonce), True)
conferir('e JSON valido', isinstance(grafo, dict) and 'erro' not in grafo, True)
tipos = {no.get('@type') for no in (grafo or {}).get('@graph', [])}
for tipo in ('WebSite', 'Organization', 'Person', 'SoftwareApplication', 'FAQPage'):
    conferir('declara %s' % tipo, tipo in tipos, True)

produto = next((n for n in grafo['@graph'] if n.get('@type') == 'SoftwareApplication'), {})
esperados = []
for code in PUBLIC_ORDER:
    centavos = PLANS[code].get('price_monthly')
    if centavos is None:
        continue
    reais, resto = divmod(centavos * MESES_NO_ANO, 100)
    esperados.append('%d.%02d' % (reais, resto))
conferir('o preco de cada oferta vem de tenancy.plans',
         [o['price'] for o in produto.get('offers', [])], esperados)
conferir('o Personalizado nao vira oferta sem preco',
         any(o['name'].endswith('Personalizado') for o in produto.get('offers', [])), False)
conferir('nenhuma nota de avaliacao inventada',
         'aggregateRating' in produto, False)

perguntas = next((n for n in grafo['@graph'] if n.get('@type') == 'FAQPage'), {})
conferir('o FAQ marcado tem o mesmo tamanho do FAQ da pagina',
         len(perguntas.get('mainEntity', [])), len(FAQ))
conferir('e a primeira pergunta e a mesma',
         perguntas['mainEntity'][0]['name'], FAQ[0]['pergunta'])

# O escape e o que impede um `</script>` escrito no catalogo de fechar o
# bloco no meio e jogar o resto do JSON na tela.
escapado = seo._para_script({'t': '</script><img onerror=x>'})
conferir('nenhum "<" cru sobrevive ao escape', '<' in escapado, False)
conferir('e o JSON continua lendo igual',
         json.loads(escapado)['t'], '</script><img onerror=x>')

artigo = anonimo.get('/ajuda/%s/' % ARTICLES[0]['slug'])
_, grafo_artigo = jsonld_de(artigo.content.decode())
tipos_artigo = {n.get('@type') for n in (grafo_artigo or {}).get('@graph', [])}
conferir('o artigo do manual traz trilha de navegacao',
         'BreadcrumbList' in tipos_artigo, True)
conferir('e se declara artigo tecnico assinado',
         'TechArticle' in tipos_artigo, True)
conferir('e o titulo dele sai do proprio manual',
         titulo_de(artigo.content.decode()),
         '%s | Ajuda do NeuroDoc' % ARTICLES[0]['title'])

print('\n8. Icones e manifesto, por caminho fixo da raiz')
favicon = anonimo.get('/favicon.ico')
conferir('/favicon.ico responde', favicon.status_code, 200)
bytes_ico = b''.join(favicon.streaming_content)
# Cabecalho de um ICO: reservado=0, tipo=1, e a contagem de imagens.
reservado, tipo, quantas = struct.unpack('<HHH', bytes_ico[:6])
conferir('e um ICO de verdade', (reservado, tipo), (0, 1))
conferir('com tres tamanhos dentro (16, 32, 48)', quantas, 3)

og = anonimo.get('/og-image.png')
conferir('/og-image.png responde', og.status_code, 200)
bytes_og = b''.join(og.streaming_content)
conferir('e um PNG', bytes_og[:8], b'\x89PNG\r\n\x1a\n')
largura, altura = struct.unpack('>II', bytes_og[16:24])
conferir('no tamanho que o WhatsApp e o LinkedIn esperam',
         (largura, altura), (1200, 630))

for caminho, tipo_esperado in (('/neurodoc-mark.svg', 'image/svg+xml'),
                               ('/apple-touch-icon.png', 'image/png'),
                               ('/icon-192.png', 'image/png'),
                               ('/icon-512.png', 'image/png'),
                               ('/icon-maskable-512.png', 'image/png')):
    resposta = anonimo.get(caminho)
    conferir('%s responde como %s' % (caminho, tipo_esperado),
             (resposta.status_code, resposta['Content-Type'].split(';')[0]),
             (200, tipo_esperado))

manifesto = anonimo.get('/site.webmanifest')
conferir('/site.webmanifest responde', manifesto.status_code, 200)
dados = json.loads(manifesto.content.decode())
conferir('declara os tres icones', len(dados['icons']), 3)
conferir('e um deles e recortavel pelo launcher do Android',
         any(i.get('purpose') == 'maskable' for i in dados['icons']), True)
conferir('o atalho instalado abre o aplicativo, nao a pagina de vendas',
         dados['start_url'], '/app/')
conferir('a pagina declara o manifesto', 'rel="manifest"' in html, True)
conferir('e o icone vetorial', 'href="/neurodoc-mark.svg"' in html, True)

print('\n9. A pagina responde "isto serve para a minha especialidade?"')
conferir('a secao existe', ESPECIALIDADES['titulo'] in html, True)
conferir('o selo do topo nao fecha a porta',
         'qualquer especialidade' in html.split('<h1')[0], True)
conferir('o H1 diz "prontuario eletronico" por extenso',
         'prontuário eletrônico' in re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S).group(1).lower(),
         True)
faltando = [t for t, _ in ESPECIALIDADES['comum'] if t not in html]
conferir('todo item do catalogo que serve a qualquer especialidade esta na pagina',
         faltando, [])
conferir('a ressalva tambem -- e ela e o que torna o resto crivel',
         ESPECIALIDADES['ressalva'][:60] in html, True)
conferir('a descricao do catalogo diz o mesmo',
         'qualquer especialidade' in seo.RESUMO, True)

print('\n10. Verificacao do Google Search Console')
tag = '<meta name="google-site-verification"'
if dj_settings.GOOGLE_SITE_VERIFICATION:
    conferir('o token configurado aparece na pagina',
             meta(html, 'google-site-verification'),
             dj_settings.GOOGLE_SITE_VERIFICATION)
else:
    conferir('sem token configurado, nenhuma tag vazia e emitida', tag in html, False)
    print('  (nota: GOOGLE_SITE_VERIFICATION vazio nesta instalacao)')

print()
if falhas:
    print('FALHAS (%d):' % len(falhas))
    for falha in falhas:
        print('  -', falha)
    raise SystemExit(1)
print('OK: titulo chegando a pagina, catalogo unico para robots e sitemap, '
      'dados estruturados conferidos contra o catalogo, icones na raiz.')
