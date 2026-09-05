import urllib.request

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpResponse


class HealthMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    @staticmethod
    def health_response(request):
        request.get_host()
        response = HttpResponse('ok', content_type='text/plain')
        response['Cache-Control'] = 'no-store'
        return response

    def __call__(self, request):
        if self.is_async:
            return self.acall(request)
        if request.path_info == '/health/':
            return self.health_response(request)
        return self.get_response(request)

    async def acall(self, request):
        if request.path_info == '/health/':
            return self.health_response(request)
        return await self.get_response(request)


if __name__ == '__main__':
    with urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=4) as result:
        raise SystemExit(0 if result.status == 200 else 1)
