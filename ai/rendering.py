import html
import re

import markdown as markdown_lib

_DANGEROUS_ATTR_URI = re.compile(
    r'(href|src)="(?:\s|&nbsp;)*(?:javascript|data|vbscript):[^"]*"', re.IGNORECASE,
)


def render_markdown(raw_text):
    """Escapes the raw text *before* Markdown conversion, so any literal
    `<script>`/`<img onerror=...>` typed by the model becomes inert
    entities rather than real tags -- only the HTML that Python-Markdown
    itself generates from recognized syntax (bold, links, code blocks) is
    real markup. A second pass neutralizes `javascript:`/`data:`/`vbscript:`
    URIs in whatever `href`/`src` Markdown produced from `[text](url)`
    syntax, since Markdown itself does not restrict link schemes.
    """
    escaped = html.escape(raw_text or '')
    rendered = markdown_lib.markdown(escaped, extensions=['fenced_code', 'tables'])
    rendered = _DANGEROUS_ATTR_URI.sub(r'\1="#"', rendered)
    return rendered
