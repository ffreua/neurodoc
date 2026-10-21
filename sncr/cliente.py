"""O cliente da API do SNCR — o único lugar que conhece o formato da Anvisa.

Fontes: Manual da API SNCR v5 (set/2026), OpenAPI `sncr-api` 1.2.1 da
homologação e a aplicação de exemplo oficial. O que ainda é **suposição**
até o primeiro pedido real (decisão D8) mora aqui e só aqui, para o
ajuste, se houver, não espalhar:

- o `Origin` mandado pelo servidor na troca do token (o `session_id` fica
  preso ao `Origin` que iniciou o login; a aplicação de exemplo chama por
  um proxy de servidor) — lacuna L7;
- `numeracoesReceita`, que o manual mostra como texto e a OpenAPI como
  lista — o parser aceita os dois (L2);
- o cabeçalho `X-Jws-Integradora`, que está na OpenAPI e não no manual:
  **não** é mandado até ser documentado (L1).

**O desfecho é a parte delicada, não o sucesso.** O pedido de bloco gasta
1 de 3 do mês e não tem consulta nem cancelamento. Por isso o erro é
classificado pelo que se sabe do lado de lá:

- `Indisponivel` — o pedido **não chegou** (DNS, TLS, conexão recusada,
  tempo esgotado ao conectar). Pode tentar de novo depois.
- `Incerto` — o pedido **saiu** e a resposta não veio, veio quebrada, ou
  veio 5xx. A Anvisa pode ter entregado o bloco. **Não repetir.**
- `Recusado` — a Anvisa respondeu 4xx com motivo (CRM diferente do CPF,
  limite do mês, CNPJ inválido...). Nada foi entregue.
- `SessaoInvalida` — 401: o login expirou (o token vive 30 s).
"""

import httpx

#: Conectar é rápido ou não vai; ler espera a Anvisa gerar o bloco.
TEMPO = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)


class ErroSncr(Exception):
    """Base. `str(exc)` é a mensagem em português para o médico."""

    def __init__(self, mensagem, status=None):
        super().__init__(mensagem)
        self.status = status


class Indisponivel(ErroSncr):
    pass


class Incerto(ErroSncr):
    pass


class Recusado(ErroSncr):
    pass


class SessaoInvalida(ErroSncr):
    pass


def _mensagem(resposta):
    """O motivo que a Anvisa escreveu, em qualquer dos formatos documentados."""
    try:
        corpo = resposta.json()
    except ValueError:
        return (resposta.text or '').strip()[:300]
    if isinstance(corpo, dict):
        objeto = corpo.get('errorObject') or {}
        return str(
            corpo.get('mensagem') or corpo.get('error') or objeto.get('description') or corpo
        )[:300]
    return str(corpo)[:300]


class Cliente:
    def __init__(self, base_url, origem, transport=None):
        self.base_url = base_url.rstrip('/') + '/'
        self.origem = origem
        self._http = httpx.Client(
            timeout=TEMPO, transport=transport, follow_redirects=False,
            headers={'Origin': origem, 'Accept': 'application/json', 'User-Agent': 'NeuroDoc'},
        )

    def url_login(self, client_url):
        return str(httpx.URL(self.base_url + 'auth/login', params={'client_url': client_url}))

    def trocar_sessao(self, session_id):
        """O `access_token` do `session_id` (uso único, 30 s). Não repete."""
        try:
            resposta = self._http.get(self.base_url + 'auth/token', params={'session_id': session_id})
        except httpx.TransportError as exc:
            # Trocar a sessão não gasta nada na Anvisa; perder a resposta
            # aqui só perde o login.
            raise Indisponivel('Não foi possível falar com o SNCR para concluir o login.') from exc
        if resposta.status_code == 401:
            raise SessaoInvalida('O login no Gov.br expirou antes de ser usado. Peça de novo.', 401)
        if resposta.status_code != 200:
            raise Indisponivel(f'O SNCR não concluiu o login ({resposta.status_code}).', resposta.status_code)
        try:
            token = resposta.json().get('access_token')
        except (ValueError, AttributeError):
            token = None
        if not token:
            raise Indisponivel('O SNCR respondeu ao login sem o token de acesso.', resposta.status_code)
        return token

    def pedir_bloco(self, token, tipo, conselho, uf, documento, cnpj):
        """Pede um bloco de RCE/RET. Devolve `inicio`, `fim`, `quantidade`, `mensagem`."""
        corpo = {'conselho': conselho, 'tipo': tipo, 'documento': documento, 'uf': uf, 'cnpj': cnpj}
        try:
            resposta = self._http.post(
                self.base_url + 'numeracoes/receita-especial-retencao', json=corpo,
                headers={'Authorization': f'Bearer {token}'},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise Indisponivel('O SNCR não respondeu. Nenhum pedido foi feito; tente mais tarde.') from exc
        except httpx.TransportError as exc:
            raise Incerto(
                'O pedido saiu, mas a resposta do SNCR não chegou. O bloco pode ter sido entregue: '
                'não peça de novo antes de conferir no portal do SNCR.'
            ) from exc
        status = resposta.status_code
        if status == 401:
            raise SessaoInvalida('O login no Gov.br expirou antes do pedido. Peça de novo.', 401)
        if 400 <= status < 500:
            raise Recusado(f'O SNCR recusou o pedido: {_mensagem(resposta)}', status)
        if status >= 500:
            raise Incerto(
                f'O SNCR respondeu com erro ({status}) depois de receber o pedido. O bloco pode ter '
                'sido entregue: não peça de novo antes de conferir no portal do SNCR.', status,
            )
        try:
            dados = resposta.json()
        except ValueError:
            dados = None
        if not isinstance(dados, dict) or not dados.get('inicio') or not dados.get('fim'):
            raise Incerto(
                'O SNCR aceitou o pedido, mas a resposta veio sem início e fim do bloco. Confira no '
                'portal do SNCR antes de pedir de novo.', status,
            )
        quantidade = dados.get('quantidade')
        try:
            quantidade = int(quantidade) if quantidade is not None else None
        except (TypeError, ValueError):
            quantidade = None
        return {
            'inicio': str(dados['inicio']).strip(), 'fim': str(dados['fim']).strip(),
            'quantidade': quantidade, 'mensagem': str(dados.get('mensagem') or '')[:300],
        }

    def fechar(self):
        self._http.close()

