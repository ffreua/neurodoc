"""Contratar um plano pago pela página de vendas, de ponta a ponta.

O caminho, e quem faz cada passo:

1. **app** — `criar_pedido`: grava o pedido com o preço do catálogo naquele
   instante e pede o checkout ao worker (depois do commit).
2. **worker** — `preparar_checkout`: abre o checkout na Asaas e grava o link.
   A página do pedido, que estava esperando, leva a pessoa até ele.
3. **app** — `registrar_evento`: a Asaas avisa pelo webhook; a porta confere o
   token, grava o aviso pela chave única do evento e responde 200.
4. **worker** — `processar_evento`: no `CHECKOUT_PAID`, emite o convite do
   plano pago (`tenancy.invitations`) e manda o link de cadastro por e-mail.
   Daí em diante é o cadastro de sempre, com o aceite do contrato de sempre.

**O pagamento não muda plano de clínica nenhuma.** Ele emite um convite, e é o
convite que cria a clínica no plano pago. Estorno e contestação chegam ao
console e por e-mail aos superadministradores, e **não** suspendem nada
sozinhos: a cláusula 5 do contrato pede aviso antes de restringir, e essa
decisão é de gente.

**A renovação (1.47) é o mesmo caminho com a clínica no pedido.** O
responsável clica em Renovar (`contratacao/vigencias.py`), o pedido nasce com
`tenant`, e no passo 4 o pagamento abre o período seguinte em vez de emitir
convite. Não muda o plano: renova o que a clínica tem.
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from . import asaas
from .models import Cobranca, EventoAsaas, Pedido, StatusPedido

logger = logging.getLogger(__name__)

#: Quantos dias o convite emitido pelo pagamento vale. Mais que os dois do
#: Gratuito: aqui houve pagamento, e o link pode ficar esperando no e-mail
#: enquanto a pessoa junta o CNPJ e decide quem será o responsável.
CONVITE_DIAS = 30

#: Tentativas de um aviso que falha antes de o alarme ir por e-mail.
TENTATIVAS_ANTES_DO_ALARME = 5

#: O que pede atenção de gente. Cada um chega uma vez por evento (a chave
#: única do `EventoAsaas` garante) e vira e-mail aos superadministradores.
EVENTOS_DE_ALERTA = {
    'PAYMENT_OVERDUE': 'Cobrança vencida sem pagamento',
    'PAYMENT_REFUNDED': 'Cobrança estornada',
    'PAYMENT_PARTIALLY_REFUNDED': 'Cobrança estornada em parte',
    'PAYMENT_REFUND_IN_PROGRESS': 'Estorno em andamento',
    'PAYMENT_CHARGEBACK_REQUESTED': 'Contestação (chargeback) aberta',
    'PAYMENT_CHARGEBACK_DISPUTE': 'Contestação (chargeback) em disputa',
    'PAYMENT_AWAITING_CHARGEBACK_REVERSAL': 'Contestação ganha, aguardando repasse',
    'PAYMENT_DELETED': 'Cobrança removida na Asaas',
    'PAYMENT_CREDIT_CARD_CAPTURE_REFUSED': 'Cartão recusado na cobrança',
    'PAYMENT_REPROVED_BY_RISK_ANALYSIS': 'Pagamento reprovado na análise de risco',
    'SUBSCRIPTION_INACTIVATED': 'Assinatura inativada',
    'SUBSCRIPTION_DELETED': 'Assinatura removida',
}

EVENTOS_DA_CHAVE = {
    'ACCESS_TOKEN_EXPIRING_SOON': 'A chave da API da Asaas vai expirar',
    'ACCESS_TOKEN_DISABLED': 'A chave da API da Asaas foi desativada',
    'ACCESS_TOKEN_EXPIRED': 'A chave da API da Asaas expirou',
}


# ------------------------------------------------------------------ pedido

def preco_do_pedido(plano, periodicidade):
    """O pagamento único do período, o equivalente no ano e quantas cobranças (1)."""
    from tenancy.plans import preco_na_periodicidade

    preco = preco_na_periodicidade(plano, periodicidade)
    if not preco or not preco['pagamento']:
        raise ValueError('Plano sem preço de tabela não se contrata pela página.')
    # Uma cobrança: desde a 1.47 o período é pago de uma vez (contrato 2.2).
    return preco['pagamento'], preco['ano'], 1


def criar_pedido(plano, periodicidade, nome, email, ip=None, tenant=None, usuario=None):
    """Grava o pedido e pede o checkout ao worker depois do commit.

    Com `tenant`, é a renovação de uma clínica que já existe (`vigencias`).
    """
    from tenancy import contract

    pagamento, ano, cobrancas = preco_do_pedido(plano, periodicidade)
    pedido = Pedido.objects.create(
        plano=plano, periodicidade=periodicidade,
        valor_pagamento_centavos=pagamento, valor_ano_centavos=ano,
        cobrancas_previstas=cobrancas, nome=nome.strip()[:150],
        email=email.strip().lower(), contrato_versao=contract.VERSAO, origem_ip=ip,
        tenant=tenant, solicitado_por=usuario,
    )
    transaction.on_commit(lambda: _enfileirar_checkout(pedido.id))
    return pedido


def _enfileirar_checkout(pedido_id):
    from .tasks import preparar_checkout_task

    try:
        preparar_checkout_task.delay(str(pedido_id))
    except Exception:  # noqa: BLE001 — sem fila, a varredura dá o pedido por falho
        logger.exception('contratacao: não enfileirou o checkout (pedido=%s)', pedido_id)


def url_do_pedido(pedido_id):
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    return base + reverse('contratacao:pedido', args=[pedido_id])


def preparar_checkout(pedido_id):
    """Abre o checkout na Asaas. Worker. `AsaasIndisponivel` sobe para a nova tentativa."""
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().filter(id=pedido_id).first()
        if pedido is None or pedido.status != StatusPedido.PREPARANDO or pedido.checkout_id:
            return pedido
        corpo = asaas.montar_checkout(pedido, url_do_pedido(pedido.id), timezone.localdate())
    try:
        dados = asaas.criar_checkout(corpo)
    except asaas.AsaasErro as exc:
        marcar_falha(pedido_id, str(exc))
        return Pedido.objects.get(id=pedido_id)
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(id=pedido_id)
        if pedido.status != StatusPedido.PREPARANDO:
            return pedido
        pedido.checkout_id = dados['id']
        pedido.checkout_link = asaas.link_do_checkout(dados)[:500]
        pedido.status = StatusPedido.AGUARDANDO
        pedido.save(update_fields=['checkout_id', 'checkout_link', 'status', 'updated_at'])
    return pedido


def marcar_falha(pedido_id, motivo):
    atualizados = Pedido.objects.filter(id=pedido_id, status=StatusPedido.PREPARANDO).update(
        status=StatusPedido.FALHOU, falha=motivo[:2000], updated_at=timezone.now(),
    )
    if atualizados:
        logger.warning('contratacao: checkout não abriu (pedido=%s): %s', pedido_id, motivo)
        avisar_superadmins(
            'O checkout de um pedido não abriu',
            f'A Asaas não abriu o pagamento do pedido {pedido_id}.\n\nMotivo: {motivo}\n\n'
            'Se o motivo for a chave Pix, a chave da API ou a conta, quem tentar contratar '
            'agora vai receber a mesma recusa. Para parar de oferecer o checkout enquanto '
            'isso é resolvido, desligue-o no console.',
        )
    return atualizados


# ------------------------------------------------------------------ webhook

def registrar_evento(payload):
    """Grava o aviso. Devolve `(evento, novo)`. App: nada além de banco."""
    event_id = str(payload.get('id') or '').strip()[:120]
    tipo = str(payload.get('event') or '').strip()[:60]
    if not event_id or not tipo:
        raise ValueError('aviso sem id ou sem tipo')
    try:
        with transaction.atomic():
            evento = EventoAsaas.objects.create(event_id=event_id, tipo=tipo, payload=payload)
    except IntegrityError:
        return EventoAsaas.objects.get(event_id=event_id), False
    transaction.on_commit(lambda: _enfileirar_evento(evento.id))
    return evento, True


def _enfileirar_evento(evento_id):
    from .tasks import processar_evento_task

    try:
        processar_evento_task.delay(evento_id)
    except Exception:  # noqa: BLE001 — a varredura de cinco em cinco minutos retoma
        logger.exception('contratacao: não enfileirou o aviso %s', evento_id)


def processar_evento(evento_id):
    """Entende um aviso, uma vez só. Worker."""
    with transaction.atomic():
        evento = EventoAsaas.objects.select_for_update().filter(id=evento_id).first()
        if evento is None or evento.processado_em:
            return evento
        try:
            with transaction.atomic():
                nota = _despachar(evento) or ''
        except Exception as exc:  # noqa: BLE001 — registrado e retomado pela varredura
            logger.exception('contratacao: aviso %s (%s) falhou', evento.event_id, evento.tipo)
            evento.tentativas += 1
            evento.erro = f'{type(exc).__name__}: {exc}'[:2000]
            evento.save(update_fields=['tentativas', 'erro'])
            if evento.tentativas == TENTATIVAS_ANTES_DO_ALARME:
                texto = (f'O aviso {evento.event_id} ({evento.tipo}) falhou '
                         f'{TENTATIVAS_ANTES_DO_ALARME} vezes.\n\nÚltimo erro: {evento.erro}')
                transaction.on_commit(lambda: avisar_superadmins(
                    'Um aviso da Asaas não pôde ser processado', texto,
                ))
            return evento
        evento.processado_em = timezone.now()
        evento.erro = nota[:2000]
        evento.save(update_fields=['processado_em', 'erro'])
    return evento


def _despachar(evento):
    dados = evento.payload or {}
    tipo = evento.tipo
    if tipo.startswith('CHECKOUT_'):
        return _evento_de_checkout(tipo, dados.get('checkout') or {})
    if tipo.startswith('SUBSCRIPTION_'):
        return _evento_de_assinatura(tipo, dados.get('subscription') or {})
    if tipo.startswith('PAYMENT_'):
        return _evento_de_cobranca(tipo, dados.get('payment') or {})
    if tipo in EVENTOS_DA_CHAVE:
        transaction.on_commit(lambda: avisar_superadmins(
            EVENTOS_DA_CHAVE[tipo],
            'A Asaas avisou sobre a chave da API usada pelo checkout. Sem chave válida, '
            'nenhum pedido novo abre o pagamento. Gere uma chave nova em Integrações > '
            'Chaves de API no painel da Asaas e troque o segredo NEURODOC_ASAAS_API_KEY '
            '(docs/operations/asaas.md).',
        ))
        return ''
    return 'ignorado: tipo sem tratamento'


def _evento_de_checkout(tipo, checkout):
    checkout_id = str(checkout.get('id') or '')
    pedido = None
    if checkout_id:
        pedido = Pedido.objects.select_for_update().filter(checkout_id=checkout_id).first()
    if pedido is None:
        return 'ignorado: checkout que não é de pedido desta instalação'
    if tipo == 'CHECKOUT_PAID':
        return _pago(pedido, checkout)
    if tipo in ('CHECKOUT_CANCELED', 'CHECKOUT_EXPIRED'):
        if pedido.status in (StatusPedido.PREPARANDO, StatusPedido.AGUARDANDO):
            pedido.status = (StatusPedido.CANCELADO if tipo == 'CHECKOUT_CANCELED'
                             else StatusPedido.EXPIRADO)
            pedido.save(update_fields=['status', 'updated_at'])
        return ''
    return 'ignorado: evento de checkout sem efeito'


def _total_dos_itens(checkout):
    total = Decimal('0')
    for item in checkout.get('items') or []:
        total += Decimal(str(item.get('value') or 0)) * int(item.get('quantity') or 1)
    return total.quantize(Decimal('0.01'))


def _pago(pedido, checkout):
    """O pagamento confirmado: convite, e-mail a quem pagou, aviso ao console.

    Vale de qualquer estado — o pagamento é o fato, e um pedido que a
    varredura deu por expirado pode ter sido pago no último minuto. Só não
    vale duas vezes.
    """
    from audit.services import record_audit_event
    from base.crypto import encrypt_secret
    from tenancy.invitations import issue_invitation
    from tenancy.models import InvitationPurpose

    if pedido.status == StatusPedido.PAGO:
        return 'repetido: pedido já pago'
    try:
        total = _total_dos_itens(checkout)
    except (InvalidOperation, ValueError, TypeError):
        total = None
    pedido.status = StatusPedido.PAGO
    pedido.pago_em = timezone.now()
    pedido.cliente_asaas_id = str(checkout.get('customer') or '')[:64]
    esperado = asaas.reais(pedido.valor_pagamento_centavos)
    if checkout.get('items') and total != esperado:
        # Não deveria acontecer — o checkout foi aberto daqui, com este valor.
        # Se acontecer, ninguém recebe plano por um valor que não é o do pedido.
        pedido.falha = f'Valor pago {total} diferente do pedido {esperado}.'
        pedido.save(update_fields=['status', 'pago_em', 'cliente_asaas_id', 'falha', 'updated_at'])
        texto = (f'O pedido {pedido.id} foi pago com valor diferente do combinado '
                 f'({total} contra {esperado}). Nenhum convite foi emitido nem período '
                 'aberto; confira na Asaas.')
        transaction.on_commit(lambda: avisar_superadmins(
            'Pagamento com valor diferente do pedido', texto,
        ))
        return 'pago com valor divergente: sem convite'
    if pedido.tenant_id:
        return _renovacao_paga(pedido)
    convite, token = issue_invitation(
        purpose=InvitationPurpose.PLATFORM, plan=pedido.plano,
        periodicidade=pedido.periodicidade, email_binding=pedido.email,
        ttl_days=CONVITE_DIAS,
        plan_note='Contratado e pago pela página de vendas (Asaas).',
    )
    cifrado, meta = encrypt_secret(token)
    pedido.convite = convite
    pedido.convite_token_cifrado, pedido.convite_token_meta = cifrado, meta
    pedido.save(update_fields=['status', 'pago_em', 'cliente_asaas_id', 'convite',
                               'convite_token_cifrado', 'convite_token_meta', 'updated_at'])
    record_audit_event(
        None, None, 'contratacao.pago', object_type='pedido_contratacao', object_id=pedido.id,
        outcome='success', integrity_metadata={
            'plano': pedido.plano, 'periodicidade': pedido.periodicidade,
            'valor_centavos': pedido.valor_pagamento_centavos, 'convite': str(convite.id),
        },
    )
    pedido_id = pedido.id
    texto = (f'Plano {pedido.plano}, {pedido.periodicidade}, {esperado} em pagamento único. '
             f'Pedido {pedido.id}.\n\n'
             'O convite foi emitido e o link de cadastro foi ao e-mail de quem pagou.')
    transaction.on_commit(lambda: enviar_link_de_cadastro(pedido_id, token))
    transaction.on_commit(lambda: avisar_superadmins('Novo plano pago pela página', texto))
    return ''


def _renovacao_paga(pedido):
    """O pagamento de uma renovação: o período seguinte, o e-mail e o aviso ao console."""
    from . import vigencias

    pedido.save(update_fields=['status', 'pago_em', 'cliente_asaas_id', 'updated_at'])
    vigencia = vigencias.abrir_da_renovacao(pedido)
    tenant = vigencia.tenant
    nome = tenant.trade_name or tenant.legal_name
    texto = (f'A clínica {nome} renovou o plano {pedido.plano} ({pedido.periodicidade}, '
             f'{asaas.reais(pedido.valor_pagamento_centavos)}). Novo período até '
             f'{vigencias.ultimo_dia(vigencia.fim):%d/%m/%Y}. Pedido {pedido.id}.')
    if pedido.plano != tenant.plan:
        texto += (f'\n\nATENÇÃO: o plano da clínica hoje é {tenant.plan}, e o pago foi '
                  f'{pedido.plano}. O plano não foi alterado; confira no console.')
    pedido_id = pedido.id
    transaction.on_commit(lambda: vigencias.avisar_renovacao_paga(pedido_id))
    transaction.on_commit(lambda: avisar_superadmins('Renovação paga', texto))
    return ''


def _evento_de_assinatura(tipo, assinatura):
    pedido = None
    sessao = str(assinatura.get('checkoutSession') or '')
    if sessao:
        pedido = Pedido.objects.select_for_update().filter(checkout_id=sessao).first()
    if pedido is None and assinatura.get('id'):
        pedido = Pedido.objects.select_for_update().filter(assinatura_id=str(assinatura['id'])).first()
    if pedido is None:
        return 'ignorado: assinatura que não é de pedido desta instalação'
    if assinatura.get('id') and not pedido.assinatura_id:
        pedido.assinatura_id = str(assinatura['id'])[:64]
        pedido.save(update_fields=['assinatura_id', 'updated_at'])
    if tipo in EVENTOS_DE_ALERTA:
        _alertar(tipo, pedido, assinatura.get('id'))
    return ''


def _pedido_da_cobranca(pagamento):
    sessao = str(pagamento.get('checkoutSession') or '')
    if sessao:
        pedido = Pedido.objects.filter(checkout_id=sessao).first()
        if pedido:
            return pedido
    assinatura = str(pagamento.get('subscription') or '')
    if assinatura:
        return Pedido.objects.filter(assinatura_id=assinatura).first()
    return None


def _evento_de_cobranca(tipo, pagamento):
    payment_id = str(pagamento.get('id') or '')[:64]
    pedido = _pedido_da_cobranca(pagamento)
    if not payment_id or pedido is None:
        return 'ignorado: cobrança que não é de pedido desta instalação'
    try:
        valor = Decimal(str(pagamento['value'])) if pagamento.get('value') is not None else None
    except InvalidOperation:
        valor = None
    try:
        vencimento = date.fromisoformat(str(pagamento.get('dueDate') or '')[:10])
    except ValueError:
        vencimento = None
    Cobranca.objects.update_or_create(payment_id=payment_id, defaults={
        'pedido': pedido, 'assinatura_id': str(pagamento.get('subscription') or '')[:64],
        'status': str(pagamento.get('status') or '')[:40],
        'forma': str(pagamento.get('billingType') or '')[:20],
        'valor': valor, 'vencimento': vencimento, 'ultimo_evento': tipo[:60],
    })
    if tipo in EVENTOS_DE_ALERTA:
        _alertar(tipo, pedido, payment_id)
    return ''


def _alertar(tipo, pedido, referencia):
    titulo = EVENTOS_DE_ALERTA[tipo]
    renovacao = ', renovação' if pedido.tenant_id else ''
    texto = (f'{titulo} (Asaas: {referencia}) no pedido {pedido.id} — plano {pedido.plano}, '
             f'{pedido.periodicidade}{renovacao}.\n\nNada foi suspenso nem alterado na clínica: a cláusula 5 '
             'do contrato pede aviso antes de restringir. Confira na Asaas e decida no console.')
    transaction.on_commit(lambda: avisar_superadmins(titulo, texto))


# ------------------------------------------------------------------ e-mails

def link_de_cadastro(token):
    return settings.PUBLIC_BASE_URL.rstrip('/') + reverse('onboarding:signup', args=[token])


def enviar_link_de_cadastro(pedido_id, token):
    """O link de cadastro a quem pagou, pelo remetente da instalação."""
    from django.template.loader import render_to_string

    from communications.email import send_email
    from tenancy.plans import Periodicidade, plan_label

    pedido = Pedido.objects.filter(id=pedido_id).first()
    if pedido is None:
        return False
    corpo = render_to_string('contratacao/email/pago.txt', {
        'pedido': pedido, 'plano': plan_label(pedido.plano),
        'periodicidade': Periodicidade(pedido.periodicidade).label.lower(),
        'valor': asaas.reais(pedido.valor_pagamento_centavos),
        'link': link_de_cadastro(token), 'dias': CONVITE_DIAS,
        'contrato_url': settings.PUBLIC_BASE_URL.rstrip('/') + reverse('onboarding:contrato'),
    })
    try:
        send_email(pedido.email, 'Pagamento confirmado: crie sua clínica no NeuroDoc', corpo)
    except Exception:  # noqa: BLE001 — o botão continua na página do pedido; o console mostra
        logger.warning('contratacao: e-mail do link falhou (pedido=%s)', pedido_id, exc_info=True)
        return False
    Pedido.objects.filter(id=pedido_id).update(email_enviado_em=timezone.now())
    return True


def avisar_superadmins(titulo, corpo):
    """E-mail a todo superadministrador ativo. Sem nome nem e-mail de quem pagou."""
    from django.core.mail import send_mail

    from accounts.models import User

    destinos = list(
        User.objects.filter(is_superuser=True, is_active=True)
        .exclude(email='').values_list('email', flat=True)
    )
    if not destinos:
        return 0
    rodape = ('\n\nConsole: ' + settings.PUBLIC_BASE_URL.rstrip('/')
              + reverse('superadmin:contratacao'))
    try:
        return send_mail(f'[NeuroDoc] {titulo}', corpo + rodape,
                         settings.DEFAULT_FROM_EMAIL, destinos, fail_silently=False)
    except Exception:  # noqa: BLE001
        logger.warning('contratacao: aviso aos superadministradores falhou', exc_info=True)
        return 0


# ------------------------------------------------------------------ varreduras

def varrer():
    """De cinco em cinco minutos: avisos sem processar e pedidos parados."""
    agora = timezone.now()
    pendentes = list(
        EventoAsaas.objects.filter(
            processado_em__isnull=True, recebido_em__lt=agora - timezone.timedelta(minutes=1),
            tentativas__lt=20,
        ).order_by('recebido_em').values_list('id', flat=True)[:200]
    )
    for evento_id in pendentes:
        processar_evento(evento_id)
    parados = list(Pedido.objects.filter(
        status=StatusPedido.PREPARANDO, created_at__lt=agora - timezone.timedelta(minutes=15),
    ).values_list('id', flat=True))
    for pedido_id in parados:
        marcar_falha(pedido_id, 'O worker não abriu o checkout em 15 minutos.')
    # Sem aviso de expiração em três horas, o link já venceu (vale uma hora).
    # O pagamento que ainda chegar é aceito mesmo assim (`_pago`).
    Pedido.objects.filter(
        status=StatusPedido.AGUARDANDO,
        updated_at__lt=agora - timezone.timedelta(minutes=asaas.MINUTOS_PARA_EXPIRAR + 120),
    ).update(status=StatusPedido.EXPIRADO, updated_at=agora)
    return len(pendentes)
