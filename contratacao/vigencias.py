"""A vigência do plano pago: o período, o aviso de vencimento e a renovação.

Desde a 1.47 (contrato 2.2) cada forma de pagamento é um período — doze, seis
ou três meses, pago de uma vez —, e **nada renova sozinho**. O caminho:

1. **Contratar** abre o primeiro período, no aceite (`abrir_do_aceite`).
2. **Quinze dias antes do fim**, o responsável vê o aviso no alto de toda tela
   de `/app/` e recebe um e-mail (`avisar`, uma vez por período).
3. **Renovar** é um botão em Organização → Plano e renovação. Ele grava um
   pedido com a clínica (`criar_pedido_de_renovacao`), o worker abre um
   checkout da Asaas como na contratação, e o aviso `CHECKOUT_PAID` abre o
   período seguinte (`abrir_da_renovacao`), emendado no fim do atual: quem
   paga dez dias antes não perde os dez dias.
4. **Vencer sem renovar** avisa o responsável e os superadministradores, e
   **não** rebaixa nem suspende — a cláusula 5 do contrato pede aviso antes
   de restringir. O console decide, como já decide estorno e atraso.

**Por que um checkout gerado no clique, e não um link de cobrança mandado
por e-mail.** Estudamos os três caminhos da API (2026-11-13). O *link de
pagamentos* da Asaas é anônimo e reutilizável — feito para muitos pagadores —,
e não diz de que clínica veio o dinheiro. A *cobrança* (`/v3/payments`) exige
criar o cliente na Asaas com o CNPJ e o nome da clínica mandados daqui, o que
o Anexo II do contrato não prevê (hoje a Asaas recebe os dados só da página
dela), e ninguém a testou contra a conta real. O *checkout* é o que a 1.46 já
abre e já foi provado em produção, e é casado pelo `checkout.id` que fica
gravado no pedido. Ele vence em uma hora — e por isso é gerado na hora do
clique, e o e-mail leva à tela de renovação, que exige estar logado como
responsável: quem paga é sempre quem pode.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import OrigemVigencia, Pedido, StatusPedido, Vigencia

logger = logging.getLogger(__name__)

#: Quantos dias antes do fim o aviso aparece e a renovação abre.
JANELA_DIAS = 15

#: Um pedido de renovação em aberto mais novo que isto é reaproveitado em vez
#: de abrir outro: dois cliques não podem virar duas cobranças pagas.
PEDIDO_EM_ABERTO_MINUTOS = 90


def ultimo_dia(fim):
    """O último dia em que o período vale, no dia de Brasília."""
    return timezone.localtime(fim - timezone.timedelta(seconds=1)).date()


def ultima(tenant_id):
    return Vigencia.objects.filter(tenant_id=tenant_id).order_by('-fim').first()


def situacao(tenant, agora=None):
    """O estado da vigência da clínica, para o aviso e a tela. `None` se não há.

    Também `None` quando o plano da clínica já não é o do último período: o
    console trocou o plano (rebaixou, passou ao Personalizado), e o período
    pago deixou de descrever o que a clínica tem.
    """
    if tenant is None:
        return None
    vigencia = ultima(tenant.id)
    if vigencia is None or vigencia.plano != tenant.plan:
        return None
    agora = agora or timezone.now()
    dia = ultimo_dia(vigencia.fim)
    dias = (dia - timezone.localdate(agora)).days
    vencida = vigencia.fim <= agora
    return {
        'vigencia': vigencia, 'ultimo_dia': dia, 'dias': max(dias, 0),
        'vencida': vencida, 'vence_em_breve': not vencida and dias < JANELA_DIAS,
        'renovavel': vencida or dias < JANELA_DIAS,
    }


def renovacao_disponivel(tenant, agora=None):
    """Se o botão Renovar aparece: na janela, em plano de tabela, com o checkout ligado."""
    from .views import checkout_ligado, plano_contratavel

    estado = situacao(tenant, agora)
    return bool(estado and estado['renovavel'] and plano_contratavel(tenant.plan)
                and checkout_ligado())


# ------------------------------------------------------------------ abrir

def abrir_do_aceite(aceite, pedido=None):
    """O primeiro período, no aceite do plano pago. Dentro da transação do cadastro.

    Só o plano com preço e periodicidade tem período: o Gratuito, a
    degustação (que adere ao Gratuito) e o Personalizado não. `pedido` é o da
    página de vendas, quando a clínica nasceu de um pagamento.
    """
    if not aceite.price_payment_cents or not aceite.periodicidade:
        return None
    if pedido is not None and (pedido.status != StatusPedido.PAGO
                               or Vigencia.objects.filter(pedido=pedido).exists()):
        pedido = None
    return Vigencia.objects.create(
        tenant_id=aceite.tenant_id, plano=aceite.plan, periodicidade=aceite.periodicidade,
        inicio=aceite.created_at, fim=aceite.expires_at,
        valor_centavos=pedido.valor_pagamento_centavos if pedido else aceite.price_payment_cents,
        origem=OrigemVigencia.ACEITE, aceite=aceite, pedido=pedido,
    )


def _proximo_periodo(tenant_id, periodicidade, agora):
    """Início e fim do período seguinte: emendado no fim do atual, ou a partir de agora."""
    from tenancy.contracts import somar_meses
    from tenancy.plans import meses_da_periodicidade

    anterior = ultima(tenant_id)
    inicio = max(agora, anterior.fim) if anterior else agora
    return inicio, somar_meses(inicio, meses_da_periodicidade(periodicidade))


def abrir_da_renovacao(pedido):
    """O período pago por uma renovação. Worker, dentro da transação do aviso.

    Trava a linha da clínica: dois avisos de pagamento processados ao mesmo
    tempo emendam um período depois do outro, em vez de dois no mesmo lugar.
    Dois pagamentos são dois períodos — pago é pago — e o console é avisado.
    """
    from audit.services import record_audit_event
    from tenancy.models import Tenant

    tenant = Tenant.objects.select_for_update().get(id=pedido.tenant_id)
    existente = Vigencia.objects.filter(pedido=pedido).first()
    if existente is not None:
        return existente
    inicio, fim = _proximo_periodo(tenant.id, pedido.periodicidade, timezone.now())
    vigencia = Vigencia.objects.create(
        tenant=tenant, plano=pedido.plano, periodicidade=pedido.periodicidade,
        inicio=inicio, fim=fim, valor_centavos=pedido.valor_pagamento_centavos,
        origem=OrigemVigencia.RENOVACAO, pedido=pedido, registrado_por=pedido.solicitado_por,
    )
    record_audit_event(
        None, tenant.id, 'contratacao.renovado', object_type='vigencia', object_id=vigencia.id,
        outcome='success', integrity_metadata={
            'plano': pedido.plano, 'periodicidade': pedido.periodicidade,
            'valor_centavos': pedido.valor_pagamento_centavos, 'pedido': str(pedido.id),
            'fim': fim.isoformat(),
        },
    )
    return vigencia


def registrar_no_console(tenant, usuario, periodicidade, inicio, valor_centavos=None, nota=''):
    """Período registrado à mão: pagamento por Pix ou transferência, ou clínica antiga.

    `inicio` é uma data; o período começa à meia-noite de Brasília dela.
    """
    from datetime import datetime, time

    from tenancy.contracts import somar_meses
    from tenancy.plans import meses_da_periodicidade

    comeco = timezone.make_aware(datetime.combine(inicio, time.min))
    return Vigencia.objects.create(
        tenant=tenant, plano=tenant.plan, periodicidade=periodicidade, inicio=comeco,
        fim=somar_meses(comeco, meses_da_periodicidade(periodicidade)),
        valor_centavos=valor_centavos, origem=OrigemVigencia.CONSOLE,
        registrado_por=usuario, nota=(nota or '')[:255],
    )


# ------------------------------------------------------------------ renovar

def pedido_em_aberto(tenant_id):
    limite = timezone.now() - timezone.timedelta(minutes=PEDIDO_EM_ABERTO_MINUTOS)
    return (Pedido.objects.filter(
        tenant_id=tenant_id, status__in=(StatusPedido.PREPARANDO, StatusPedido.AGUARDANDO),
        created_at__gte=limite,
    ).order_by('-created_at').first())


def criar_pedido_de_renovacao(tenant, usuario, periodicidade, ip=None):
    """O pedido da renovação, com o preço do catálogo de hoje e a clínica."""
    from . import servicos

    nome = f'{usuario.first_name} {usuario.last_name}'.strip() or usuario.email
    return servicos.criar_pedido(
        tenant.plan, periodicidade, nome, usuario.email, ip=ip, tenant=tenant, usuario=usuario,
    )


# ------------------------------------------------------------------ avisos

def url_da_tela():
    return settings.PUBLIC_BASE_URL.rstrip('/') + reverse('tenancy:plano')


def _responsaveis(tenant_id):
    from tenancy.models import Membership, MembershipStatus, Role

    return list(
        Membership.objects.filter(tenant_id=tenant_id, status=MembershipStatus.ACTIVE,
                                  roles__contains=[Role.OWNER])
        .exclude(user__email='').values_list('user__email', flat=True)
    )


def _texto_antes(tenant, estado):
    from tenancy.plans import plan_label

    ultimo = estado['ultimo_dia'].strftime('%d/%m/%Y')
    return (
        f'O plano {plan_label(tenant.plan)} da {tenant.trade_name or tenant.legal_name} '
        f'vale até {ultimo}.\n\n'
        'Não há renovação automática. Para continuar no plano, renove pelo próprio '
        'NeuroDoc, em Organização → Plano e renovação, escolhendo o período (12, 6 ou '
        '3 meses) e pagando por Pix ou cartão:\n\n'
        f'{url_da_tela()}\n\n'
        'O novo período começa no dia seguinte ao fim do atual: renovar antes não '
        'encurta nada.\n\n'
        'Se a clínica tem uma condição combinada conosco, responda a este e-mail em vez '
        'de pagar pelo sistema.\n\nEquipe NeuroDoc'
    )


def _texto_vencido(tenant, estado):
    from tenancy.plans import plan_label

    ultimo = estado['ultimo_dia'].strftime('%d/%m/%Y')
    return (
        f'O plano {plan_label(tenant.plan)} da {tenant.trade_name or tenant.legal_name} '
        f'venceu em {ultimo}, sem renovação.\n\n'
        'Nada foi apagado nem bloqueado. Para continuar no plano, renove em '
        f'Organização → Plano e renovação:\n\n{url_da_tela()}\n\n'
        'Se não pretende renovar, responda a este e-mail: combinamos a passagem ao '
        'plano Gratuito e a exportação dos dados (cláusula 14 do contrato), sem '
        'perder nada do que foi registrado.\n\nEquipe NeuroDoc'
    )


def _enviar_aos_responsaveis(tenant, assunto, corpo):
    from communications.email import send_email

    enviados = 0
    for email in _responsaveis(tenant.id):
        try:
            # Pelo remetente da instalação, e não pelo da clínica: é a
            # ProntDoc falando com quem a contratou.
            send_email(email, assunto, corpo)
            enviados += 1
        except Exception:  # noqa: BLE001 — o aviso na tela continua; o carimbo diz se saiu
            logger.warning('vigencia: e-mail ao responsável falhou (tenant=%s)', tenant.id,
                           exc_info=True)
    return enviados


def avisar(agora=None):
    """Uma vez por dia: o aviso de quinze dias antes e o de vencida. Worker.

    Cada aviso sai uma vez por período (`aviso_antes_em`, `aviso_vencido_em`).
    O carimbo é gravado mesmo que o e-mail falhe: o aviso na tela é o que
    importa, e um e-mail por dia ao responsável por causa de um SMTP fora do
    ar seria pior que um a menos.
    """
    from tenancy.models import Tenant, TenantStatus

    from .servicos import avisar_superadmins

    agora = agora or timezone.now()
    ultimas = (Vigencia.objects.order_by('tenant_id', '-fim').distinct('tenant_id')
               .values_list('id', flat=True))
    candidatas = Vigencia.objects.filter(id__in=list(ultimas)).filter(
        fim__lte=agora + timezone.timedelta(days=JANELA_DIAS + 1),
    ).select_related('tenant')
    contagem = {'antes': 0, 'vencida': 0}
    for vigencia in candidatas:
        tenant = vigencia.tenant
        if tenant.status == TenantStatus.CLOSED:
            continue
        estado = situacao(tenant, agora)
        if estado is None or estado['vigencia'].id != vigencia.id:
            continue
        if estado['vencida'] and vigencia.aviso_vencido_em is None:
            _enviar_aos_responsaveis(tenant, 'Seu plano no NeuroDoc venceu',
                                     _texto_vencido(tenant, estado))
            avisar_superadmins(
                'Vigência vencida sem renovação',
                f'O plano {vigencia.plano} da clínica {tenant.trade_name or tenant.legal_name} '
                f'venceu em {estado["ultimo_dia"]:%d/%m/%Y} sem renovação.\n\nNada foi '
                'suspenso nem rebaixado: a cláusula 5 do contrato pede aviso antes de '
                'restringir. O responsável foi avisado por e-mail. Decida no console.',
            )
            Vigencia.objects.filter(id=vigencia.id).update(aviso_vencido_em=agora,
                                                            aviso_antes_em=vigencia.aviso_antes_em or agora)
            contagem['vencida'] += 1
        elif estado['vence_em_breve'] and vigencia.aviso_antes_em is None:
            _enviar_aos_responsaveis(
                tenant, f'Seu plano no NeuroDoc vence em {estado["ultimo_dia"]:%d/%m/%Y}',
                _texto_antes(tenant, estado),
            )
            Vigencia.objects.filter(id=vigencia.id).update(aviso_antes_em=agora)
            contagem['antes'] += 1
    return contagem


def avisar_renovacao_paga(pedido_id):
    """O e-mail a quem renovou, depois do commit. Falha não desfaz o período."""
    from communications.email import send_email
    from tenancy.plans import plan_label

    pedido = Pedido.objects.select_related('vigencia', 'tenant').filter(id=pedido_id).first()
    vigencia = getattr(pedido, 'vigencia', None) if pedido else None
    if vigencia is None:
        return False
    corpo = (
        f'Olá, {pedido.nome}.\n\n'
        f'Recebemos o pagamento da renovação do plano {plan_label(pedido.plano)} da '
        f'{pedido.tenant.trade_name or pedido.tenant.legal_name} '
        f'({pedido.valor_pagamento_brl}).\n\n'
        f'O novo período vai de {timezone.localtime(vigencia.inicio):%d/%m/%Y} a '
        f'{ultimo_dia(vigencia.fim):%d/%m/%Y}. Não há renovação automática: perto do fim, '
        'avisaremos de novo.\n\n'
        f'Plano e renovação: {url_da_tela()}\n\nEquipe NeuroDoc'
    )
    try:
        send_email(pedido.email, 'Renovação confirmada no NeuroDoc', corpo)
    except Exception:  # noqa: BLE001
        logger.warning('vigencia: e-mail da renovação falhou (pedido=%s)', pedido_id, exc_info=True)
        return False
    Pedido.objects.filter(id=pedido_id).update(email_enviado_em=timezone.now())
    return True
