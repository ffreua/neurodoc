"""`/instalacao/contratacao/`: a chave do checkout, os pedidos e os avisos da Asaas.

**Assimétrica, como a do TISS e a do SNCR.** Desligar é um clique — é parar de
vender, e freio que pede código chega tarde. Ligar exige o código recente,
digitar a palavra, o motivo e **um contrato que preveja o pagamento pela
Asaas**: até a 2.0, a cláusula 4.3 dizia "PIX ou transferência bancária" e
"ausência de cobrança automática", e um aceite gravado nela contradiria o
cartão recorrente que o checkout cobra.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render

from ops.superadmin import SuperAdminView, _nav, _pede_codigo_de_novo

from .models import Configuracao, EventoAsaas, Pedido, StatusPedido

CONFIRMACAO_LIGAR = 'LIGAR'

#: A primeira versão do contrato de adesão que prevê o pagamento pela Asaas.
CONTRATO_MINIMO = '2.1'


def _versao(texto):
    try:
        return tuple(int(p) for p in str(texto).split('.'))
    except ValueError:
        return (0,)


def contrato_permite():
    from tenancy import contract

    return _versao(contract.VERSAO) >= _versao(CONTRATO_MINIMO)


class ContratacaoView(SuperAdminView):
    def get(self, request):
        from django.conf import settings

        from tenancy import contract

        pedidos = list(
            Pedido.objects.select_related('convite', 'convite__consumed_by')
            .prefetch_related('cobrancas').order_by('-created_at')[:100]
        )
        contexto = _nav('contratacao')
        token = getattr(settings, 'ASAAS_WEBHOOK_TOKEN', '') or ''
        contexto.update({
            'config': Configuracao.carregar(),
            'confirmacao': CONFIRMACAO_LIGAR,
            'contrato_versao': contract.VERSAO, 'contrato_minimo': CONTRATO_MINIMO,
            'contrato_permite': contrato_permite(),
            'token_configurado': bool(token) and token != 'DISABLED',
            'webhook_url': settings.PUBLIC_BASE_URL.rstrip('/') + '/asaas/webhook/',
            'pedidos': pedidos,
            'pagos': Pedido.objects.filter(status=StatusPedido.PAGO).count(),
            'eventos_com_erro': EventoAsaas.objects.filter(processado_em__isnull=True, tentativas__gt=0)[:20],
            'eventos_recentes': EventoAsaas.objects.order_by('-recebido_em')[:20],
        })
        return render(request, 'ops/superadmin/contratacao.html', contexto)

    def post(self, request):
        from audit.services import record_audit_event

        config = Configuracao.carregar()
        acao = request.POST.get('acao')
        motivo = ''
        if acao == 'desligar':
            config.ativo = False
            evento, aviso = 'ops.checkout_disabled', (
                'Checkout desligado: a página de vendas volta ao formulário de contato. '
                'Os avisos da Asaas continuam sendo recebidos.'
            )
        elif acao == 'ligar':
            pedido = _pede_codigo_de_novo(request, 'superadmin:contratacao')
            if pedido is not None:
                return pedido
            if not contrato_permite():
                messages.error(
                    request,
                    f'O contrato publicado é a versão {self._versao_publicada()}, que não prevê o '
                    f'pagamento pela Asaas. Publique a {CONTRATO_MINIMO} antes. Nada foi alterado.',
                )
                return redirect('superadmin:contratacao')
            if (request.POST.get('confirmacao') or '').strip() != CONFIRMACAO_LIGAR:
                messages.error(request, f'Para ligar, digite {CONFIRMACAO_LIGAR} no campo de '
                                        'confirmação. Nada foi alterado.')
                return redirect('superadmin:contratacao')
            motivo = (request.POST.get('motivo') or '').strip()
            if not motivo:
                messages.error(request, 'Escreva o motivo. Nada foi alterado.')
                return redirect('superadmin:contratacao')
            config.ativo = True
            evento, aviso = 'ops.checkout_enabled', (
                'Checkout ligado: os planos pagos da página de vendas passam a abrir o pagamento.'
            )
        else:
            raise Http404
        config.save()
        metadados = {'ativo': config.ativo}
        if motivo:
            metadados['motivo'] = motivo[:255]
        record_audit_event(
            request.user, None, evento, object_type='contratacao_configuracao',
            object_id=config.id, outcome='success', integrity_metadata=metadados,
        )
        messages.success(request, aviso)
        return redirect('superadmin:contratacao')

    @staticmethod
    def _versao_publicada():
        from tenancy import contract

        return contract.VERSAO
