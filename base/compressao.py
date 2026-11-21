"""Compressão do HTML (e de outros textos) na saída do servidor.

Por que existe (medido em 2026-11-20): o servidor mandava o HTML **sem
compressão** até a Cloudflare, que só comprimia no trecho até o navegador.
A vitrine (128 KB) montava em ~25 ms dentro do contêiner e levava ~0,45 s
a mais que uma página vazia para chegar ao Brasil, porque os 128 KB
atravessavam dos EUA em várias idas e voltas. Comprimida, vira ~20 KB, e
todas as telas grandes do sistema ganham junto.

Três recusas deliberadas sobre o `GZipMiddleware` do Django:

- **resposta em stream nunca é comprimida.** O gzip guarda os bytes até
  juntar um bloco: os eventos do chat da equipe e da IA (SSE) chegariam
  atrasados, ou só no fim. E downloads (PDF, exportação) já saem como
  arquivo, alguns comprimidos;
- **só tipos de texto.** Imagem e PDF já vêm comprimidos; comprimir de novo
  gasta CPU para nada — e o `ETag` forte do logotipo, que a tela confere à
  mão, viraria fraco;
- a **proteção contra o BREACH** do Django (bytes aleatórios no cabeçalho
  do gzip) continua ligada: a página leva o código do CSRF, e é esse o
  ataque que a compressão abre.
"""
from django.middleware.gzip import GZipMiddleware

#: O que vale comprimir. Prefixo do `Content-Type`.
TIPOS_DE_TEXTO = (
    'text/html', 'text/plain', 'text/csv', 'text/css', 'text/xml', 'text/markdown',
    'application/json', 'application/javascript', 'application/xml', 'application/xhtml+xml',
    'application/manifest+json', 'application/ld+json', 'image/svg+xml',
)


class CompressaoDeTextoMiddleware(GZipMiddleware):
    def process_response(self, request, response):
        if response.streaming:
            return response
        tipo = (response.get('Content-Type') or '').split(';')[0].strip().lower()
        if not tipo.startswith(TIPOS_DE_TEXTO):
            return response
        return super().process_response(request, response)
