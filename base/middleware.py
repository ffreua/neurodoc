from django.http import Http404

PANEL_PREFIXES = (
    '/admin/dj-control-room-base/',
    '/admin/dj-celery-panel/',
    '/admin/dj-control-room/',
)


class TechnicalPanelMFAMiddleware:
    """Adds an MFA requirement on top of dj-celery-panel/dj-control-room.

    Those packages already gate their own views on is_staff (and, once
    REQUIRE_SUPERUSER is set, is_superuser); they have no concept of MFA.
    Anonymous users are left alone here so their own decorator can redirect
    to the admin login page as designed.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith(PANEL_PREFIXES):
            user = request.user
            if user.is_authenticated and not (user.is_superuser and user.is_verified()):
                raise Http404
        return self.get_response(request)


class HostCanonicoMiddleware:
    """Página pública pedida por subdomínio volta, com 301, ao domínio principal.

    O roteador aceita `*.neurodoc.app.br` de propósito (DEC-15: apelido de
    subdomínio por clínica), e o certificado curinga cobre todos. O efeito
    colateral era a vitrine inteira respondendo 200 em `www.`, e em qualquer
    outro nome inventado: cada um uma cópia do site para o rastreador. A
    canônica apontava para o domínio certo, e o Google acabava juntando —
    mas canônica é sugestão, e redirecionamento é instrução.

    **Só o catálogo público e os arquivos da raiz** são redirecionados
    (`base.seo.pagina_de` e `base.public_urls`). `/app/`, `/accounts/`, o
    portal e todo o resto seguem atendendo no subdomínio como antes: mexer
    neles mudaria o cookie de sessão de host, que é host-only, e derrubaria
    quem já está dentro. Também só `GET` e `HEAD` — um `POST` redirecionado
    perde o corpo.

    Vale só para **subdomínio do host canônico**. `testserver`, `localhost`
    e o IP da rede local passam direto, e é por isso que a bateria e o
    ambiente local não mudam com isto.
    """

    def __init__(self, get_response):
        from urllib.parse import urlsplit

        from django.conf import settings

        self.get_response = get_response
        partes = urlsplit(getattr(settings, 'PUBLIC_BASE_URL', '') or '')
        self.esquema = partes.scheme or 'https'
        self.canonico = (partes.hostname or '').lower()

    def __call__(self, request):
        destino = self._destino(request)
        if destino:
            from django.http import HttpResponsePermanentRedirect

            return HttpResponsePermanentRedirect(destino)
        resposta = self.get_response(request)
        # O `<meta name="robots">` só existe em HTML. O PDF de um documento,
        # o arquivo de uma exportação e a resposta JSON de uma tela não têm
        # onde levá-lo — e um link desses que vaze para uma página de
        # terceiro seria indexado com o nome do arquivo. O cabeçalho é o
        # `noindex` de quem não é HTML; o estático versionado fica de fora
        # porque CSS e JS são o que o Google precisa para desenhar a página.
        if (not request.path_info.startswith('/static/')
                and 'X-Robots-Tag' not in resposta
                and not self._publico(request.path_info)):
            resposta['X-Robots-Tag'] = 'noindex, nofollow'
        return resposta

    def _destino(self, request):
        if not self.canonico or request.method not in ('GET', 'HEAD'):
            return None
        try:
            host = request.get_host().split(':')[0].lower()
        except Exception:                                   # noqa: BLE001
            return None
        if host == self.canonico or not host.endswith('.' + self.canonico):
            return None
        if not self._publico(request.path_info):
            return None
        return '%s://%s%s' % (self.esquema, self.canonico, request.get_full_path())

    @staticmethod
    def _publico(caminho):
        from django.urls import Resolver404, resolve

        from . import seo

        try:
            match = resolve(caminho)
        except Resolver404:
            return False
        rota = match.url_name or ''
        if match.namespace:
            rota = '%s:%s' % (match.namespace, rota)
        if rota in ARQUIVOS_DA_RAIZ or rota.startswith('ativo-'):
            return True
        try:
            return seo.pagina_de(rota, match.kwargs or {}) is not None
        except Exception:                                   # noqa: BLE001
            return False


#: Os nomes de rota de `base/public_urls.py` que um rastreador pede direto.
ARQUIVOS_DA_RAIZ = {'robots', 'sitemap', 'webmanifest', 'llms', 'llm', 'llms-full'}
