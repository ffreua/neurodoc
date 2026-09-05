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
