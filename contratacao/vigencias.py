"""A vigência do plano pago: o período, os avisos, a renovação e o Gratuito.

Desde a 1.47 (contrato 2.2) cada forma de pagamento é um período — doze, seis
ou três meses, pago de uma vez —, e **nada renova sozinho**. O caminho:

1. **Contratar** abre o primeiro período, no aceite (`abrir_do_aceite`).
2. **Trinta e quinze dias antes do fim**, o responsável recebe um e-mail
   (`avisar`, uma vez cada por período), e desde os trinta vê o aviso no alto
   de toda tela de `/app/` (cláusula 3.2).
3. **Renovar** é um botão em Organização → Plano e renovação, com **novo
   "li e aceito"** do contrato vigente (cláusula 3.2; gravado no pedido) e
   sem arrependimento (13.1). Ele grava um pedido com a clínica
   (`criar_pedido_de_renovacao`), o worker abre um checkout da Asaas como na
   contratação, e o aviso `CHECKOUT_PAID` abre o período seguinte
   (`abrir_da_renovacao`), emendado no fim do atual: quem paga dez dias antes
   não perde os dez dias.
4. **Vencer sem renovar** avisa o responsável e os superadministradores no
   dia, e **quinze dias depois** a clínica passa ao Gratuito (`rebaixar`,
   cláusula 3.4): nada é apagado, e os médicos além do limite perdem o papel,
   pela mesma regra do oitavo dia da degustação. A renovação paga depois
   devolve o plano e os papéis.

**O que não muda: as clínicas que já existiam** (decisão de 2026-11-13).
Nenhuma ganha período por migração, e sem período não há aviso nem passagem
ao Gratuito. O console registra o período de uma clínica antiga só quando se
decide que ela entra na regra.

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
responsável: quem paga é sempre quem pode, e quem aceita o contrato também.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import OrigemVigencia, Pedido, StatusPedido, Vigencia

logger = logging.getLogger(__name__)

#: Quantos dias antes do fim a faixa aparece e a renovação abre: o primeiro
#: dos dois avisos da cláusula 3.2.
JANELA_DIAS = 30
#: Os e-mails antes do fim, em dias (cláusula 3.2). Um de cada por período.
AVISOS_DIAS = (30, 15)
#: Dias depois do fim em que a clínica que não renovou passa ao Gratuito
#: (cláusula 3.4). Até lá, o plano continua o pago.
CARENCIA_DIAS = 15
#: Para onde vai quem não renova.
PLANO_DEPOIS = 'free'
#: Por quanto tempo a faixa continua depois da passagem ao Gratuito.
FAIXA_DEPOIS_DO_GRATUITO_DIAS = 30

#: Um pedido de renovação em aberto mais novo que isto é reaproveitado em vez
#: de abrir outro: dois cliques não podem virar duas cobranças pagas.
PEDIDO_EM_ABERTO_MINUTOS = 90


def ultimo_dia(fim):
    """O último dia em que o período vale, no dia de Brasília."""
    return timezone.localtime(fim - timezone.timedelta(seconds=1)).date()


def ultima(tenant_id):
    return Vigencia.objects.filter(tenant_id=tenant_id).order_by('-fim').first()


def gratuito_a_partir_de(vigencia):
    """O instante em que a clínica que não renovou passa ao Gratuito."""
    return vigencia.fim + timezone.timedelta(days=CARENCIA_DIAS)


def situacao(tenant, agora=None):
    """O estado da vigência da clínica, para o aviso e a tela. `None` se não há.

    Também `None` quando o plano da clínica já não é o do último período: o
    console trocou o plano (rebaixou, passou ao Personalizado), e o período
    pago deixou de descrever o que a clínica tem. A exceção é a clínica que
    passou ao Gratuito por não renovar: ela continua vendo o período e o
    botão Renovar, que a devolve ao plano pago.
    """
    if tenant is None:
        return None
    vigencia = ultima(tenant.id)
    if vigencia is None:
        return None
    rebaixada = vigencia.rebaixada_em is not None
    if rebaixada and tenant.plan != PLANO_DEPOIS:
        return None
    if not rebaixada and vigencia.plano != tenant.plan:
        return None
    agora = agora or timezone.now()
    dia = ultimo_dia(vigencia.fim)
    dias = (dia - timezone.localdate(agora)).days
    vencida = vigencia.fim <= agora
    vence_em_breve = not vencida and dias < JANELA_DIAS
    faixa = vence_em_breve or (vencida and not rebaixada) or (
        rebaixada and agora - vigencia.rebaixada_em
        < timezone.timedelta(days=FAIXA_DEPOIS_DO_GRATUITO_DIAS))
    return {
        'vigencia': vigencia, 'plano': vigencia.plano, 'ultimo_dia': dia, 'dias': max(dias, 0),
        'vencida': vencida, 'vence_em_breve': vence_em_breve, 'rebaixada': rebaixada,
        'gratuito_em': timezone.localtime(gratuito_a_partir_de(vigencia)).date(),
        'renovavel': vencida or dias < JANELA_DIAS, 'faixa': faixa,
    }


def renovacao_disponivel(tenant, agora=None):
    """Se o botão Renovar aparece: na janela, em plano de tabela, com o checkout ligado."""
    from .views import checkout_ligado, plano_contratavel

    estado = situacao(tenant, agora)
    return bool(estado and estado['renovavel'] and plano_contratavel(estado['plano'])
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
    anterior = ultima(tenant.id)
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
    if anterior is not None and pedido.plano == anterior.plano:
        restabelecer(tenant, anterior, por=pedido.solicitado_por)
    return vigencia


def restabelecer(tenant, anterior, por=None):
    """Devolve o plano pago e os médicos a quem passou ao Gratuito por não renovar.

    Chamado com a linha da clínica travada, pela renovação paga e pelo
    registro no console. Só age se a clínica ainda está no Gratuito em que
    `rebaixar` a deixou: plano trocado no console nesse meio-tempo é decisão
    de gente, e não se desfaz daqui.
    """
    from audit.services import record_audit_event
    from tenancy.degustacao import devolver_medicos

    if anterior.rebaixada_em is None or tenant.plan != PLANO_DEPOIS:
        return False
    tenant.plan = anterior.plano
    tenant.save(update_fields=['plan', 'updated_at'])
    devolvidos = devolver_medicos(tenant, anterior.medicos_retirados)
    Vigencia.objects.filter(id=anterior.id).update(medicos_retirados=[])
    record_audit_event(
        por, tenant.id, 'contratacao.plano_restabelecido', object_type='tenant',
        object_id=tenant.id, outcome='success',
        integrity_metadata={'plano': anterior.plano, 'medicos_devolvidos': devolvidos},
    )
    return True


def rebaixar(vigencia_id, agora=None):
    """Passa ao Gratuito a clínica que não renovou em quinze dias (cláusula 3.4). Worker.

    Trava a linha da clínica e confere tudo de novo: a renovação paga entre a
    leitura e a trava abre um período novo, e então este já não é o último.
    O que passa do limite do Gratuito só impede o próximo cadastro, como em
    todo rebaixamento; os médicos além do limite perdem o papel (fica o mais
    antigo), pela regra do oitavo dia da degustação. Devolve `True` se foi
    este chamado que rebaixou.
    """
    from audit.services import record_audit_event
    from tenancy.degustacao import retirar_medicos_excedentes
    from tenancy.models import Tenant, TenantStatus

    agora = agora or timezone.now()
    with transaction.atomic():
        vigencia = Vigencia.objects.filter(id=vigencia_id).first()
        if vigencia is None:
            return False
        tenant = Tenant.objects.select_for_update().filter(id=vigencia.tenant_id).first()
        vigencia = Vigencia.objects.select_for_update().get(id=vigencia_id)
        if (tenant is None or tenant.status == TenantStatus.CLOSED
                or vigencia.rebaixada_em is not None or tenant.plan != vigencia.plano
                or gratuito_a_partir_de(vigencia) > agora
                or ultima(tenant.id).id != vigencia.id):
            return False
        retirados = retirar_medicos_excedentes(tenant, PLANO_DEPOIS)
        tenant.plan = PLANO_DEPOIS
        tenant.save(update_fields=['plan', 'updated_at'])
        vigencia.rebaixada_em = agora
        vigencia.medicos_retirados = retirados
        vigencia.save(update_fields=['rebaixada_em', 'medicos_retirados', 'updated_at'])
        record_audit_event(
            None, tenant.id, 'contratacao.passou_ao_gratuito', object_type='vigencia',
            object_id=vigencia.id, outcome='success', integrity_metadata={
                'de': vigencia.plano, 'para': PLANO_DEPOIS,
                'fim': vigencia.fim.isoformat(), 'medicos_retirados': len(retirados),
                'vinculos_suspensos': sum(1 for r in retirados if r['suspenso']),
            },
        )
    return True


def registrar_no_console(tenant, usuario, periodicidade, inicio, valor_centavos=None, nota=''):
    """Período registrado à mão: pagamento por Pix ou transferência, ou clínica antiga.

    `inicio` é uma data; o período começa à meia-noite de Brasília dela.
    """
    from datetime import datetime, time

    from tenancy.contracts import somar_meses
    from tenancy.plans import meses_da_periodicidade

    from tenancy.models import Tenant

    comeco = timezone.make_aware(datetime.combine(inicio, time.min))
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(id=tenant.id)
        anterior = ultima(tenant.id)
        # A clínica que passou ao Gratuito por não renovar volta ao plano do
        # período anterior, com os médicos.
        rebaixada = bool(anterior and anterior.rebaixada_em and tenant.plan == PLANO_DEPOIS)
        vigencia = Vigencia.objects.create(
            tenant=tenant, plano=anterior.plano if rebaixada else tenant.plan,
            periodicidade=periodicidade, inicio=comeco,
            fim=somar_meses(comeco, meses_da_periodicidade(periodicidade)),
            valor_centavos=valor_centavos, origem=OrigemVigencia.CONSOLE,
            registrado_por=usuario, nota=(nota or '')[:255],
        )
        if rebaixada:
            restabelecer(tenant, anterior, por=usuario)
    return vigencia


# ------------------------------------------------------------------ renovar

def pedido_em_aberto(tenant_id):
    limite = timezone.now() - timezone.timedelta(minutes=PEDIDO_EM_ABERTO_MINUTOS)
    return (Pedido.objects.filter(
        tenant_id=tenant_id, status__in=(StatusPedido.PREPARANDO, StatusPedido.AGUARDANDO),
        created_at__gte=limite,
    ).order_by('-created_at').first())


def criar_pedido_de_renovacao(tenant, usuario, periodicidade, ip=None, user_agent='',
                              poderes_declarados=False):
    """O pedido da renovação, com o preço de hoje, a clínica e o aceite.

    O plano é o do último período — o mesmo quando a clínica já passou ao
    Gratuito por não renovar. O aceite (cláusula 3.2 da 2.2) é gravado aqui,
    no clique de quem leu: a versão, o hash e o texto inteiro do contrato em
    vigor, como no cadastro.
    """
    from tenancy import contract
    from tenancy.contracts import sha_do_texto

    from . import servicos

    estado = situacao(tenant)
    plano = estado['plano'] if estado else tenant.plan
    nome = f'{usuario.first_name} {usuario.last_name}'.strip() or usuario.email
    return servicos.criar_pedido(
        plano, periodicidade, nome, usuario.email, ip=ip, tenant=tenant, usuario=usuario,
        aceite_em=timezone.now(), aceite_sha256=sha_do_texto(),
        aceite_texto=contract.texto_simples(), aceite_user_agent=(user_agent or '')[:255],
        poderes_declarados=bool(poderes_declarados),
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


def _nome(tenant):
    return tenant.trade_name or tenant.legal_name


def _texto_antes(tenant, estado):
    from tenancy.plans import plan_label

    ultimo = estado['ultimo_dia'].strftime('%d/%m/%Y')
    return (
        f'O plano {plan_label(estado["plano"])} da {_nome(tenant)} vale até {ultimo}.\n\n'
        'Não há renovação automática. Para continuar no plano, renove pelo próprio '
        'NeuroDoc, em Organização → Plano e renovação: escolha o período (12, 6 ou '
        '3 meses), aceite o contrato e pague por Pix ou cartão:\n\n'
        f'{url_da_tela()}\n\n'
        'O novo período começa no dia seguinte ao fim do atual: renovar antes não '
        'encurta nada. Na renovação não há prazo de arrependimento (cláusula 13.1).\n\n'
        f'Sem renovação, a clínica passa ao plano Gratuito em '
        f'{estado["gratuito_em"]:%d/%m/%Y}, quinze dias depois do fim (cláusula 3.4).\n\n'
        'Se a clínica tem uma condição combinada conosco, responda a este e-mail em vez '
        'de pagar pelo sistema.\n\nEquipe NeuroDoc'
    )


def _texto_vencido(tenant, estado):
    from tenancy.plans import plan_label

    ultimo = estado['ultimo_dia'].strftime('%d/%m/%Y')
    return (
        f'O plano {plan_label(estado["plano"])} da {_nome(tenant)} venceu em {ultimo}, '
        'sem renovação.\n\n'
        f'Até {estado["gratuito_em"]:%d/%m/%Y} nada muda. Se não houver renovação até '
        'lá, a clínica passa ao plano Gratuito (cláusula 3.4 do contrato): nada é '
        'apagado, mas valem os limites do Gratuito, e os médicos além do limite perdem '
        'o papel médico até a renovação. Para continuar no plano, renove em '
        f'Organização → Plano e renovação:\n\n{url_da_tela()}\n\n'
        'Este é o aviso prévio de que trata a cláusula 5.2 do contrato.\n\n'
        'Equipe NeuroDoc'
    )


def _texto_gratuito(tenant, vigencia):
    from tenancy.plans import plan_label

    retirados = len(vigencia.medicos_retirados or [])
    medicos = (f' {retirados} vínculo{"s" if retirados != 1 else ""} perdeu o papel médico '
               '(fica o mais antigo).' if retirados else '')
    return (
        f'O plano {plan_label(vigencia.plano)} da {_nome(tenant)} venceu em '
        f'{ultimo_dia(vigencia.fim):%d/%m/%Y} e não foi renovado em quinze dias. Conforme '
        'a cláusula 3.4 do contrato, a clínica passou hoje ao plano Gratuito.\n\n'
        f'Nada foi apagado: os registros continuam acessíveis para consulta e exportação, '
        f'e o que passa dos limites do Gratuito só impede novos cadastros.{medicos}\n\n'
        'Renovar devolve o plano e os papéis retirados:\n\n'
        f'{url_da_tela()}\n\nEquipe NeuroDoc'
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
    """Uma vez por dia: os avisos de 30 e 15 dias, o de vencida e o Gratuito. Worker.

    Cada aviso sai uma vez por período (`aviso_30_em`, `aviso_15_em`,
    `aviso_vencido_em`). O carimbo é gravado mesmo que o e-mail falhe: a faixa
    na tela é o que importa, e um e-mail por dia ao responsável por causa de
    um SMTP fora do ar seria pior que um a menos. O período registrado já
    dentro dos quinze dias ganha só o aviso de quinze.

    **A passagem ao Gratuito também sai daqui**, na primeira rodada depois do
    décimo quinto dia — às 8h15, e não à meia-noite: ninguém perde o plano
    enquanto dorme, e quem pagou de madrugada já está renovado.
    """
    from tenancy.models import TenantStatus

    from .servicos import avisar_superadmins

    agora = agora or timezone.now()
    ultimas = (Vigencia.objects.order_by('tenant_id', '-fim').distinct('tenant_id')
               .values_list('id', flat=True))
    candidatas = Vigencia.objects.filter(id__in=list(ultimas), rebaixada_em__isnull=True).filter(
        fim__lte=agora + timezone.timedelta(days=JANELA_DIAS + 1),
    ).select_related('tenant')
    contagem = {'30': 0, '15': 0, 'vencida': 0, 'gratuito': 0}
    for vigencia in candidatas:
        tenant = vigencia.tenant
        if tenant.status == TenantStatus.CLOSED:
            continue
        estado = situacao(tenant, agora)
        if estado is None or estado['vigencia'].id != vigencia.id:
            continue
        if estado['vencida'] and gratuito_a_partir_de(vigencia) <= agora:
            if rebaixar(vigencia.id, agora):
                vigencia.refresh_from_db()
                _enviar_aos_responsaveis(tenant, 'Sua clínica passou ao plano Gratuito no NeuroDoc',
                                         _texto_gratuito(tenant, vigencia))
                avisar_superadmins(
                    'Clínica passou ao Gratuito por não renovar',
                    f'A clínica {_nome(tenant)} não renovou o plano {vigencia.plano}, vencido '
                    f'em {estado["ultimo_dia"]:%d/%m/%Y}, e passou hoje ao Gratuito '
                    f'(cláusula 3.4). Médicos retirados: {len(vigencia.medicos_retirados)}.',
                )
                contagem['gratuito'] += 1
        elif estado['vencida']:
            if vigencia.aviso_vencido_em is None:
                _enviar_aos_responsaveis(tenant, 'Seu plano no NeuroDoc venceu',
                                         _texto_vencido(tenant, estado))
                avisar_superadmins(
                    'Vigência vencida sem renovação',
                    f'O plano {vigencia.plano} da clínica {_nome(tenant)} venceu em '
                    f'{estado["ultimo_dia"]:%d/%m/%Y} sem renovação. O responsável foi '
                    f'avisado; sem pagamento, ela passa ao Gratuito em '
                    f'{estado["gratuito_em"]:%d/%m/%Y} (cláusula 3.4).',
                )
                Vigencia.objects.filter(id=vigencia.id).update(
                    aviso_vencido_em=agora, aviso_15_em=vigencia.aviso_15_em or agora,
                    aviso_30_em=vigencia.aviso_30_em or agora)
                contagem['vencida'] += 1
        elif estado['dias'] < AVISOS_DIAS[1]:
            if vigencia.aviso_15_em is None:
                _enviar_aos_responsaveis(
                    tenant, f'Seu plano no NeuroDoc vence em {estado["ultimo_dia"]:%d/%m/%Y}',
                    _texto_antes(tenant, estado))
                Vigencia.objects.filter(id=vigencia.id).update(
                    aviso_15_em=agora, aviso_30_em=vigencia.aviso_30_em or agora)
                contagem['15'] += 1
        elif estado['dias'] < AVISOS_DIAS[0]:
            if vigencia.aviso_30_em is None:
                _enviar_aos_responsaveis(
                    tenant, f'Seu plano no NeuroDoc vence em {estado["ultimo_dia"]:%d/%m/%Y}',
                    _texto_antes(tenant, estado))
                Vigencia.objects.filter(id=vigencia.id).update(aviso_30_em=agora)
                contagem['30'] += 1
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
        f'{ultimo_dia(vigencia.fim):%d/%m/%Y}. Não há renovação automática: trinta e '
        'quinze dias antes do fim, avisaremos de novo.\n\n'
        f'Contrato de adesão aceito na renovação: versão {pedido.contrato_versao}, em '
        f'{timezone.localtime(pedido.aceite_em or pedido.created_at):%d/%m/%Y %H:%M} '
        '(texto em /contrato/). Na renovação não há prazo de arrependimento '
        '(cláusula 13.1).\n\n'
        f'Plano e renovação: {url_da_tela()}\n\nEquipe NeuroDoc'
    )
    try:
        send_email(pedido.email, 'Renovação confirmada no NeuroDoc', corpo)
    except Exception:  # noqa: BLE001
        logger.warning('vigencia: e-mail da renovação falhou (pedido=%s)', pedido_id, exc_info=True)
        return False
    Pedido.objects.filter(id=pedido_id).update(email_enviado_em=timezone.now())
    return True
