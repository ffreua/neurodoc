import html
import re

import markdown as markdown_lib

#: Todo `href`/`src` que o Markdown gerou. O valor é conferido contra uma
#: lista de **permissão**, e não de proibição.
_ATRIBUTO_URI = re.compile(r'(href|src)="([^"]*)"', re.IGNORECASE)

#: Esquemas que o texto da IA pode usar num link. A lista negra antiga
#: (`javascript|data|vbscript`) era contornada por um caractere de controle
#: antes do esquema — `\x01javascript:` —, que o navegador descarta ao ler
#: a URL (auditoria externa de 2026-11-20). Só a CSP segurava; a defesa não
#: pode depender só dela.
_ESQUEMAS_PERMITIDOS = ('http:', 'https:', 'mailto:')

#: O que o navegador ignora no começo e no meio do esquema.
_INVISIVEIS = re.compile(r'[\x00-\x20\x7f]+')


def _uri_segura(valor):
    """`True` para link http(s), mailto, âncora ou endereço relativo."""
    bruto = _INVISIVEIS.sub('', html.unescape(valor)).lower()
    if not bruto or bruto.startswith(('#', '/', '?')):
        return True
    if bruto.startswith(_ESQUEMAS_PERMITIDOS):
        return True
    # Sem esquema nenhum (nada antes de ":" que pareça um), é relativo.
    return not re.match(r'^[a-z][a-z0-9+.\-]*:', bruto)


def _neutralizar(match):
    if _uri_segura(match.group(2)):
        return match.group(0)
    return f'{match.group(1)}="#"'


def render_markdown(raw_text):
    """Escapes the raw text *before* Markdown conversion, so any literal
    `<script>`/`<img onerror=...>` typed by the model becomes inert
    entities rather than real tags -- only the HTML that Python-Markdown
    itself generates from recognized syntax (bold, links, code blocks) is
    real markup. A second pass keeps only http(s)/mailto/relative URIs in
    whatever `href`/`src` Markdown produced from `[text](url)` syntax,
    since Markdown itself does not restrict link schemes.
    """
    escaped = html.escape(raw_text or '')
    rendered = markdown_lib.markdown(escaped, extensions=['fenced_code', 'tables'])
    return _ATRIBUTO_URI.sub(_neutralizar, rendered)
