"""De quem veio esta requisicao, de verdade.

Todo limite por IP do sistema -- tentativas de login, consultas ao QR do
documento, portal do paciente, formulario de contato -- lia
`REMOTE_ADDR`. Em producao o app so e alcancavel atraves do Traefik, na
rede interna do Swarm, e `REMOTE_ADDR` e o IP **do Traefik**: o mesmo
para todo visitante do planeta.

O efeito era o contrario do pretendido. `documents/verification.py`
permite vinte consultas por IP; com todos no mesmo balde, vinte consultas
de qualquer pessoa fechavam a verificacao de receita **para todo mundo**,
e essa e a pagina que a farmacia abre com o paciente esperando no balcao.
O mesmo valia para o portal e para o formulario da pagina de vendas. O
login escapava por acidente: a chave dele inclui o e-mail
(`accounts/throttling.py`), entao o bloqueio sempre foi por conta.

A saida **nao** e confiar em `X-Forwarded-For`, que qualquer cliente
escreve. E confiar nele so quando quem entregou a requisicao e um proxy
que nos mesmos declaramos: `TRUSTED_PROXIES`. Fora dessa lista, o
cabecalho e ignorado e vale o endereco da conexao -- que e o
comportamento correto para quem fala com o app diretamente.

O uvicorn continua com `--no-proxy-headers` (`ops/entrypoint.sh`), de
proposito: quem decide em quem confiar e esta lista, num lugar so, e nao
o servidor de aplicacao com a regra dele.
"""

import ipaddress

from django.conf import settings

#: Quando nao ha endereco nenhum -- `manage.py`, teste sem `REMOTE_ADDR`.
#: E uma string, e nao `None`, porque vira chave de cache nos limitadores:
#: `None` viraria "None" em metade deles e "" na outra metade.
UNKNOWN = 'desconhecido'


def _parse_networks(valores):
    redes = []
    for bruto in valores or ():
        texto = str(bruto).strip()
        if not texto:
            continue
        try:
            redes.append(ipaddress.ip_network(texto, strict=False))
        except ValueError:
            # Entrada invalida no `.env` nao derruba o site: ela apenas nao
            # confia em ninguem, que e o lado seguro do erro.
            continue
    return redes


def _is_trusted(endereco, redes):
    try:
        ip = ipaddress.ip_address(endereco)
    except ValueError:
        return False
    return any(ip in rede for rede in redes)


def client_ip(request):
    """O endereco do cliente, atravessando apenas proxies confiaveis.

    `X-Forwarded-For` e uma lista em que cada proxy **acrescenta** quem
    falou com ele: `cliente, proxy1, proxy2`. Ler o primeiro item seria
    aceitar o que o cliente escreveu -- forjar o proprio IP viraria uma
    linha de `curl`, e o limitador deixaria de limitar.

    Por isso a leitura e da direita para a esquerda, descartando enderecos
    confiaveis enquanto houver: o primeiro que nao for de um proxy nosso e
    quem de fato falou com a nossa borda. Se todos forem confiaveis, vale
    o primeiro da lista -- a cadeia inteira e nossa.

    Com a Cloudflare na frente, as faixas dela precisam entrar em
    `TRUSTED_PROXIES` para o IP do visitante aparecer; sem isso o que
    aparece e o IP da Cloudflare. E ruim de propaganda e certo de
    seguranca: nao se confia em quem nao foi declarado confiavel.
    """
    if request is None:
        return UNKNOWN
    remoto = (request.META.get('REMOTE_ADDR') or '').strip()
    redes = _parse_networks(getattr(settings, 'TRUSTED_PROXIES', ()))
    if not remoto:
        return UNKNOWN
    if not redes or not _is_trusted(remoto, redes):
        return remoto

    encaminhados = [
        parte.strip()
        for parte in (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')
        if parte.strip()
    ]
    for endereco in reversed(encaminhados):
        if not _is_trusted(endereco, redes):
            return endereco
    return encaminhados[0] if encaminhados else remoto
