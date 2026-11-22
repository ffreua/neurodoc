"""O corpo em HTML da comunicação em massa: o que entra, e o que sai.

Quem escreve a campanha cola HTML com CSS para a mensagem chegar bonita.
Esse HTML vai a pacientes, pelo servidor da clínica, com o nome dela no
remetente — e por isso não sai como veio. Três regras, nesta ordem:

**Limpo por lista de permissão, não por lista negra.** `nh3` (o `ammonia`
do Rust) reescreve o documento e só deixa passar as marcas de layout de
e-mail — tabela, parágrafo, título, imagem, link, lista. Script, `iframe`,
formulário, `object`, atributo de evento e `javascript:` não atravessam
porque nunca estiveram na lista. A lista negra foi recusada pelo mesmo
motivo do sanitizador do chat (auditoria de 2026-11-20): toda vez que
alguém inventa um jeito novo de escrever `javascript:`, ela perde.

**O CSS também é limpo.** Estilo é onde o HTML de e-mail mora (`style=` e
um bloco `<style>`), e é também por onde entram `url(javascript:…)`,
`expression()` do Internet Explorer, `@import` de folha alheia e
`-moz-binding`. Fica só `url()` de `https:` (imagem de fundo) e a
declaração com qualquer uma das outras some inteira.

**O rodapé não é do HTML de quem escreve.** O link de descadastro é
acrescentado aqui, depois da limpeza, fora do corpo — quem escreve não o
remove por esquecimento nem por escolha (LGPD, art. 8º, §5º), como já
acontecia no texto simples. E a mensagem sempre leva também a versão em
texto (`texto_do_html`): cliente que não mostra HTML, e filtro que o
descarta, ainda entregam algo legível.

**Imagem remota é permitida, e o motivo é medido, não suposto.** O modelo
da campanha recusa medir abertura (`MarketingCampaign`): pixel por
destinatário diria quando cada paciente leu. Uma imagem remota só faria
isso se o endereço mudasse por destinatário — e aqui o HTML é **o mesmo
para todos** (não há campo de mesclagem), então o servidor da imagem vê
que alguém abriu, não quem. O logotipo da clínica vale esse custo; o
pixel individual continua impossível.
"""

import html
import re

import nh3

#: Teto do HTML colado. O Gmail corta a mensagem acima de ~102 KB e
#: esconde o resto atrás de "ver mensagem inteira" — e o rodapé, com o
#: link de descadastro, é justamente o que fica no fim.
MAX_HTML = 90_000

#: Marcas de layout de e-mail. Nada que execute, envie ou embuta outro
#: documento.
TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'center', 'code', 'col',
    'colgroup', 'dd', 'del', 'div', 'dl', 'dt', 'em', 'font', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'i', 'img', 'ins', 'li', 'mark', 'ol', 'p', 'pre',
    's', 'small', 'span', 'strong', 'sub', 'sup', 'table', 'tbody', 'td',
    'tfoot', 'th', 'thead', 'tr', 'u', 'ul',
}

_COMUNS = {'style', 'class', 'align', 'dir', 'title', 'role', 'lang'}
ATRIBUTOS = {
    '*': _COMUNS,
    'a': {'href', 'target'},
    'img': {'src', 'alt', 'width', 'height', 'border'},
    'table': {'width', 'height', 'border', 'cellpadding', 'cellspacing', 'bgcolor', 'valign'},
    'td': {'width', 'height', 'colspan', 'rowspan', 'bgcolor', 'valign', 'nowrap'},
    'th': {'width', 'height', 'colspan', 'rowspan', 'bgcolor', 'valign', 'scope'},
    'tr': {'bgcolor', 'valign', 'height'},
    'col': {'width', 'span'}, 'colgroup': {'width', 'span'},
    'font': {'color', 'face', 'size'},
    'ol': {'start', 'type'}, 'ul': {'type'},
}

#: Propriedades de CSS que um e-mail usa. Fora delas o `style=` perde a
#: declaração — inclusive `position` (cobrir o rodapé com outra caixa) e
#: `behavior`/`-moz-binding` (que executavam código em navegador antigo).
PROPRIEDADES_CSS = {
    'background', 'background-color', 'background-image', 'background-position',
    'background-repeat', 'background-size', 'border', 'border-bottom',
    'border-bottom-color', 'border-bottom-style', 'border-bottom-width',
    'border-collapse', 'border-color', 'border-left', 'border-left-color',
    'border-left-style', 'border-left-width', 'border-radius', 'border-right',
    'border-right-color', 'border-right-style', 'border-right-width',
    'border-spacing', 'border-style', 'border-top', 'border-top-color',
    'border-top-style', 'border-top-width', 'border-width', 'box-shadow',
    'box-sizing', 'color', 'direction', 'display', 'font', 'font-family',
    'font-size', 'font-style', 'font-variant', 'font-weight', 'height',
    'letter-spacing', 'line-height', 'list-style', 'list-style-type', 'margin',
    'margin-bottom', 'margin-left', 'margin-right', 'margin-top', 'max-height',
    'max-width', 'min-height', 'min-width', 'mso-line-height-rule', 'opacity',
    'overflow', 'padding', 'padding-bottom', 'padding-left', 'padding-right',
    'padding-top', 'table-layout', 'text-align', 'text-decoration',
    'text-indent', 'text-shadow', 'text-transform', 'vertical-align',
    'white-space', 'width', 'word-break', 'word-spacing', 'word-wrap',
}

_STYLE_BLOCO = re.compile(r'<style\b[^>]*>(.*?)</style\s*>', re.IGNORECASE | re.DOTALL)
_CORPO = re.compile(r'<body\b[^>]*>(.*)</body\s*>', re.IGNORECASE | re.DOTALL)
_COMENTARIO_CSS = re.compile(r'/\*.*?\*/', re.DOTALL)
_URL_CSS = re.compile(r'url\(\s*([\'"]?)(.*?)\1\s*\)', re.IGNORECASE | re.DOTALL)
#: O que torna uma declaração perigosa mesmo dentro de propriedade
#: permitida. Comparado sem espaço, sem barra invertida e sem caixa: o CSS
#: aceita `java\script` e `expr/**/ession`, e a comparação crua perderia.
_PROIBIDO_CSS = ('expression(', 'javascript:', 'vbscript:', 'behavior', '-moz-binding',
                 '@import', 'data:text', '</')


def _normalizado(texto):
    return re.sub(r'[\s\\]+', '', _COMENTARIO_CSS.sub('', texto)).lower()


def _url_permitida(valor):
    valor = html.unescape(valor or '').strip()
    return bool(re.match(r'^https://', valor, re.IGNORECASE))


def _declaracao_segura(declaracao):
    """A declaração, se pode ficar; `None`, se sai inteira."""
    plano = _normalizado(declaracao)
    if any(marca in plano for marca in _PROIBIDO_CSS):
        return None
    for _aspas, alvo in _URL_CSS.findall(declaracao):
        if not _url_permitida(alvo):
            return None
    return declaracao.strip()


def css_seguro(css):
    """Um bloco `<style>` limpo: regras mantidas, declarações perigosas fora.

    Não é um analisador de CSS completo, e não precisa ser: o que se
    procura são as poucas construções que executam ou buscam algo, e a
    declaração que traz uma delas sai inteira. `@import` e `@font-face`
    (fonte remota de qualquer lugar) saem como regra; `@media` fica, porque
    é como o e-mail se ajusta ao celular.
    """
    css = _COMENTARIO_CSS.sub('', css or '')
    css = re.sub(r'@import[^;]*;?', '', css, flags=re.IGNORECASE)
    css = re.sub(r'@charset[^;]*;?', '', css, flags=re.IGNORECASE)
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', css, flags=re.IGNORECASE)

    def _bloco(m):
        declaracoes = [d for d in (_declaracao_segura(x) for x in m.group(2).split(';')) if d]
        return f'{m.group(1)}{{{"; ".join(declaracoes)}}}'

    css = re.sub(r'([^{}]*)\{([^{}]*)\}', _bloco, css)
    # O fechamento do bloco é a única saída do `<style>`: sem `<` não há
    # como escrever `</style>` e começar HTML fora da limpeza.
    return css.replace('<', '').strip()


def _filtro_de_atributo(tag, atributo, valor):
    if atributo == 'style':
        declaracoes = [d for d in (_declaracao_segura(x) for x in valor.split(';')) if d]
        return '; '.join(declaracoes) or None
    if atributo == 'src':
        # Imagem só de `https:`. `http:` entrega o conteúdo misto que o
        # cliente bloqueia, e `data:` vira anexo invisível em vários
        # leitores — e nenhum dos dois é o logotipo de alguém.
        return valor if _url_permitida(valor) else None
    if atributo == 'target':
        return '_blank'
    return valor


def limpar_html(bruto):
    """O HTML colado, reduzido ao que pode chegar ao paciente.

    Aceita documento inteiro (com `<head>` e `<style>`) ou só o pedaço do
    corpo. Devolve `(css, corpo)`, já limpos, para `montar_documento`
    juntar com o rodapé. Corpo vazio depois da limpeza devolve `('', '')`:
    é o sinal de que nada do que foi colado sobrou.
    """
    bruto = bruto or ''
    css = '\n'.join(css_seguro(bloco) for bloco in _STYLE_BLOCO.findall(bruto))
    sem_style = _STYLE_BLOCO.sub('', bruto)
    corpo = _CORPO.search(sem_style)
    corpo = corpo.group(1) if corpo else sem_style
    limpo = nh3.clean(
        corpo,
        tags=TAGS,
        clean_content_tags={'script', 'style', 'title', 'head'},
        attributes=ATRIBUTOS,
        attribute_filter=_filtro_de_atributo,
        url_schemes={'https', 'http', 'mailto'},
        filter_style_properties=PROPRIEDADES_CSS,
        link_rel='noopener noreferrer',
        strip_comments=True,
    ).strip()
    if not texto_do_html(limpo).strip() and '<img' not in limpo:
        return '', ''
    return css, limpo


def rodape_html(nome_clinica, link_descadastro):
    """O rodapé obrigatório, em HTML, fora do corpo de quem escreve.

    Estilo próprio e inline, para não herdar o CSS da campanha: o link de
    descadastro tem de continuar visível mesmo que o corpo pinte todo
    texto de branco.
    """
    nome = html.escape(nome_clinica)
    link = html.escape(link_descadastro, quote=True)
    estilo = ('font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;'
              'color:#555555;background:#ffffff;')
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin-top:24px;border-top:1px solid #dddddd;{estilo}"><tr>'
        f'<td style="padding:16px 12px;{estilo}">'
        f'<p style="margin:0 0 6px 0;{estilo}">Você recebeu esta mensagem porque autorizou '
        f'{nome} a enviar comunicações.</p>'
        f'<p style="margin:0 0 6px 0;{estilo}">Para não receber mais, '
        f'<a href="{link}" style="color:#1a56db;text-decoration:underline;">clique aqui para '
        f'se descadastrar</a>.</p>'
        f'<p style="margin:0;{estilo}">Esta é uma mensagem de divulgação. Para assuntos do seu '
        f'atendimento, use os canais de sempre da clínica.</p>'
        f'</td></tr></table>'
    )


def montar_documento(css, corpo, nome_clinica, link_descadastro, assunto=''):
    """O documento que sai: o corpo limpo e o rodapé, num HTML completo."""
    estilo = f'<style type="text/css">{css}</style>' if css else ''
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{html.escape(assunto)}</title>{estilo}</head>'
        f'<body style="margin:0;padding:0;">{corpo}'
        f'{rodape_html(nome_clinica, link_descadastro)}</body></html>'
    )


_QUEBRA = re.compile(r'<\s*(br|/p|/div|/tr|/h[1-6]|/li|/table|hr)\b[^>]*>', re.IGNORECASE)
_LINK = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a\s*>', re.IGNORECASE | re.DOTALL)


def texto_do_html(corpo):
    """A versão em texto de um corpo HTML já limpo.

    Para a parte `text/plain` da mensagem quando quem escreve não deu um
    texto próprio. Os links ganham o endereço entre parênteses — sem ele,
    "clique aqui" no texto simples não leva a lugar nenhum.
    """
    def _link(m):
        rotulo = nh3.clean(m.group(2), tags=set()).strip()
        alvo = html.unescape(m.group(1))
        return f'{rotulo} ({alvo})' if rotulo and rotulo != alvo else alvo

    texto = _LINK.sub(_link, corpo or '')
    texto = _QUEBRA.sub('\n', texto)
    texto = html.unescape(nh3.clean(texto, tags=set()))
    linhas = [re.sub(r'[ \t\xa0]+', ' ', linha).strip() for linha in texto.splitlines()]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(linhas)).strip()
