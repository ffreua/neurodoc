"""O aplicativo instalado (PWA), Etapa 1 (2026-11-27, `base/pwa.py`).

O que se cobra, e o que tentaria quebrar:

- `/app/` (o `start_url` do manifesto) leva à tela inicial de **cada papel**,
  e nao a um 404 depois do login; sem sessao, ao login; sem organizacao, ao
  seletor;
- o manifesto tem identidade fixa e atalhos que **todo papel** abre;
- `/sw.js` e servido da raiz, sem cache, e o worker so trata navegacao `GET`
  de `/app/` e `/accounts/`, so guarda a pagina `/offline/` e so a mostra na
  falha de rede (nada de `cache.put`, nada de guardar tela do sistema);
- o botao de emergencia (`PWA_SERVICE_WORKER=False`) serve um worker que se
  apaga e tira o registro das paginas;
- `/offline/` abre sem login, sem script e sem nada externo, `noindex`;
- as telas da equipe registram o worker e declaram o manifesto; as do
  **paciente** (portal, link `/d/`, verificacao, termo) nao fazem nenhum dos
  dois; a vitrine continua com o manifesto, sem o worker;
- o artigo de ajuda abre, esta no sitemap e no menu de todo papel, com o
  convite que some dentro do app instalado.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import json
import re

from django.test import Client

from base import pwa
from base.version import VERSION
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')


def vinculo(papel):
    return Membership.objects.filter(
        tenant=clinica, roles__contains=[papel], status=MembershipStatus.ACTIVE,
    ).select_related('user').first()


def logado(m):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(clinica.id)
    s.save()
    return c


papeis = {}
for papel in (Role.DOCTOR, Role.SECRETARY, Role.OWNER, Role.MANAGER):
    m = vinculo(papel)
    if m is not None:
        papeis[papel] = m
anonimo = Client()

print('\n1. /app/ leva a tela inicial, e nao a um 404')
r = anonimo.get('/app/')
confere(r.status_code == 302 and '/accounts/login/' in r['Location'], 'sem sessao: ao login')
for papel, m in papeis.items():
    c = logado(m)
    r = c.get('/app/')
    confere(r.status_code == 302 and r['Location'] == '/app/reporting/',
            f'{papel}: /app/ redireciona ao painel ({r.status_code} {r.get("Location")})')
    # O painel manda cada papel a sua tela inicial (a secretaria ao balcao,
    # `HomeRedirectMixin`); `/app/` passa por ele e herda a regra.
    r = c.get('/app/', follow=True)
    destino = r.redirect_chain[-1][0] if r.redirect_chain else '/app/'
    confere(r.status_code == 200, f'{papel}: seguindo, a tela inicial abre ({destino})')
sem_org = Client()
sem_org.force_login(papeis[Role.DOCTOR].user)
r = sem_org.get('/app/')
confere(r.status_code == 302 and 'select-organization' in r['Location'],
        'sem organizacao escolhida: ao seletor')

print('\n2. O manifesto')
r = anonimo.get('/site.webmanifest')
dados = json.loads(r.content.decode())
confere(dados.get('id') == '/app/' and dados.get('start_url') == '/app/', 'id e start_url em /app/')
confere(dados.get('display') == 'standalone', 'abre em tela cheia')
atalhos = dados.get('shortcuts') or []
confere([a['url'] for a in atalhos] == ['/app/scheduling/', '/app/patients/'], 'atalhos Agenda e Pacientes')
for papel, m in papeis.items():
    c = logado(m)
    for a in atalhos:
        st = c.get(a['url']).status_code
        confere(st == 200, f'{papel}: o atalho {a["name"]} abre ({st})')

print('\n3. /sw.js')
r = anonimo.get('/sw.js')
corpo = r.content.decode()
confere(r.status_code == 200, 'responde 200 sem login')
confere(r['Content-Type'].startswith('application/javascript'), 'como JavaScript')
confere(r.get('Cache-Control') == 'no-cache', 'sem prazo de cache (e por ele que a versao nova chega)')
confere("'/offline/'" in corpo and '["/app/", "/accounts/"]' in corpo, 'a pagina offline e as duas areas')
confere("pedido.mode !== 'navigate' || pedido.method !== 'GET'" in corpo, 'so navegacao GET')
confere(corpo.count('cache.add(') == 1 and 'cache.put' not in corpo and 'caches.open' in corpo,
        'guarda uma coisa so, e nunca uma resposta do sistema')
confere('fetch(pedido).catch(' in corpo, 'a pagina offline so na falha de rede')
confere(VERSION in corpo, 'o nome do cache carrega a versao')
confere('unregister' not in corpo, 'o worker normal nao se desregistra')

print('\n4. O botao de emergencia')
original = dj_settings.PWA_SERVICE_WORKER
dj_settings.PWA_SERVICE_WORKER = False
try:
    corpo_off = anonimo.get('/sw.js').content.decode()
    confere('unregister()' in corpo_off and "addEventListener('fetch'" not in corpo_off,
            'desligado: o worker se apaga e nao intercepta nada')
    html = logado(papeis[Role.DOCTOR]).get('/app/patients/').content.decode()
    confere('nd-pwa.js' not in html, 'desligado: a tela nao registra o worker')
    confere('rel="manifest"' in html, 'desligado: o manifesto continua (instalar nao depende do worker)')
finally:
    dj_settings.PWA_SERVICE_WORKER = original

print('\n5. /offline/')
r = anonimo.get('/offline/')
html = r.content.decode()
confere(r.status_code == 200, 'abre sem login')
confere('<script' not in html, 'sem script')
confere(not re.search(r'(src|href)="(https?:|/static/)', html), 'sem arquivo externo nem do tema')
confere('href=""' in html and 'Tentar de novo' in html, '"Tentar de novo" pede a mesma tela')
confere('Nenhum dado de paciente' in ' '.join(html.split()), 'diz que nada do paciente fica no aparelho')
confere(r.get('X-Robots-Tag') == 'noindex, nofollow', 'fora da busca')
confere('Disallow: /offline/' in anonimo.get('/robots.txt').content.decode(), 'e no robots.txt')

print('\n6. Telas da equipe, do paciente e a vitrine')
for papel, m in papeis.items():
    html = logado(m).get('/app/patients/').content.decode()
    confere('nd-pwa.js' in html and 'rel="manifest"' in html, f'{papel}: worker e manifesto no app')
    confere('instalar-app' in html and 'data-nd-so-navegador' in html, f'{papel}: "Instalar o app" no menu')
login = anonimo.get('/accounts/login/').content.decode()
confere('nd-pwa.js' in login and 'rel="manifest"' in login, 'login: worker e manifesto')
confere('/ajuda/instalar-app/' in login, 'login: o convite a instalar')
vitrine = anonimo.get('/').content.decode()
confere('rel="manifest"' in vitrine and 'nd-pwa.js' not in vitrine, 'vitrine: manifesto, sem worker')
for caminho in ('/verificar/', '/termo-teleconsulta/', '/d/token-inexistente/'):
    r = anonimo.get(caminho)
    html = r.content.decode('utf-8', 'replace')
    confere('rel="manifest"' not in html and 'nd-pwa.js' not in html,
            f'{caminho} ({r.status_code}): nao se oferece como app da equipe')
for caminho in ('/d/x/', '/solicitacoes/x/', '/verificar/', '/descadastrar/x/', '/c/x/',
                '/termo-teleconsulta/'):
    confere(not pwa.instalavel(caminho), f'instalavel({caminho}) e falso')
for caminho in ('/app/', '/accounts/login/', '/', '/ajuda/'):
    confere(pwa.instalavel(caminho), f'instalavel({caminho}) e verdadeiro')

print('\n7. O artigo de ajuda')
r = anonimo.get('/ajuda/instalar-app/')
html = r.content.decode()
confere(r.status_code == 200, 'abre sem login')
confere('data-nd-instalar' in html and 'nd-instalar.js' in html, 'com o bloco "Instalar agora"')
confere('Adicionar à Tela de Início' in html and 'Instalar app' in html, 'com os passos do iPhone e do Android')
botao = re.search(r'<button[^>]*data-nd-instalar-botao[^>]*>', html)
confere(botao is not None and 'hidden' in botao.group(0), 'o botao nasce escondido')
confere('/ajuda/instalar-app/' in anonimo.get('/sitemap.xml').content.decode(), 'no sitemap')
outro = anonimo.get('/ajuda/primeiros-passos/').content.decode()
confere('nd-instalar.js' not in outro, 'o bloco so no artigo de instalar')
css = open(dj_settings.BASE_DIR / 'static' / 'duralux' / 'neurodoc.css', encoding='utf-8').read()
confere(re.search(r'@media \(display-mode: standalone\)\s*\{\s*\[data-nd-so-navegador\]', css) is not None,
        'o convite some dentro do app instalado')

print()
if falhas:
    print(f'FALHAS ({len(falhas)}):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('Tudo certo.')
