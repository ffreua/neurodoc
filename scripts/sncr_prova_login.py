"""Prova de comunicação com o SNCR (Anvisa), ambiente de HOMOLOGAÇÃO.

Decisão D3 de `docs/sncr/DECISOES.md`. Prova, com o login Gov.br de
treinamento do próprio médico, os passos que a integração vai usar:

1. `auth/login?client_url=` → Gov.br → volta com `session_id`;
2. o **servidor** troca o `session_id` pelo `access_token` (decisão D4),
   mandando o mesmo `Origin` que iniciou o fluxo (Manual v5, nota de
   atualização da seção 2.2.4.3; lacuna L7 do relatório da Sprint 0);
3. o token é aceito numa chamada protegida **sem efeito persistente**: o
   pedido de RCE vai **sem o CNPJ**, campo obrigatório na especificação, e
   a resposta distingue "token recusado" (401) de "token aceito, pedido
   incompleto" (400). Nenhum bloco é pedido.

**Não toca no NeuroDoc** e não importa Django. Roda na máquina do médico:

    python scripts/sncr_prova_login.py --crm 134498 --uf SP

e abra http://localhost:8765/. **Nunca** mostra nem grava o token: a
evidência guarda status, tempos e os **nomes** das informações do token,
com o CPF mascarado.

Pré-requisito (Instruções de Integração v1.0, §2.1): cadastro feito uma
vez em https://sncr-treinamento.anvisa.gov.br/ com a conta Gov.br de
testes.
"""

import argparse
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE_HOMOLOGACAO = 'https://api-gateway.hmg.apps.anvisa.gov.br/api-sncr/api/v1/'


def _mascara_cpf(valor):
    digitos = ''.join(c for c in str(valor) if c.isdigit())
    return f'***.***.{digitos[6:9]}-**' if len(digitos) == 11 else '(não é CPF)'


def _claims(token):
    """As informações do token, sem a assinatura e sem expor valores."""
    try:
        meio = token.split('.')[1]
        dados = json.loads(base64.urlsafe_b64decode(meio + '=' * (-len(meio) % 4)))
    except (IndexError, ValueError):
        return {'formato': 'não é JWT'}
    saida = {'campos': sorted(dados)}
    for chave in ('preferred_username', 'sub', 'cpf'):
        if chave in dados:
            saida[f'{chave} (mascarado)'] = _mascara_cpf(dados[chave])
    if 'name' in dados:
        saida['nome'] = dados['name']
    if 'exp' in dados and 'iat' in dados:
        saida['validade_segundos'] = dados['exp'] - dados['iat']
    return saida


def _chamar(metodo, url, origem, token=None, corpo=None):
    cabecalhos = {'Origin': origem, 'Accept': 'application/json'}
    dados = None
    if token:
        cabecalhos['Authorization'] = f'Bearer {token}'
    if corpo is not None:
        dados = json.dumps(corpo).encode('utf-8')
        cabecalhos['Content-Type'] = 'application/json'
    pedido = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(pedido, timeout=20) as resposta:
            return resposta.status, resposta.read().decode('utf-8', 'replace'), time.monotonic() - inicio
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read().decode('utf-8', 'replace'), time.monotonic() - inicio


def montar(base, porta, crm, uf, evidencia):
    origem = f'http://localhost:{porta}'
    retorno = f'{origem}/retorno'

    class Pagina(BaseHTTPRequestHandler):
        def _html(self, corpo, status=200):
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(f'<!doctype html><meta charset="utf-8"><title>Prova SNCR</title>'
                             f'<body style="font-family:sans-serif;max-width:720px;margin:40px auto">'
                             f'{corpo}</body>'.encode('utf-8'))

        def log_message(self, *args):  # o token viaja na URL de retorno; não ir para o log
            pass

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == '/':
                return self._html(
                    '<h2>Prova de comunicação com o SNCR — homologação</h2>'
                    f'<p>CRM {crm}/{uf}. Ambiente de <b>treinamento</b> da Anvisa: nada aqui tem efeito '
                    'regulatório, e nenhum bloco de números é pedido.</p>'
                    '<p><a href="/iniciar" style="font-size:20px">Entrar com Gov.br (treinamento)</a></p>'
                )
            if url.path == '/iniciar':
                self.send_response(302)
                self.send_header('Location', base + 'auth/login?client_url=' + urllib.parse.quote(retorno, safe=''))
                self.end_headers()
                return None
            if url.path == '/retorno':
                return self._retorno(urllib.parse.parse_qs(url.query).get('session_id', [''])[0])
            return self._html('não encontrado', 404)

        def _retorno(self, session_id):
            registro = {'quando': datetime.now(timezone.utc).isoformat(), 'base': base, 'origem': origem,
                        'crm': crm, 'uf': uf, 'session_id_recebido': bool(session_id)}
            if not session_id:
                registro['resultado'] = 'o Gov.br voltou sem session_id'
                return self._fim(registro)
            status, corpo, tempo = _chamar(
                'GET', base + 'auth/token?session_id=' + urllib.parse.quote(session_id), origem,
            )
            registro['auth_token'] = {'status': status, 'ms': round(tempo * 1000)}
            token = None
            if status == 200:
                try:
                    token = json.loads(corpo).get('access_token')
                except ValueError:
                    pass
            if not token:
                registro['auth_token']['resposta'] = corpo[:300]
                registro['resultado'] = 'troca do session_id falhou'
                return self._fim(registro)
            registro['token'] = _claims(token)
            # Sem `cnpj` de propósito: obrigatório na especificação, então o
            # pedido é recusado na validação e nenhum bloco é gerado.
            status, corpo, tempo = _chamar(
                'POST', base + 'numeracoes/receita-especial-retencao', origem, token=token,
                corpo={'conselho': 'CRM', 'tipo': 'RCE', 'documento': crm, 'uf': uf},
            )
            registro['chamada_protegida_sem_cnpj'] = {'status': status, 'ms': round(tempo * 1000), 'resposta': corpo[:400]}
            registro['resultado'] = {
                401: 'token RECUSADO na chamada protegida',
                403: 'token aceito, acesso negado (ver resposta)',
                400: 'token ACEITO; pedido recusado por falta do CNPJ, como esperado',
            }.get(status, f'status inesperado {status} — ver resposta')
            return self._fim(registro)

        def _fim(self, registro):
            with open(evidencia, 'w', encoding='utf-8') as arquivo:
                json.dump(registro, arquivo, ensure_ascii=False, indent=2)
            texto = json.dumps(registro, ensure_ascii=False, indent=2)
            return self._html(f'<h2>Resultado</h2><pre style="white-space:pre-wrap">{texto}</pre>'
                              '<p>Pode fechar esta aba.</p>')

    return Pagina


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--crm', required=True)
    parser.add_argument('--uf', required=True)
    parser.add_argument('--porta', type=int, default=8765)
    parser.add_argument('--base', default=BASE_HOMOLOGACAO)
    parser.add_argument('--evidencia', default='sncr-prova-login.json')
    opcoes = parser.parse_args()
    if 'prd' in opcoes.base:
        raise SystemExit('Esta prova é só para HOMOLOGAÇÃO.')
    servidor = HTTPServer(('127.0.0.1', opcoes.porta), montar(opcoes.base, opcoes.porta, opcoes.crm, opcoes.uf, opcoes.evidencia))
    print(f'Abra http://localhost:{opcoes.porta}/ — evidência em {opcoes.evidencia}', flush=True)
    servidor.serve_forever()


if __name__ == '__main__':
    main()
