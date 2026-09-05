import asyncio
import mimetypes
import re
from pathlib import Path

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.http import FileResponse, HttpResponse, StreamingHttpResponse


async def file_chunks(path):
    source = await asyncio.to_thread(path.open, 'rb')
    try:
        while chunk := await asyncio.to_thread(source.read, 65536):
            yield chunk
    finally:
        await asyncio.to_thread(source.close)


def public_asset(request, asynchronous):
    request.get_host()
    if request.method not in {'GET', 'HEAD'}:
        return HttpResponse(status=405, headers={'Allow': 'GET, HEAD'})
    match = re.fullmatch(r'/static/(dev|[a-f0-9]{40})/(.+)', request.path_info)
    if not match or (match[1] == 'dev' and not settings.DEBUG):
        return HttpResponse(status=404)
    release, relative = match.groups()
    parts = relative.split('/')
    if any(not part or part.startswith('.') or '\\' in part for part in parts):
        return HttpResponse(status=404)
    if parts[-1] == 'staticfiles.json':
        return HttpResponse(status=404)
    root = Path('/data/staticfiles/public/static') / release
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not (root / '.ready').is_file():
        return HttpResponse(status=404)
    if not path.is_file():
        return HttpResponse(status=404)
    content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    headers = {'Cache-Control': 'no-cache' if settings.DEBUG else
               'public, max-age=31536000, immutable',
               'Content-Length': str(path.stat().st_size),
               'X-Content-Type-Options': 'nosniff'}
    if request.method == 'HEAD':
        return HttpResponse(content_type=content_type, headers=headers)
    if asynchronous:
        return StreamingHttpResponse(file_chunks(path), content_type=content_type,
                                     headers=headers)
    return FileResponse(path.open('rb'), content_type=content_type, headers=headers)


class ReleaseStaticMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self.is_async:
            return self.acall(request)
        if request.path_info.startswith('/static/'):
            return public_asset(request, False)
        return self.get_response(request)

    async def acall(self, request):
        if request.path_info.startswith('/static/'):
            return await asyncio.to_thread(public_asset, request, True)
        return await self.get_response(request)
