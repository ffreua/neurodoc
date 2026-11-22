"""As telas do SNCR: o painel de numeração do médico, o pedido e o retorno.

Exigem `ISSUE_DOCUMENT` — quem emite receita — e um perfil profissional:
o bloco é do médico (`sncr/models.py`), e o painel mostra **só os dele**,
em qualquer clínica em que ele esteja. A secretária e o gestor não abrem.

O link do menu ("Numeração SNCR") aparece só com a integração ligada
(`base/context_processors.py`, `nd_sncr_ativo`); desligada — o padrão —,
a tela existe para o roteiro e para o teste real autorizado (decisão D8).
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render

from accounts.models import PhysicianProfile
from tenancy.permissions import Capability, CapabilityRequiredView

from . import fluxo
from .models import (
    BlocoNumeracao, Configuracao, EstadoNumero, EstadoPedido, NumeroSncr, PedidoNumeracao, TipoReceita,
    eh_notificacao,
)
from .numeracao import saldo


def _medico(request):
    if not request.access_context.has_role('doctor'):
        return None
    return PhysicianProfile.objects.filter(user=request.user).first()


class SncrView(CapabilityRequiredView):
    required_capability = Capability.ISSUE_DOCUMENT


class PainelView(SncrView):
    def get(self, request):
        medico = _medico(request)
        if medico is None:
            raise Http404
        config = Configuracao.carregar()
        tipos = []
        for tipo in TipoReceita:
            tipos.append({
                'codigo': tipo.value, 'rotulo': tipo.label,
                'notificacao': eh_notificacao(tipo.value),
                'saldo': saldo(medico, tipo.value, config.ambiente),
                'impedimentos': fluxo.conferir(config, medico, tipo.value),
            })
        return render(request, 'sncr/painel.html', {
            'config': config, 'medico': medico, 'tipos': tipos,
            **_lista_curta(medico),
            'usados': NumeroSncr.objects.filter(medico=medico, estado=EstadoNumero.CONSUMIDO).count(),
            'quantidades': fluxo.QUANTIDADES_DO_LOTE, 'lote_padrao': fluxo.LOTE_PADRAO,
            'notificacoes': [t.value for t in TipoReceita if eh_notificacao(t.value)],
        })


#: Quantos pedidos e blocos o painel mostra. O resto mora no histórico,
#: paginado: a lista crescia um item por tentativa de login no Gov.br e
#: empurrava o saldo, que é o que o médico abre a tela para ver.
PEDIDOS_NO_PAINEL = 6
BLOCOS_NO_PAINEL = 5
PEDIDOS_POR_PAGINA = 25


def _lista_curta(medico):
    """Os pedidos e blocos do painel: os incertos todos, e os mais recentes.

    O incerto não entra na conta do teto: é o único pedido que pede ação, e
    enquanto estiver aberto barra o pedido novo daquele tipo.
    """
    pedidos = PedidoNumeracao.objects.filter(medico=medico)
    incertos = list(pedidos.filter(estado=EstadoPedido.INCERTO).order_by('-created_at'))
    recentes = list(pedidos.exclude(estado=EstadoPedido.INCERTO).order_by('-created_at')[:PEDIDOS_NO_PAINEL])
    blocos = BlocoNumeracao.objects.filter(medico=medico)
    return {
        'pedidos_incertos': incertos,
        'pedidos': recentes,
        'pedidos_total': pedidos.count(),
        'pedidos_mostrados': len(incertos) + len(recentes),
        'blocos': list(blocos.order_by('-created_at')[:BLOCOS_NO_PAINEL]),
        'blocos_total': blocos.count(),
    }


class HistoricoView(SncrView):
    """Todos os pedidos de numeração do médico, paginados, e todos os blocos."""

    def get(self, request):
        from django.core.paginator import Paginator

        medico = _medico(request)
        if medico is None:
            raise Http404
        pedidos = PedidoNumeracao.objects.filter(medico=medico).order_by('-created_at')
        return render(request, 'sncr/historico.html', {
            'medico': medico,
            'pedidos': Paginator(pedidos, PEDIDOS_POR_PAGINA).get_page(request.GET.get('page')),
            'blocos': BlocoNumeracao.objects.filter(medico=medico).order_by('-created_at'),
            'notificacoes': [t.value for t in TipoReceita if eh_notificacao(t.value)],
        })


class PedirView(SncrView):
    """Cria o pedido e leva o médico ao Gov.br — por uma página, não por redirect.

    O POST não pode responder com o redirecionamento para a Anvisa: a CSP
    aplicada em produção tem `form-action 'self'`, e o navegador confere
    essa diretiva em **cada** salto da navegação que nasceu do envio do
    formulário — a API do SNCR, o Keycloak da Anvisa e o Gov.br. O envio
    seria recusado no primeiro salto, sem chegar ao login, e nenhum roteiro
    veria isso: o cliente de teste do Django não aplica CSP. Abrir uma
    exceção para três domínios de terceiros em `form-action` amarraria a
    política ao caminho interno do login da Anvisa, que muda sem aviso.

    A página intermediária começa uma navegação nova (um link), que a CSP
    não restringe.
    """

    def post(self, request, tipo):
        if tipo not in TipoReceita.values:
            raise Http404
        medico = _medico(request)
        if medico is None:
            raise Http404
        try:
            pedido, endereco = fluxo.iniciar(
                request, medico, tipo, request.access_context.tenant_id,
                quantidade=request.POST.get('quantidade') if eh_notificacao(tipo) else None,
            )
        except fluxo.PedidoRecusado as exc:
            messages.error(request, str(exc))
            return redirect('sncr:painel')
        return render(request, 'sncr/entrar.html', {
            'pedido': pedido, 'endereco': endereco, 'config': Configuracao.carregar(),
        })


class RetornoView(SncrView):
    """O SNCR devolve o navegador aqui com `?session_id=` (uso único, 30 s)."""

    def get(self, request):
        try:
            pedido = fluxo.concluir(request, request.GET.get('session_id', ''))
        except fluxo.PedidoRecusado as exc:
            messages.error(request, str(exc))
            return redirect('sncr:painel')
        nivel = messages.success if pedido.estado == 'concluido' else messages.error
        nivel(request, pedido.mensagem)
        return redirect('sncr:painel')


class ConferirPedidoView(SncrView):
    """O médico registra o que viu no portal do SNCR sobre um pedido incerto.

    Na Notificação de Receita, em vez de conferir, ele dá o pedido por
    perdido (`resultado=perdido`, decisão I18).
    """

    def post(self, request, pedido_id):
        medico = _medico(request)
        if medico is None:
            raise Http404
        gerado = request.POST.get('resultado')
        if gerado not in ('gerado', 'nao_gerado', 'perdido'):
            raise Http404
        try:
            if gerado == 'perdido':
                pedido = fluxo.dar_por_perdido(pedido_id, medico, request.user.id)
                messages.success(request, pedido.mensagem)
                return redirect('sncr:painel')
            pedido = fluxo.resolver_incerto(
                pedido_id, medico, request.user.id, gerado=gerado == 'gerado',
                inicio=request.POST.get('inicio', ''), fim=request.POST.get('fim', ''),
            )
        except fluxo.PedidoRecusado as exc:
            messages.error(request, str(exc))
            return redirect('sncr:painel')
        messages.success(request, pedido.mensagem)
        return redirect('sncr:painel')
