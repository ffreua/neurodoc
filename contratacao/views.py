"""As três portas públicas da contratação: escolher, esperar, e o aviso da Asaas.

Nenhuma delas fala com a Asaas. A chave da API é do worker (CLAUDE.md §2):
a página grava o pedido e espera o link; o webhook grava o aviso e responde.
"""

import hmac
import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from audit.services import record_audit_event
from base.net import client_ip
from tenancy import contract
from tenancy.plans import PLANS, Periodicidade, brl, plan_config, preco_na_periodicidade

from . import servicos
from .forms import ContratarForm
from .models import Configuracao, Pedido, StatusPedido

logger = logging.getLogger(__name__)

#: Onde a sessão guarda os pedidos feitos neste navegador. É o que libera o
#: botão de criar a clínica na página do pedido: o endereço sozinho mostra o
#: estado, e o link de cadastro só aparece para quem pediu (ou no e-mail).
CHAVE_DA_SESSAO = 'contratacao_pedidos'

#: Teto do corpo do webhook. O maior aviso da Asaas tem poucos KB.
MAX_CORPO_WEBHOOK = 256 * 1024

#: Hosts para onde a página do pedido aceita mandar o navegador.
HOSTS_DO_CHECKOUT = ('asaas.com',)


def checkout_ligado():
    return Configuracao.carregar().ativo


def plano_contratavel(code):
    """Plano pago de tabela: nem o Gratuito, nem o Personalizado (combinado)."""
    config = PLANS.get(code)
    return bool(config) and not config.get('contact_only') and bool(config.get('price_monthly'))


class ContratarView(View):
    """`/contratar/<plano>/`: forma de pagamento, nome, e-mail, e para a Asaas."""

    LIMITE_POR_IP = 5
    JANELA_SEGUNDOS = 3600

    def _plano(self, plano):
        if not plano_contratavel(plano):
            raise Http404
        return plano

    def _contexto(self, plano, form):
        precos = {str(p): preco_na_periodicidade(plano, p) for p in Periodicidade}
        return {
            'form': form, 'plano': dict(plan_config(plano), code=plano),
            'precos': {k: {kk: brl(vv) if kk in ('pagamento', 'ano', 'mensal') else vv
                           for kk, vv in v.items()} for k, v in precos.items()},
            'contrato_versao': contract.VERSAO,
        }

    def get(self, request, plano):
        plano = self._plano(plano)
        if not checkout_ligado():
            return redirect(f"{reverse('onboarding:landing')}#planos")
        periodo = request.GET.get('periodo')
        inicial = {'periodicidade': periodo if periodo in Periodicidade.values else Periodicidade.ANUAL}
        return render(request, 'contratacao/contratar.html',
                      self._contexto(plano, ContratarForm(plano=plano, initial=inicial)))

    def post(self, request, plano):
        plano = self._plano(plano)
        if not checkout_ligado():
            return redirect(f"{reverse('onboarding:landing')}#planos")
        if (request.POST.get('website') or '').strip():
            return redirect(f"{reverse('onboarding:landing')}#planos")
        form = ContratarForm(request.POST, plano=plano)
        if not form.is_valid():
            return render(request, 'contratacao/contratar.html', self._contexto(plano, form), status=400)
        if self._excedeu_o_limite(request):
            form.add_error(None, 'Muitos pedidos a partir desta conexão agora há pouco. '
                                 'Tente de novo em uma hora, ou fale conosco pelo formulário de contato.')
            return render(request, 'contratacao/contratar.html', self._contexto(plano, form), status=429)
        dados = form.cleaned_data
        pedido = servicos.criar_pedido(
            plano, dados['periodicidade'], dados['nome'], dados['email'], ip=client_ip(request),
        )
        meus = list(request.session.get(CHAVE_DA_SESSAO, []))[-9:]
        request.session[CHAVE_DA_SESSAO] = meus + [str(pedido.id)]
        record_audit_event(
            None, None, 'contratacao.pedido_criado', object_type='pedido_contratacao',
            object_id=pedido.id, outcome='success', origin_ip=client_ip(request),
            integrity_metadata={'plano': plano, 'periodicidade': dados['periodicidade']},
        )
        return redirect('contratacao:pedido', pedido_id=pedido.id)

    def _excedeu_o_limite(self, request):
        """Falha **fechada**, como o botão do Gratuito: sem contagem, não abre pedido."""
        from django.core.cache import cache

        chave = f'contratar:{client_ip(request)}'
        try:
            cache.get_or_set(chave, 0, self.JANELA_SEGUNDOS)
            return cache.incr(chave) > self.LIMITE_POR_IP
        except Exception:  # noqa: BLE001
            return True


def _link_seguro(link):
    partes = urlsplit(link or '')
    host = (partes.hostname or '').lower()
    return partes.scheme == 'https' and any(host == h or host.endswith('.' + h) for h in HOSTS_DO_CHECKOUT)


class PedidoView(View):
    """`/contratar/pedido/<id>/`: a página que espera, leva à Asaas e recebe de volta.

    A Asaas devolve a pessoa para cá com `?retorno=pago|cancelado|expirado`.
    **O retorno não é prova de pagamento** (a documentação insiste nisso): ele
    só decide o que a página diz enquanto espera. Pago é quando o aviso
    `CHECKOUT_PAID` chegou e o worker o processou.
    """

    def get(self, request, pedido_id):
        pedido = get_object_or_404(Pedido, id=pedido_id)
        retorno = request.GET.get('retorno', '')
        meu = str(pedido.id) in request.session.get(CHAVE_DA_SESSAO, [])
        if (pedido.status == StatusPedido.AGUARDANDO and not retorno
                and _link_seguro(pedido.checkout_link)):
            return redirect(pedido.checkout_link)
        contexto = {
            'pedido': pedido, 'retorno': retorno, 'meu': meu,
            'plano': plan_config(pedido.plano)['label'],
            'periodicidade': Periodicidade(pedido.periodicidade).label.lower(),
            'valor': brl(pedido.valor_pagamento_centavos), 'ano': brl(pedido.valor_ano_centavos),
            'email_mascarado': _mascarar(pedido.email),
            'Status': StatusPedido,
        }
        esperando = (pedido.status == StatusPedido.PREPARANDO
                     or (pedido.status == StatusPedido.AGUARDANDO and retorno == 'pago'))
        # Recarregar tem prazo: depois de meia hora sem mudança, a página para
        # de perguntar e diz que o link chegará por e-mail. O cartão em análise
        # de risco pode levar mais que isso, e a aba aberta não deve ficar
        # batendo no servidor a cada três segundos pela noite.
        recente = timezone.now() - pedido.updated_at < timezone.timedelta(minutes=30)
        contexto['atualizar'] = esperando and recente
        contexto['esperando_sem_recarregar'] = esperando and not recente
        if pedido.status == StatusPedido.PAGO and meu and pedido.convite_token_cifrado:
            contexto['link_cadastro'] = self._link_cadastro(pedido)
        return render(request, 'contratacao/pedido.html', contexto)

    def _link_cadastro(self, pedido):
        from base.crypto import SecretUnavailable, decrypt_secret
        from tenancy.invitations import peek_invitation

        try:
            token = decrypt_secret(pedido.convite_token_cifrado, pedido.convite_token_meta)
        except SecretUnavailable:
            return None
        # Convite já usado ou vencido não vira botão: a clínica já existe.
        if peek_invitation(token) is None:
            return None
        return reverse('onboarding:signup', args=[token])


def _mascarar(email):
    nome, _, dominio = (email or '').partition('@')
    if not dominio:
        return ''
    return f'{nome[:1]}{"•" * max(len(nome) - 1, 2)}@{dominio}'


@method_decorator(csrf_exempt, name='dispatch')
class WebhookAsaasView(View):
    """`/asaas/webhook/`: o aviso da Asaas. Confere o token, grava e responde 200.

    Sem CSRF porque quem posta é o servidor da Asaas, e no lugar dele vale o
    `asaas-access-token`, comparado em tempo constante. Responde **só** 200 no
    sucesso — a Asaas trata 201 e 204 como falha em parte da documentação, e
    15 falhas seguidas pausam a fila inteira.

    Grava e devolve; entender é do worker. A Asaas espera até 10 segundos, e
    um convite emitido aqui dentro, com o e-mail, poderia passar disso. O aviso
    repetido (mesmo `id`) responde 200 sem gravar de novo.
    """

    def post(self, request):
        esperado = getattr(settings, 'ASAAS_WEBHOOK_TOKEN', '') or ''
        recebido = request.headers.get('asaas-access-token', '')
        if not esperado or esperado == 'DISABLED':
            logger.warning('asaas webhook: token não configurado; aviso recusado')
            return HttpResponse(status=503)
        if not hmac.compare_digest(recebido.encode(), esperado.encode()):
            logger.warning('asaas webhook: token inválido (ip=%s)', client_ip(request))
            return HttpResponse(status=401)
        if len(request.body) > MAX_CORPO_WEBHOOK:
            return HttpResponse(status=413)
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return HttpResponse(status=400)
        if not isinstance(payload, dict):
            return HttpResponse(status=400)
        try:
            servicos.registrar_evento(payload)
        except ValueError:
            return HttpResponse(status=400)
        return HttpResponse(status=200)

    def get(self, request):
        raise Http404
