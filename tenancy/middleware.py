from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import render

from .context import build_access_context
from .models import TenantStatus

#: Métodos que só leem. A regra da organização congelada é sobre escrita,
#: e o verbo é o critério certo: a alternativa seria marcar view por view,
#: e a view esquecida é justamente a que ninguém percebe.
SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})

#: Caminhos que continuam abertos numa clínica congelada, apesar de
#: escreverem. Marcar uma notificação como lida é estado do **usuário**,
#: não da clínica: trancá-lo encheria o sino de avisos que a pessoa não
#: tem como baixar, sem proteger dado nenhum.
#:
#: Entrar, sair e trocar de organização não aparecem aqui porque vivem em
#: `/accounts/`, fora do alcance deste middleware — quem está numa clínica
#: congelada continua tendo como sair dela.
ALWAYS_ALLOWED_PREFIXES = ('/app/notifications/',)


class TenantMiddleware:
    """Resolves and attaches request.access_context for the `/app/` area.

    Every other path is left alone here: `/health/`, `/static/`, `/admin/`
    and `/technical-docs/` have their own dedicated protection, and public
    routes (landing, auth, onboarding) do not need a tenant.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.access_context = None
        if not request.path_info.startswith('/app/'):
            return self.get_response(request)
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.email_verified_at is not None and not request.session.get('tenant_id'):
            # Authenticated, verified, but no organization chosen yet in
            # this browser session (fresh login, or a deep link opened
            # before ever picking one) -- send them to pick one and come
            # straight back here, instead of a bare 404 with no way out.
            return redirect_to_login(request.get_full_path(), login_url='accounts:tenant-picker')
        context = build_access_context(request)
        if context is None:
            raise Http404
        request.access_context = context

        # ------------------------------------------ organização inativa
        #
        # Encerrada: a porta fecha, e a tela **explica**. Um 404 aqui seria
        # tecnicamente suficiente e humanamente inútil: quem está do outro
        # lado é um médico cuja clínica foi desligada, e ele precisa saber
        # que o prontuário continua guardado e a quem pedir a exportação.
        if context.tenant_status == TenantStatus.CLOSED:
            return render(request, 'tenancy/tenant_closed.html', status=403)

        # Suspensa: congela. Ler segue livre; escrever é recusado aqui, num
        # lugar só, e não em cada view -- a view que esquecesse a
        # verificação seria a que ninguém testaria.
        if (
            context.tenant_status == TenantStatus.SUSPENDED
            and request.method not in SAFE_METHODS
            and not request.path_info.startswith(ALWAYS_ALLOWED_PREFIXES)
        ):
            return render(request, 'tenancy/tenant_suspended.html', status=403)

        return self.get_response(request)
