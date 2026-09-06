from django.contrib.auth.views import redirect_to_login
from django.http import Http404

from .context import build_access_context


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
        return self.get_response(request)
