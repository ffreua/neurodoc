"""O aplicativo instalado (PWA): o service worker e a tela sem internet.

**O mesmo arquivo nos dois produtos** (NeuroDoc e ProntDoc), salvo o nome e
a cor em `PRODUTO` e `COR`. Decisões em `docs/homologation/pwa.md`.

O que o worker faz, e é tudo: quando uma tela de `/app/` ou `/accounts/`
não abre **porque a rede caiu**, ele mostra a página `/offline/` em vez do
dinossauro do navegador. Nada além disso, e cada recusa é deliberada:

- **não guarda nenhuma página do sistema.** Página de `/app/` carrega
  prontuário, e celular se perde, é roubado e é emprestado. O único item
  do cache é a própria `/offline/`, que não tem dado de ninguém;
- **não toca em `POST`**, nem em nada que não seja navegação: formulário,
  assinatura, envio de arquivo, o SSE do chat e o `fetch` das telas passam
  direto, como se o worker não existisse;
- **não toca em navegação fora de `/app/` e `/accounts/`.** O portal do
  paciente, o link `/d/`, a verificação do QR e a vitrine seguem o caminho
  de sempre, mesmo no navegador de quem instalou;
- **resposta de erro do servidor passa como veio.** Só a falha de rede (o
  `fetch` que rejeita) vira a tela sem internet — um 403 ou um 500 não
  podem se disfarçar de "sem conexão", senão o diagnóstico vai para o lugar
  errado.

O botão de emergência é `PWA_SERVICE_WORKER=False` (ver `core/settings.py`):
as páginas param de registrar o worker e `/sw.js` passa a servir um que se
apaga sozinho. Apagar o arquivo não bastaria — o worker já instalado num
celular continua lá até o navegador receber um substituto.
"""

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from .version import VERSION

PRODUTO = 'NeuroDoc'
#: O primário do tema, o mesmo do `theme_color` do manifesto.
COR = '#3454d1'

#: As áreas cujas telas ganham a tela sem internet. Só as da equipe.
AREAS = ('/app/', '/accounts/')

#: Endereços que o **paciente** (ou a farmácia) abre. Neles a página não se
#: oferece como aplicativo da equipe: o paciente que adicionasse o portal à
#: tela inicial ganharia um ícone que abre o login da clínica.
PREFIXOS_DO_PACIENTE = (
    '/d/', '/solicitacoes/', '/verificar/', '/descadastrar/', '/c/',
    '/termo-teleconsulta/',
)


def instalavel(caminho):
    """A página se oferece como o aplicativo da equipe?"""
    return not caminho.startswith(PREFIXOS_DO_PACIENTE)


def worker_ligado():
    return bool(getattr(settings, 'PWA_SERVICE_WORKER', True))


def _nome_do_cache():
    # A versão do produto **e** o build: a página offline muda de texto entre
    # versões, e o build garante que cada publicação troque o cache sem
    # depender de alguém lembrar de subir a versão.
    return '%s-offline-%s-%s' % (PRODUTO.lower(), VERSION,
                                 getattr(settings, 'RELEASE_ID', 'dev'))


_WORKER = """'use strict';
/* %(produto)s — service worker. Ver base/pwa.py: o único item guardado é a
 * página /offline/, e nenhuma tela do sistema passa a ser guardada. */
var CACHE = '%(cache)s';
var OFFLINE = '/offline/';
var AREAS = %(areas)s;
var PREFIXO = '%(prefixo)s-offline-';

self.addEventListener('install', function (evento) {
    evento.waitUntil(
        caches.open(CACHE)
            .then(function (cache) { return cache.add(new Request(OFFLINE, {cache: 'reload'})); })
            .then(function () { return self.skipWaiting(); })
    );
});

self.addEventListener('activate', function (evento) {
    evento.waitUntil(
        caches.keys().then(function (nomes) {
            return Promise.all(nomes.filter(function (nome) {
                return nome.indexOf(PREFIXO) === 0 && nome !== CACHE;
            }).map(function (nome) { return caches.delete(nome); }));
        }).then(function () { return self.clients.claim(); })
    );
});

self.addEventListener('fetch', function (evento) {
    var pedido = evento.request;
    if (pedido.mode !== 'navigate' || pedido.method !== 'GET') { return; }
    var url = new URL(pedido.url);
    if (url.origin !== self.location.origin) { return; }
    var naArea = AREAS.some(function (area) { return url.pathname.indexOf(area) === 0; });
    if (!naArea) { return; }
    evento.respondWith(
        fetch(pedido).catch(function () {
            return caches.match(OFFLINE).then(function (guardada) {
                return guardada || Response.error();
            });
        })
    );
});
"""

#: O substituto do botão de emergência: instala, apaga o próprio cache e se
#: desregistra. Sem `fetch`, então nada passa por ele enquanto isso.
_WORKER_QUE_SE_APAGA = """'use strict';
/* %(produto)s — service worker desligado (PWA_SERVICE_WORKER=False). */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (evento) {
    evento.waitUntil(
        caches.keys().then(function (nomes) {
            return Promise.all(nomes.filter(function (nome) {
                return nome.indexOf('%(prefixo)s-offline-') === 0;
            }).map(function (nome) { return caches.delete(nome); }));
        }).then(function () { return self.registration.unregister(); })
    );
});
"""


class ServiceWorkerView(View):
    """`/sw.js`, na raiz: o escopo de um worker é a pasta de onde ele vem.

    `no-cache` porque é por este arquivo que o navegador descobre uma versão
    nova (e o desligamento); com prazo de cache, o worker antigo ficaria
    valendo até o prazo vencer.
    """

    def get(self, request):
        import json

        dados = {'produto': PRODUTO, 'prefixo': PRODUTO.lower(),
                 'cache': _nome_do_cache(), 'areas': json.dumps(list(AREAS))}
        modelo = _WORKER if worker_ligado() else _WORKER_QUE_SE_APAGA
        return HttpResponse(modelo % dados,
                            content_type='application/javascript; charset=utf-8',
                            headers={'Cache-Control': 'no-cache'})


class OfflineView(View):
    """`/offline/`: o que o worker mostra quando a rede cai.

    Página **sem script e sem nada externo**: ela vai para o cache uma vez e
    é mostrada justamente quando nada mais carrega. O estilo vai no próprio
    HTML (a política de conteúdo permite estilo embutido; script, não).
    """

    def get(self, request):
        resposta = render(request, 'base/offline.html', {'produto': PRODUTO, 'cor': COR})
        resposta['Cache-Control'] = 'no-cache'
        return resposta
