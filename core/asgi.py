import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

#: Teto do corpo de uma requisição, em bytes. O maior envio legítimo é um
#: anexo de 25 MB (`documents.models.MAX_ATTACHMENT_BYTES`); o portal manda
#: até 5 × 3 MB.
#:
#: O handler ASGI do Django lê o corpo **inteiro** para um arquivo
#: temporário antes de qualquer middleware, view, CSRF ou limite por IP, e
#: o `/tmp` do contêiner é um tmpfs de 128 MB. Sem teto, um POST anônimo de
#: 100 MB (o limite da Cloudflare) enchia o `/tmp` e derrubava os envios e
#: a assinatura de PDF de todo mundo (auditoria externa de 2026-11-20). O
#: teto não foi para o Traefik porque o `buffering` de lá também retém a
#: **resposta** inteira, e isso quebraria o streaming do chat (SSE).
MAX_CORPO_BYTES = 40 * 1024 * 1024


def limitar_corpo(app, limite=MAX_CORPO_BYTES):
    """Recusa com 413 o corpo declarado grande demais; corta o que mentir."""

    async def wrapper(scope, receive, send):
        if scope['type'] != 'http':
            return await app(scope, receive, send)
        declarado = dict(scope.get('headers') or ()).get(b'content-length')
        if declarado is not None and declarado.isdigit() and int(declarado) > limite:
            await send({'type': 'http.response.start', 'status': 413,
                        'headers': [(b'content-type', b'text/plain; charset=utf-8')]})
            await send({'type': 'http.response.body',
                        'body': 'Arquivo grande demais.'.encode('utf-8')})
            return
        recebido = 0

        async def receive_limitado():
            nonlocal recebido
            mensagem = await receive()
            if mensagem['type'] == 'http.request':
                recebido += len(mensagem.get('body', b''))
                if recebido > limite:
                    # Sem Content-Length (corpo em partes) que passa do teto:
                    # o Django trata a desconexão como pedido abortado e para
                    # de escrever no `/tmp`.
                    return {'type': 'http.disconnect'}
            return mensagem

        return await app(scope, receive_limitado, send)

    return wrapper


application = limitar_corpo(get_asgi_application())
