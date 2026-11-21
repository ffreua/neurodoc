"""Compressão do HTML na saída (2026-11-20, `base/compressao.py`).

O que este roteiro tenta quebrar:

1. a vitrine sai comprimida para quem aceita gzip, e inteira para quem não
   aceita; o conteúdo descomprimido é a mesma página, com o nonce da CSP
   do cabeçalho igual ao do HTML;
2. `Vary: Accept-Encoding` em toda resposta comprimível (sem ele, um cache
   no meio serviria gzip a quem não pediu);
3. stream (SSE) nunca é comprimido — os eventos do chat chegariam atrasados;
4. imagem, PDF e resposta curta não são comprimidos;
5. JSON e CSV, que são texto, são;
6. o middleware fica antes de todos os que mexem no corpo da resposta.
"""
import gzip
import re

from django.conf import settings as dj_settings
from django.http import HttpResponse, StreamingHttpResponse
from django.test import Client, RequestFactory

from base.compressao import CompressaoDeTextoMiddleware

falhas = []


def conferir(rotulo, condicao, detalhe=''):
    print(f'  {"ok   " if condicao else "FALHA"} {rotulo}' + (f'  [{detalhe}]' if not condicao and detalhe else ''))
    if not condicao:
        falhas.append(rotulo)


def passa(resposta, ae='gzip, deflate, br'):
    req = RequestFactory().get('/', HTTP_ACCEPT_ENCODING=ae)
    return CompressaoDeTextoMiddleware(lambda r: resposta)(req)


print('1. A vitrine comprimida para quem aceita, inteira para quem não')
cliente = Client(HTTP_HOST='localhost')
crua = cliente.get('/')
comprimida = cliente.get('/', HTTP_ACCEPT_ENCODING='gzip, deflate, br')
conferir('sem pedir, sai sem compressão', crua.status_code == 200 and not crua.has_header('Content-Encoding'))
conferir('pedindo gzip, sai gzip', comprimida.get('Content-Encoding') == 'gzip', comprimida.get('Content-Encoding'))
corpo = gzip.decompress(comprimida.content) if comprimida.get('Content-Encoding') == 'gzip' else b''
conferir('e bem menor', len(comprimida.content) < len(crua.content) * 0.4,
         (len(comprimida.content), len(crua.content)))
conferir('descomprimida, é a página inteira', corpo.rstrip().endswith(b'</html>') and len(corpo) > len(crua.content) * 0.9)
nonce_html = re.search(rb'nonce="([^"]+)"', corpo)
politica = comprimida.get('Content-Security-Policy') or comprimida.get('Content-Security-Policy-Report-Only') or ''
conferir('o nonce do HTML é o do cabeçalho da CSP',
         bool(nonce_html) and f"'nonce-{nonce_html.group(1).decode()}'" in politica)

print('\n2. Vary: Accept-Encoding')
conferir('na resposta comprimida', 'Accept-Encoding' in (comprimida.get('Vary') or ''), comprimida.get('Vary'))
conferir('e na que saiu inteira', 'Accept-Encoding' in (crua.get('Vary') or ''), crua.get('Vary'))

print('\n3. Stream nunca é comprimido')
sse = StreamingHttpResponse(iter(['data: 1\n\n', 'data: 2\n\n']), content_type='text/event-stream')
saida = passa(sse)
conferir('o SSE sai sem Content-Encoding', not saida.has_header('Content-Encoding'))
conferir('e com os eventos como vieram', b''.join(saida.streaming_content) == b'data: 1\n\ndata: 2\n\n')
download = StreamingHttpResponse(iter([b'a' * 5000]), content_type='text/csv')
conferir('download em stream também não', not passa(download).has_header('Content-Encoding'))

print('\n4. Imagem, PDF e resposta curta ficam como estão')
for tipo in ('image/png', 'application/pdf', 'image/jpeg'):
    r = passa(HttpResponse(b'x' * 5000, content_type=tipo))
    conferir(f'{tipo} não', not r.has_header('Content-Encoding'))
r = passa(HttpResponse('<p>curta</p>', content_type='text/html'))
conferir('HTML de menos de 200 bytes não', not r.has_header('Content-Encoding'))
imagem = HttpResponse(b'x' * 5000, content_type='image/png')
imagem['ETag'] = '"forte"'
conferir('o ETag forte da imagem continua forte', passa(imagem)['ETag'] == '"forte"')

print('\n5. JSON e CSV, que são texto, são comprimidos')
for tipo in ('application/json', 'text/csv; charset=utf-8', 'image/svg+xml'):
    r = passa(HttpResponse(('{"a": "texto repetido"} ' * 300).encode(), content_type=tipo))
    conferir(f'{tipo} sim', r.get('Content-Encoding') == 'gzip', r.get('Content-Encoding'))

print('\n6. Posição na lista')
mw = list(dj_settings.MIDDLEWARE)
pos = mw.index('base.compressao.CompressaoDeTextoMiddleware')
conferir('antes de todos os que leem ou escrevem o corpo',
         all(pos < mw.index(m) for m in ('base.csp.ContentSecurityPolicyMiddleware',
                                         'django.middleware.common.CommonMiddleware',
                                         'tenancy.middleware.TenantMiddleware',
                                         'base.lentidao.TelasLentasMiddleware')))

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f_ in falhas:
        print('  -', f_)
    raise SystemExit(1)
print('Tudo certo.')
