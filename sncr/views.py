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
from .models import BlocoNumeracao, Configuracao, EstadoNumero, NumeroSncr, PedidoNumeracao, TipoReceita
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
                'saldo': saldo(medico, tipo.value, config.ambiente),
                'impedimentos': fluxo.conferir(config, medico, tipo.value),
            })
        return render(request, 'sncr/painel.html', {
            'config': config, 'medico': medico, 'tipos': tipos,
            'blocos': BlocoNumeracao.objects.filter(medico=medico).order_by('-created_at')[:20],
            'pedidos': PedidoNumeracao.objects.filter(medico=medico).order_by('-created_at')[:20],
            'usados': NumeroSncr.objects.filter(medico=medico, estado=EstadoNumero.CONSUMIDO).count(),
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
            pedido, endereco = fluxo.iniciar(request, medico, tipo, request.access_context.tenant_id)
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
    """O médico registra o que viu no portal do SNCR sobre um pedido incerto."""

    def post(self, request, pedido_id):
        medico = _medico(request)
        if medico is None:
            raise Http404
        gerado = request.POST.get('resultado')
        if gerado not in ('gerado', 'nao_gerado'):
            raise Http404
        try:
            pedido = fluxo.resolver_incerto(
                pedido_id, medico, request.user.id, gerado=gerado == 'gerado',
                inicio=request.POST.get('inicio', ''), fim=request.POST.get('fim', ''),
            )
        except fluxo.PedidoRecusado as exc:
            messages.error(request, str(exc))
            return redirect('sncr:painel')
        messages.success(request, pedido.mensagem)
        return redirect('sncr:painel')
