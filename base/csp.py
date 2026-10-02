"""Política de conteúdo (CSP): a última linha contra script injetado.

Todas as outras defesas do sistema tentam impedir que script estranho
entre — escape do template, validação de entrada, sanitização. Esta parte
do princípio de que uma delas vai falhar um dia, e diz ao navegador o que
ele tem permissão de executar **mesmo que** o script chegue à página. Num
prontuário isso importa mais que na média: a sessão que uma injeção
sequestraria abre o histórico clínico inteiro de uma clínica.

---

## Como entra em produção

**Começa em modo de relatório**, e isso é a decisão central. Política
aplicada de saída quebra em silêncio e de longe: o navegador simplesmente
não executa, e a tela que falha é aquela que ninguém abriu na semana da
publicação. O modo de relatório manda o navegador **obedecer normalmente e
avisar** o que teria bloqueado — colhe-se o inventário real, com o sistema
em uso, e só depois se fecha.

`CSP_ENFORCE` (padrão `False`) é o que troca o cabeçalho de
`Content-Security-Policy-Report-Only` para `Content-Security-Policy`. Uma
variável, um redeploy, e reversível na mesma velocidade.

## As diretivas, e por que cada uma é o que é

**`script-src 'self' 'nonce-…'`, sem `unsafe-inline`.** É a diretiva que
justifica o trabalho todo. O nonce muda a cada resposta e é sorteado por
`secrets`: um script injetado não tem como adivinhá-lo, e por isso não
executa. Os blocos `<script>` legítimos da casa recebem o nonce pelo
processador de contexto.

Atributo `onclick` **não** é coberto por nonce — só `unsafe-inline` o
salvaria, e isso desligaria a proteção inteira. Por isso os treze que
existiam viraram `data-nd-*` em `static/duralux/nd-inline.js`. Era esse o
trabalho de verdade; o cabeçalho é a parte fácil.

**`style-src 'self' 'unsafe-inline'`, e aqui a concessão é deliberada.**
São setenta atributos `style="..."` espalhados pelas telas, quase todos
uma largura mínima ou uma cor de faixa. Fechar isso exigiria reescrever
setenta trechos de HTML para ganhar pouco: CSS injetado faz defacement e
algum vazamento por seletor, enquanto script injetado faz o que quiser com
a sessão. Fechar `script-src` primeiro é onde está o valor; `style-src`
fica anotado como aperto futuro, honestamente, em vez de fingido.

**`default-src 'self'` e nada de externo.** Esta instalação não carrega um
único recurso de terceiro — nem fonte, nem CDN, nem ícone. Isso foi
conferido antes de escrever a política, e é o que permite que ela seja
estrita sem exceção nenhuma. Se um dia alguém acrescentar um `<script
src="https://cdn…">`, o modo de relatório avisa antes de quebrar.

**`frame-ancestors 'none'`** repete o que o `X-Frame-Options` já diz.
Repetição de propósito: o cabeçalho antigo é o que navegador velho
entende, e esta diretiva é a que o padrão atual define.

**`object-src 'none'`** fecha `<embed>` e `<object>`, que não existem em
nenhuma tela e são porta clássica de plugin.

**`base-uri 'self'`** impede que uma injeção mude a base das URLs
relativas e redirecione todo `src` da página para outro servidor.

**`form-action 'self'`** impede que uma injeção aponte o destino de um
formulário para fora — que, num prontuário, é como um campo de senha ou um
POST de dados do paciente sairia sem ninguém notar.

**`img-src 'self' data: blob:`.** `data:` porque o QR do documento é
gerado em memória e embutido; `blob:` porque o recorte do retrato do
paciente passa por `canvas` antes de subir.

## O que fica de fora do cabeçalho

Nada disto se aplica a resposta que não é HTML. Pôr política em JSON, PDF
ou imagem não protege coisa alguma e engorda toda resposta da API.
"""
import logging
import secrets

from django.conf import settings

logger = logging.getLogger(__name__)

#: Tamanho do nonce em bytes antes do base64. Dezesseis dão 128 bits — o
#: suficiente para que adivinhar não seja estratégia, e curto o bastante
#: para não inchar o HTML com um nonce por bloco.
NONCE_BYTES = 16

#: Tipos de resposta que recebem a política. HTML e mais nada: a política
#: não protege JSON nem PDF, e o cabeçalho em toda resposta da API é peso
#: morto em cada requisição.
TIPOS_COM_POLITICA = ('text/html',)


def montar_politica(nonce, report_uri=''):
    """A política, em texto, para este nonce.

    Montada a cada resposta porque o nonce muda a cada resposta. As
    diretivas em si são constantes — quem quiser mudá-las muda aqui, num
    lugar só, e o roteiro de verificação cobra as que importam.
    """
    diretivas = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        # A concessão consciente. Ver o cabeçalho do módulo.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        # `connect-src` cobre fetch, XHR e o SSE do chat da equipe e da IA,
        # todos na própria origem.
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        # `frame-src 'self'`, e nao `'none'`.
        #
        # A pagina publica do documento (`templates/communications/
        # access_document.html`) mostra o PDF ao paciente dentro de um
        # `<iframe>` da propria origem. Com `'none'`, quem recebe o link
        # abre a pagina e ve uma moldura vazia -- o documento nao aparece,
        # e nao ha erro na tela que explique.
        #
        # Isto foi encontrado no log do modo relatorio, que registrou tres
        # documentos reais bloqueados antes de o modo de bloqueio ser
        # ligado. E exatamente para isso que o modo relatorio existe, e e
        # a razao de ele ter ficado semanas no ar antes.
        #
        # `'self'` nao afrouxa o que importa: `frame-ancestors 'none'`
        # continua impedindo que **outros** embutam nossas paginas, que e
        # a protecao contra clickjacking. Esta diretiva governa o lado
        # oposto -- o que nos podemos embutir --, e a resposta e: so o que
        # servimos.
        "frame-src 'self'",
        # Sem isto, uma página servida em HTTPS ainda pediria sub-recurso
        # em HTTP e o navegador antigo carregaria.
        'upgrade-insecure-requests',
    ]
    if report_uri:
        diretivas.append(f'report-uri {report_uri}')
    return '; '.join(diretivas)


class ContentSecurityPolicyMiddleware:
    """Sorteia o nonce, publica-o para o template e põe o cabeçalho.

    O nonce nasce **antes** da view, em `request.csp_nonce`, porque o
    processador de contexto o lê enquanto o template renderiza — depois da
    resposta pronta seria tarde, e o `<script nonce="">` sairia vazio.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(NONCE_BYTES)
        resposta = self.get_response(request)

        tipo = (resposta.get('Content-Type') or '').split(';')[0].strip().lower()
        if tipo and tipo not in TIPOS_COM_POLITICA:
            return resposta

        # Resposta que já traz a própria política não é sobrescrita: a
        # exceção existe para telas que precisem afrouxar algo pontualmente
        # sem que este middleware desfaça a escolha delas.
        cabecalho = (
            'Content-Security-Policy' if getattr(settings, 'CSP_ENFORCE', False)
            else 'Content-Security-Policy-Report-Only'
        )
        if resposta.has_header(cabecalho):
            return resposta

        resposta[cabecalho] = montar_politica(
            request.csp_nonce, getattr(settings, 'CSP_REPORT_URI', ''),
        )
        return resposta


def csp_nonce(request):
    """Processador de contexto: `{{ nd_csp_nonce }}` nos templates."""
    return {'nd_csp_nonce': getattr(request, 'csp_nonce', '')}
