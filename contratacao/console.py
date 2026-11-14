"""`/instalacao/contratacao/`: a chave do checkout, os pedidos, as vigências e os avisos.

**Assimétrica, como a do TISS e a do SNCR.** Desligar é um clique — é parar de
vender, e freio que pede código chega tarde. Ligar exige o código recente,
digitar a palavra, o motivo e **um contrato que preveja o pagamento pela
Asaas**: até a 2.0, a cláusula 4.3 dizia "PIX ou transferência bancária" e
"ausência de cobrança automática", e um aceite gravado nela contradiria o
cartão recorrente que o checkout cobra. Desde a 1.47 o mínimo é a **2.2**: o
checkout passou a vender o período (doze, seis ou três meses) em pagamento
único, e a 2.1 ainda diz que todo plano pago tem vigência de 12 meses.

**Vigências (1.47).** A lista mostra o último período de cada clínica que tem
um, e o formulário registra período à mão — quem pagou por Pix ou
transferência, ou a clínica anterior à 1.47, que não ganhou período por
migração (`contratacao/vigencias.py`).
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render

from ops.superadmin import SuperAdminView, _nav, _pede_codigo_de_novo

from tenancy.plans import Periodicidade

from .models import Configuracao, EventoAsaas, Pedido, StatusPedido, Vigencia

CONFIRMACAO_LIGAR = 'LIGAR'

#: A primeira versão do contrato de adesão que prevê o que o checkout vende:
#: o pagamento pela Asaas (2.1) e a vigência do período pago (2.2, 1.47).
CONTRATO_MINIMO = '2.2'


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
            'vigencias': _ultimas_vigencias(),
            'clinicas_pagas': _clinicas_com_plano_pago(),
            'periodicidades': Periodicidade.choices,
        })
        return render(request, 'ops/superadmin/contratacao.html', contexto)

    def post(self, request):
        from audit.services import record_audit_event

        config = Configuracao.carregar()
        acao = request.POST.get('acao')
        motivo = ''
        if acao == 'registrar_vigencia':
            return self._registrar_vigencia(request)
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

    def _registrar_vigencia(self, request):
        """Período registrado à mão. Pede o código, como as outras ações graves."""
        from datetime import date
        from decimal import Decimal, InvalidOperation

        from audit.services import record_audit_event
        from tenancy.models import Tenant

        from . import vigencias

        pedido = _pede_codigo_de_novo(request, 'superadmin:contratacao')
        if pedido is not None:
            return pedido
        escolhida = request.POST.get('tenant')
        tenant = Tenant.objects.filter(id=escolhida).first() if _uuid(escolhida) else None
        periodicidade = request.POST.get('periodicidade')
        try:
            inicio = date.fromisoformat(request.POST.get('inicio') or '')
        except ValueError:
            inicio = None
        valor = (request.POST.get('valor') or '').strip().replace('R$', '').strip()
        if ',' in valor:
            # Formato brasileiro: 1.680,00.
            valor = valor.replace('.', '').replace(',', '.')
        try:
            valor_centavos = int(Decimal(valor) * 100) if valor else None
        except InvalidOperation:
            valor_centavos = -1
        nota = (request.POST.get('nota') or '').strip()
        erro = None
        if tenant is None:
            erro = 'Escolha a clínica.'
        elif periodicidade not in Periodicidade.values:
            erro = 'Escolha o período.'
        elif inicio is None:
            erro = 'Informe a data de início.'
        elif valor_centavos is not None and valor_centavos < 0:
            erro = 'O valor não é um número válido.'
        elif not nota:
            erro = 'Escreva de onde vem o período (ex.: Pix recebido em 10/11).'
        if erro:
            messages.error(request, f'{erro} Nada foi registrado.')
            return redirect('superadmin:contratacao')
        vigencia = vigencias.registrar_no_console(
            tenant, request.user, periodicidade, inicio, valor_centavos, nota,
        )
        record_audit_event(
            request.user, tenant.id, 'ops.vigencia_registrada', object_type='vigencia',
            object_id=vigencia.id, outcome='success', integrity_metadata={
                'plano': vigencia.plano, 'periodicidade': periodicidade,
                'inicio': inicio.isoformat(), 'valor_centavos': valor_centavos,
                'nota': nota[:255],
            },
        )
        messages.success(request, f'Período registrado: {tenant.trade_name or tenant.legal_name}, '
                                  f'até {vigencia.ultimo_dia:%d/%m/%Y}.')
        return redirect('superadmin:contratacao')

    @staticmethod
    def _versao_publicada():
        from tenancy import contract

        return contract.VERSAO


def _uuid(texto):
    import uuid

    try:
        uuid.UUID(str(texto))
    except ValueError:
        return False
    return True


def _ultimas_vigencias():
    """O último período de cada clínica, do que vence primeiro ao que vence depois."""
    ultimas = (Vigencia.objects.order_by('tenant_id', '-fim').distinct('tenant_id')
               .values_list('id', flat=True))
    return list(Vigencia.objects.filter(id__in=list(ultimas)).select_related('tenant')
                .order_by('fim')[:200])


def _clinicas_com_plano_pago():
    from tenancy.models import Tenant, TenantStatus

    return list(Tenant.objects.exclude(plan='free').exclude(status=TenantStatus.CLOSED)
                .order_by('trade_name', 'legal_name').only('id', 'trade_name', 'legal_name', 'plan'))
