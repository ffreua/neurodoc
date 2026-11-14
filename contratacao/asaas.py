"""A conversa com a API da Asaas. Só o worker chega aqui.

A chave (`ASAAS_API_KEY`) é segredo de egresso e mora **só** no worker, como a
do SMS e a da IA (CLAUDE.md §2): o processo que atende o navegador não a tem.
Por isso a página de contratar não abre o checkout — ela grava o pedido, a
tarefa pede o checkout, e a página espera o link aparecer.

O que a documentação não dizia e só a API respondeu (2026-11-12, conta de
produção, checkouts criados e cancelados no mesmo minuto):

- `customerData` pela metade é recusado — a Asaas exige telefone e endereço
  completos. Sem ele, quem paga preenche na própria página da Asaas. Não o
  mandamos: é menos dado pessoal passando por aqui.
- `successUrl` com `localhost` é recusado ("O campo successUrl é inválido").
  O ambiente local não abre checkout de verdade; os roteiros simulam a Asaas.
- Não há `GET /v3/checkouts/{id}` (404). O estado do checkout só chega pelo
  webhook — por isso o webhook é obrigatório, e não um complemento.
- Pix exige uma chave Pix cadastrada na conta; sem ela, o checkout com `PIX`
  é recusado inteiro.
"""

from decimal import Decimal

import requests
from django.conf import settings

from base.version import VERSION
from tenancy.plans import PERIODICIDADES, Periodicidade, plan_label

TIMEOUT_SEGUNDOS = 20

#: Minutos que o link do checkout vale. Uma hora cobre quem vai buscar o
#: cartão na bolsa ou abrir o aplicativo do banco para o Pix.
MINUTOS_PARA_EXPIRAR = 60

#: Os eventos que o webhook assina. A ordem não importa; a lista é a que o
#: comando `asaas_webhook` grava na Asaas. `CHECKOUT_CREATED` não muda nada
#: aqui dentro, e está na lista por isso: criar e cancelar um checkout de
#: teste prova a entrega pela Cloudflare até o app sem ninguém pagar nada.
EVENTOS_DO_WEBHOOK = [
    'CHECKOUT_CREATED', 'CHECKOUT_PAID', 'CHECKOUT_CANCELED', 'CHECKOUT_EXPIRED',
    'SUBSCRIPTION_CREATED', 'SUBSCRIPTION_INACTIVATED', 'SUBSCRIPTION_DELETED',
    'PAYMENT_CREATED', 'PAYMENT_CONFIRMED', 'PAYMENT_RECEIVED', 'PAYMENT_OVERDUE',
    'PAYMENT_REFUNDED', 'PAYMENT_PARTIALLY_REFUNDED', 'PAYMENT_REFUND_IN_PROGRESS',
    'PAYMENT_CHARGEBACK_REQUESTED', 'PAYMENT_CHARGEBACK_DISPUTE',
    'PAYMENT_AWAITING_CHARGEBACK_REVERSAL', 'PAYMENT_DELETED',
    'PAYMENT_CREDIT_CARD_CAPTURE_REFUSED', 'PAYMENT_REPROVED_BY_RISK_ANALYSIS',
    'ACCESS_TOKEN_EXPIRING_SOON', 'ACCESS_TOKEN_DISABLED', 'ACCESS_TOKEN_EXPIRED',
]


class AsaasErro(Exception):
    """A Asaas respondeu e recusou. Repetir o mesmo pedido não resolve."""


class AsaasIndisponivel(Exception):
    """Rede, tempo esgotado, 5xx ou 429. Vale tentar de novo."""


def configurada():
    chave = getattr(settings, 'ASAAS_API_KEY', '') or ''
    return bool(chave) and chave != 'DISABLED'


def _cabecalhos():
    if not configurada():
        raise AsaasErro('A chave da API da Asaas não está configurada no worker.')
    return {
        'access_token': settings.ASAAS_API_KEY,
        'Content-Type': 'application/json',
        # Obrigatório para contas criadas desde 13/06/2024.
        'User-Agent': f'NeuroDoc/{VERSION}',
    }


def _url(caminho):
    return settings.ASAAS_BASE_URL.rstrip('/') + '/' + caminho.lstrip('/')


def chamar(metodo, caminho, corpo=None):
    try:
        resposta = requests.request(
            metodo, _url(caminho), json=corpo, headers=_cabecalhos(), timeout=TIMEOUT_SEGUNDOS,
        )
    except requests.RequestException as exc:
        raise AsaasIndisponivel(f'{type(exc).__name__} ao falar com a Asaas') from exc
    if resposta.status_code == 429 or resposta.status_code >= 500:
        raise AsaasIndisponivel(f'Asaas respondeu {resposta.status_code}')
    try:
        dados = resposta.json()
    except ValueError:
        dados = {}
    if resposta.status_code >= 400:
        erros = '; '.join(
            str(e.get('description') or e.get('code') or '') for e in (dados.get('errors') or [])
        )
        raise AsaasErro(f'Asaas respondeu {resposta.status_code}: {erros or "sem descrição"}')
    return dados


def reais(centavos):
    return (Decimal(int(centavos)) / 100).quantize(Decimal('0.01'))


def montar_checkout(pedido, url_do_pedido, hoje=None):
    """O corpo do `POST /v3/checkouts` de um pedido. Função pura, para o roteiro.

    Desde a 1.47 (contrato 2.2) as três formas são **pagamento único** do
    período — doze, seis ou três meses —, por Pix ou cartão, e nenhuma cria
    assinatura: nada se cobra sozinho depois. Até a 1.46 o semestral e o
    trimestral eram assinatura no cartão com `endDate` aos 12 meses; nenhuma
    chegou a ser aberta, porque o checkout nunca foi ligado com elas.

    `hoje` ficou na assinatura por compatibilidade com quem chama; não é usado.
    """
    periodicidade = Periodicidade(pedido.periodicidade)
    rotulo = plan_label(pedido.plano)
    vigencia = PERIODICIDADES[periodicidade]['vigencia']
    acao = 'Renovação do plano' if getattr(pedido, 'tenant_id', None) else 'Plano'
    descricao = f'{acao} {rotulo}, vigência de {vigencia}. Pagamento único, sem renovação automática.'
    return {
        'chargeTypes': ['DETACHED'],
        'billingTypes': ['PIX', 'CREDIT_CARD'],
        'minutesToExpire': MINUTOS_PARA_EXPIRAR,
        'externalReference': str(pedido.id),
        'callback': {
            'successUrl': f'{url_do_pedido}?retorno=pago',
            'cancelUrl': f'{url_do_pedido}?retorno=cancelado',
            'expiredUrl': f'{url_do_pedido}?retorno=expirado',
        },
        'items': [{
            'name': f'NeuroDoc {rotulo}'[:30],
            'description': descricao[:150],
            'quantity': 1,
            'value': float(reais(pedido.valor_pagamento_centavos)),
            'externalReference': f'{pedido.plano}:{pedido.periodicidade}',
        }],
    }


def criar_checkout(corpo):
    dados = chamar('POST', 'checkouts', corpo)
    if not dados.get('id'):
        raise AsaasErro('A Asaas não devolveu o identificador do checkout.')
    return dados


def cancelar_checkout(checkout_id):
    return chamar('POST', f'checkouts/{checkout_id}/cancel')


def link_do_checkout(dados):
    """O link que a resposta traz; se não vier, o formato da documentação."""
    return dados.get('link') or f'https://www.asaas.com/checkoutSession/show?id={dados["id"]}'
