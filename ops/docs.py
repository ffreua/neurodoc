import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe


@require_safe
def technical_docs(request, path=''):
    user = request.user
    if not (settings.NEURODOC_DOCS_ENABLED and user.is_authenticated
            and user.is_active and user.is_staff and user.is_superuser
            and user.is_verified()):
        raise Http404
    root = (settings.BASE_DIR / 'site').resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or any(p.startswith('.') for p in path.split('/')):
        raise Http404
    if target.is_dir():
        target = target / 'index.html'
    if not target.is_file():
        raise Http404
    response = FileResponse(target.open('rb'), content_type=
                            mimetypes.guess_type(target.name)[0] or
                            'application/octet-stream')
    response['Cache-Control'] = 'private, no-store'
    return response
