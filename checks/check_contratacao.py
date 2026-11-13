"""A contratação pela página de vendas com o checkout da Asaas (1.46) tenta ser quebrada.

A Asaas é **simulada**: o ambiente local não abre checkout de verdade (ela
recusa `successUrl` com `localhost`), e o roteiro não pode depender de rede.
O que a API real respondeu está anotado em `contratacao/asaas.py`.

O que este roteiro cobra:

- **o corpo do checkout** de cada forma de pagamento: anual avulso por Pix ou
  cartão; semestral e trimestral em assinatura no cartão que **termina** em 12
  meses (`endDate`), sem renovação; o valor de cada cobrança vindo do catálogo;
- **a página de contratar**: desligada devolve aos planos; Gratuito e
  Personalizado não se contratam; sem a declaração de leitura, com e-mail
  descartável, com e-mail que já tem conta e pelo campo-armadilha, nenhum
  pedido nasce; o pedido válido grava o preço e pede o checkout ao worker;
- **o worker**: abre o checkout e grava o link; recusa da Asaas vira pedido
  falho com o motivo; pedido que já não está preparando não chama a Asaas;
- **a página do pedido**: leva à Asaas só por link `https` da Asaas; o
  retorno "pago" espera a confirmação, não a declara;
- **o webhook**: sem token, com token errado e sem token configurado recusa;
  corpo que não é JSON recusa; o aviso válido grava **uma vez** mesmo
  repetido; `GET` não existe;
- **o pagamento confirmado**: convite do plano e da forma de pagamento, preso
  ao e-mail, o link no e-mail e na página — esta, **só no navegador que
  pediu** —, o aviso aos superadministradores, e a clínica criada pelo
  convite no plano pago com a forma de pagamento no aceite; o segundo aviso
  de pagamento não emite segundo convite; valor divergente não emite convite;
  pago depois de expirado vale;
- **cobranças seguintes**: assinatura ligada ao pedido, atraso e estorno
  gravados e avisados, nada suspenso; cobrança de outra origem ignorada;
- **falha no processamento** registrada e retomada pela varredura;
- **o console**: ligar exige contrato que preveja a Asaas, a palavra e o
  motivo; desligar é um clique;
- **a vitrine**: com a chave desligada, nada muda; ligada, "Contratar agora"
  nos planos pagos de tabela;
- **a chave da API só no worker**, e o token do webhook no app.
"""
import json
import re
from pathlib import Path
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
TOKEN = 'roteiro-' + 'x' * 40
dj_settings.ASAAS_WEBHOOK_TOKEN = TOKEN

from django.core import mail
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from base.crypto import decrypt_secret
from contratacao import asaas, servicos
from contratacao.models import Cobranca, Configuracao, EventoAsaas, Pedido, StatusPedido
from tenancy import contract
from tenancy.invitations import peek_invitation
from tenancy.models import ContractAcceptance, Invitation
from tenancy.plans import preco_na_periodicidade
from tenancy.services import accept_platform_invitation

falhas = []
SUFIXO = '@contratacao.invalid'


def conferir(rotulo, ok, detalhe=''):
    print(f"  {'ok  ' if ok else 'FALHA'} {rotulo}" + (f' -> {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(f'{rotulo} {detalhe}')


def cnpj_valido(base):
    def dv(numeros, pesos):
        resto = sum(a * b for a, b in zip(numeros, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    n = [int(x) for x in base]
    d1 = dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


class Desfazer(Exception):
    pass


def imediato(func, using=None, robust=False):
    func()


contador = {'n': 0}


def checkout_simulado(corpo):
    contador['n'] += 1
    cid = f'00000000-0000-4000-8000-{contador["n"]:012d}'
    return {'id': cid, 'link': f'https://www.asaas.com/000/checkoutSession/show/{cid}', 'status': 'ACTIVE'}


def webhook(cliente, payload, token=TOKEN):
    cabecalhos = {'HTTP_ASAAS_ACCESS_TOKEN': token} if token is not None else {}
    return cliente.post('/asaas/webhook/', data=json.dumps(payload),
                        content_type='application/json', **cabecalhos)


def aviso(event_id, tipo, **recurso):
    return {'id': event_id, 'event': tipo, 'dateCreated': '2026-11-12 10:00:00',
            'account': {'id': 'acc', 'ownerId': None}, **recurso}


def pedido_pago(cliente, plano='complete', periodicidade='anual', email=None):
    """Cria o pedido pela tela, abre o checkout simulado e devolve o pedido."""
    cache.delete('contratar:127.0.0.1')
    r = cliente.post(f'/contratar/{plano}/', {
        'periodicidade': periodicidade, 'nome': 'Dra. Roteiro',
        'email': email or f'pago-{contador["n"]}{SUFIXO}', 'li_o_contrato': 'on',
    })
    pedido = Pedido.objects.order_by('-created_at').first()
    servicos.preparar_checkout(pedido.id)
    pedido.refresh_from_db()
    return r, pedido


print('=== 1. o corpo do checkout de cada forma de pagamento ===')
hoje = timezone.localdate()
for periodicidade, ciclo, cobrancas in (('anual', None, 1), ('semestral', 'SEMIANNUALLY', 2),
                                         ('trimestral', 'QUARTERLY', 4)):
    preco = preco_na_periodicidade('complete', periodicidade)
    falso = Pedido(plano='complete', periodicidade=periodicidade,
                   valor_pagamento_centavos=preco['pagamento'], valor_ano_centavos=preco['ano'])
    corpo = asaas.montar_checkout(falso, 'https://neurodoc.app.br/contratar/pedido/x/', hoje)
    item = corpo['items'][0]
    conferir(f'{periodicidade}: valor do item = cada pagamento do catálogo',
             item['value'] == preco['pagamento'] / 100, item['value'])
    conferir(f'{periodicidade}: nome até 30 e descrição até 150 caracteres',
             len(item['name']) <= 30 and len(item['description']) <= 150)
    conferir(f'{periodicidade}: retorno pago, cancelado e expirado',
             corpo['callback']['successUrl'].endswith('?retorno=pago')
             and corpo['callback']['cancelUrl'].endswith('?retorno=cancelado')
             and corpo['callback']['expiredUrl'].endswith('?retorno=expirado'))
    conferir(f'{periodicidade}: sem dados do cliente (a Asaas os pede inteiros)', 'customerData' not in corpo)
    if ciclo is None:
        conferir('anual: avulso, por Pix ou cartão',
                 corpo['chargeTypes'] == ['DETACHED'] and set(corpo['billingTypes']) == {'PIX', 'CREDIT_CARD'}
                 and 'subscription' not in corpo)
    else:
        sub = corpo['subscription']
        from scheduling.returns import _somar_meses
        conferir(f'{periodicidade}: assinatura {ciclo} só no cartão',
                 corpo['chargeTypes'] == ['RECURRENT'] and corpo['billingTypes'] == ['CREDIT_CARD']
                 and sub['cycle'] == ciclo)
        conferir(f'{periodicidade}: termina 11 meses depois da primeira ({cobrancas} cobranças, sem renovar)',
                 sub['nextDueDate'] == hoje.isoformat()
                 and sub['endDate'] == _somar_meses(hoje, 11).isoformat())
from datetime import date
corpo = asaas.montar_checkout(Pedido(plano='basic', periodicidade='trimestral',
                                     valor_pagamento_centavos=1, valor_ano_centavos=4),
                              'https://x/', date(2027, 3, 31))
conferir('31/03 mais 11 meses é 29/02/2028, sem estourar o mês',
         corpo['subscription']['endDate'] == '2028-02-29', corpo['subscription']['endDate'])

try:
    with transaction.atomic(), \
            mock.patch('django.db.transaction.on_commit', imediato), \
            mock.patch('contratacao.tasks.preparar_checkout_task.delay') as delay_checkout, \
            mock.patch('contratacao.tasks.processar_evento_task.delay') as delay_evento, \
            mock.patch.object(asaas, 'criar_checkout', side_effect=checkout_simulado) as criar:
        User.objects.filter(email__endswith=SUFIXO).delete()
        config = Configuracao.carregar()
        cliente = Client()

        print('=== 2. a página de contratar ===')
        config.ativo = False
        config.save()
        r = cliente.get('/contratar/complete/')
        conferir('desligada: GET volta aos planos', r.status_code == 302 and '#planos' in r['Location'])
        r = cliente.post('/contratar/complete/', {'periodicidade': 'anual', 'nome': 'X',
                                                   'email': f'a{SUFIXO}', 'li_o_contrato': 'on'})
        conferir('desligada: POST não cria pedido', r.status_code == 302 and not Pedido.objects.exists())
        config.ativo = True
        config.save()
        conferir('Gratuito não se contrata (404)', cliente.get('/contratar/free/').status_code == 404)
        conferir('Personalizado não se contrata (404)', cliente.get('/contratar/custom/').status_code == 404)
        conferir('plano inexistente (404)', cliente.get('/contratar/premium/').status_code == 404)
        r = cliente.get('/contratar/basic/?periodo=semestral')
        html = r.content.decode()
        conferir('a tela abre com as três formas e a semestral marcada',
                 r.status_code == 200 and html.count('name="periodicidade"') == 3
                 and re.search(r'value="semestral"[^>]*checked', html) is not None, r.status_code)
        conferir('a tela diz que não há renovação automática', 'não há renovação automática' in html)
        conferir('a tela aponta o contrato e a versão', f'versão {contract.VERSAO}' in html)
        base = {'periodicidade': 'anual', 'nome': 'Dra. Roteiro', 'email': f'novo{SUFIXO}'}
        cache.delete('contratar:127.0.0.1')
        r = cliente.post('/contratar/complete/', base)
        conferir('sem declarar a leitura do contrato: 400 e nenhum pedido',
                 r.status_code == 400 and not Pedido.objects.exists(), r.status_code)
        # A lista de descartáveis não é carregada no ambiente local; a
        # pergunta é simulada para o domínio do teste.
        with mock.patch('catalogs.descartaveis.e_descartavel', side_effect=lambda e: e.endswith('@descartavel.invalid')):
            r = cliente.post('/contratar/complete/', dict(base, li_o_contrato='on', email='x@descartavel.invalid'))
        conferir('e-mail descartável: 400 e nenhum pedido',
                 r.status_code == 400 and not Pedido.objects.exists() and 'temporário' in r.content.decode(),
                 r.status_code)
        existente = User.objects.create_user(email=f'ja-tem{SUFIXO}', password='Senha-forte-123')
        r = cliente.post('/contratar/complete/', dict(base, li_o_contrato='on', email=existente.email.upper()))
        conferir('e-mail que já tem conta: 400 e nenhum pedido (o cadastro recusaria depois de pago)',
                 r.status_code == 400 and not Pedido.objects.exists(), r.status_code)
        r = cliente.post('/contratar/complete/', dict(base, li_o_contrato='on', website='robo'))
        conferir('campo-armadilha: volta sem pedido', r.status_code == 302 and not Pedido.objects.exists())
        r = cliente.post('/contratar/complete/', dict(base, li_o_contrato='on', periodicidade='mensal'))
        conferir('forma de pagamento inventada: 400', r.status_code == 400 and not Pedido.objects.exists())

        r = cliente.post('/contratar/complete/', dict(base, li_o_contrato='on', periodicidade='trimestral'))
        pedido = Pedido.objects.get()
        preco = preco_na_periodicidade('complete', 'trimestral')
        conferir('pedido válido: redireciona à página do pedido',
                 r.status_code == 302 and r['Location'] == f'/contratar/pedido/{pedido.id}/', r.get('Location'))
        conferir('o preço gravado é o do catálogo (cada cobrança, ano, 4 cobranças)',
                 (pedido.valor_pagamento_centavos, pedido.valor_ano_centavos, pedido.cobrancas_previstas)
                 == (preco['pagamento'], preco['ano'], 4))
        conferir('a versão do contrato lida fica no pedido', pedido.contrato_versao == contract.VERSAO)
        conferir('o checkout é pedido ao worker, e não aberto na requisição',
                 delay_checkout.call_count == 1 and criar.call_count == 0)
        conferir('a trilha registra o pedido sem nome nem e-mail', AuditEvent.objects.filter(
            action='contratacao.pedido_criado', object_id=str(pedido.id)).exists()
            and 'Roteiro' not in json.dumps(AuditEvent.objects.filter(
                action='contratacao.pedido_criado').last().integrity_metadata))

        print('=== 3. a página espera o worker ===')
        r = cliente.get(f'/contratar/pedido/{pedido.id}/')
        conferir('preparando: recarrega sozinha', b'http-equiv="refresh"' in r.content)

        print('=== 4. o worker abre o checkout ===')
        servicos.preparar_checkout(pedido.id)
        pedido.refresh_from_db()
        conferir('aberto: aguardando, com o id e o link da Asaas',
                 pedido.status == StatusPedido.AGUARDANDO and pedido.checkout_id and 'asaas.com' in pedido.checkout_link)
        servicos.preparar_checkout(pedido.id)
        conferir('pedido que já não está preparando não chama a Asaas de novo', criar.call_count == 1)
        r = cliente.get(f'/contratar/pedido/{pedido.id}/')
        conferir('a página leva à Asaas', r.status_code == 302 and r['Location'] == pedido.checkout_link)
        r = cliente.get(f'/contratar/pedido/{pedido.id}/?retorno=pago')
        conferir('volta "pago" sem aviso: espera, não declara pago',
                 r.status_code == 200 and b'http-equiv="refresh"' in r.content
                 and b'Pagamento confirmado' not in r.content)
        r = cliente.get(f'/contratar/pedido/{pedido.id}/?retorno=cancelado')
        conferir('volta "cancelado": diz que nada foi cobrado', 'Nada foi cobrado' in r.content.decode())
        r = cliente.get(f'/contratar/pedido/{pedido.id}/?retorno=expirado')
        conferir('volta "expirado": oferece pedido novo, e não o link vencido',
                 'Fazer um novo pedido' in r.content.decode() and 'Voltar ao pagamento' not in r.content.decode())
        Pedido.objects.filter(id=pedido.id).update(updated_at=timezone.now() - timezone.timedelta(minutes=31))
        r = cliente.get(f'/contratar/pedido/{pedido.id}/?retorno=pago')
        conferir('esperando há mais de meia hora: para de recarregar e aponta o e-mail',
                 b'http-equiv="refresh"' not in r.content and 'Aguardando a confirmação' in r.content.decode())
        Pedido.objects.filter(id=pedido.id).update(updated_at=timezone.now())
        Pedido.objects.filter(id=pedido.id).update(checkout_link='http://evil.example/asaas.com')
        r = cliente.get(f'/contratar/pedido/{pedido.id}/')
        conferir('link que não é https da Asaas não vira redirecionamento', r.status_code == 200)
        Pedido.objects.filter(id=pedido.id).update(checkout_link='https://www.asaas.com.evil.example/x')
        conferir('nem domínio que só começa com asaas.com',
                 cliente.get(f'/contratar/pedido/{pedido.id}/').status_code == 200)
        Pedido.objects.filter(id=pedido.id).update(
            checkout_link=f'https://www.asaas.com/000/checkoutSession/show/{pedido.checkout_id}')

        with mock.patch.object(asaas, 'criar_checkout',
                               side_effect=asaas.AsaasErro('Para gerar cobranças com Pix é necessário criar uma chave Pix no Asaas.')):
            mail.outbox = []
            cache.delete('contratar:127.0.0.1')
            cliente.post('/contratar/basic/', dict(base, li_o_contrato='on', email=f'falho{SUFIXO}'))
            falho = Pedido.objects.order_by('-created_at').first()
            servicos.preparar_checkout(falho.id)
            falho.refresh_from_db()
            conferir('recusa da Asaas: pedido falho com o motivo',
                     falho.status == StatusPedido.FALHOU and 'chave Pix' in falho.falha)
            conferir('a página do falho oferece tentar de novo',
                     'Tentar de novo' in cliente.get(f'/contratar/pedido/{falho.id}/').content.decode())

        print('=== 5. o webhook ===')
        externo = Client()
        conferir('sem token: 401', webhook(externo, aviso('evt_1', 'CHECKOUT_PAID'), token=None).status_code == 401)
        conferir('token errado: 401', webhook(externo, aviso('evt_1', 'CHECKOUT_PAID'), token='y' * 48).status_code == 401)
        conferir('nada gravado nas recusas', not EventoAsaas.objects.exists())
        r = externo.post('/asaas/webhook/', data='não é json', content_type='application/json',
                         HTTP_ASAAS_ACCESS_TOKEN=TOKEN)
        conferir('corpo que não é JSON: 400', r.status_code == 400)
        conferir('aviso sem id: 400', webhook(externo, {'event': 'CHECKOUT_PAID'}).status_code == 400)
        conferir('GET: 404', externo.get('/asaas/webhook/').status_code == 404)
        with mock.patch.object(dj_settings, 'ASAAS_WEBHOOK_TOKEN', ''):
            conferir('token não configurado: 503, e não aceita qualquer um',
                     webhook(externo, aviso('evt_x', 'CHECKOUT_PAID'), token='').status_code == 503)

        print('=== 6. o pagamento confirmado ===')
        mail.outbox = []
        su = User.objects.create_superuser(email=f'su{SUFIXO}', password=None,
                                           email_verified_at=timezone.now())
        pago = aviso('evt_pago_1', 'CHECKOUT_PAID', checkout={
            'id': pedido.checkout_id, 'status': 'PAID', 'customer': 'cus_000001',
            'items': [{'name': 'NeuroDoc Completo', 'quantity': 1, 'value': preco['pagamento'] / 100}],
        })
        r = webhook(externo, pago)
        conferir('aviso válido: 200', r.status_code == 200, r.status_code)
        r = webhook(externo, pago)
        conferir('o mesmo aviso de novo: 200 e gravado uma vez só',
                 r.status_code == 200 and EventoAsaas.objects.filter(event_id='evt_pago_1').count() == 1)
        conferir('processar é pedido ao worker, uma vez', delay_evento.call_count == 1)
        evento = EventoAsaas.objects.get(event_id='evt_pago_1')
        servicos.processar_evento(evento.id)
        pedido.refresh_from_db()
        conferir('pedido pago, com o cliente da Asaas',
                 pedido.status == StatusPedido.PAGO and pedido.pago_em and pedido.cliente_asaas_id == 'cus_000001')
        convite = pedido.convite
        conferir('convite do plano e da forma de pagamento, preso ao e-mail, 30 dias',
                 convite and convite.plan == 'complete' and convite.periodicidade == 'trimestral'
                 and convite.email_binding == pedido.email and not convite.degustacao
                 and (convite.expires_at - timezone.now()).days >= 29)
        token = decrypt_secret(pedido.convite_token_cifrado, pedido.convite_token_meta)
        conferir('o código guardado cifrado abre o convite', peek_invitation(token) == convite)
        para_quem_pagou = [m for m in mail.outbox if pedido.email in m.to]
        conferir('o link de cadastro foi ao e-mail de quem pagou',
                 len(para_quem_pagou) == 1 and f'/signup/{token}/' in para_quem_pagou[0].body
                 and pedido.email_enviado_em is not None)
        conferir('o e-mail cita os 7 dias de arrependimento', '7 dias' in para_quem_pagou[0].body)
        para_su = [m for m in mail.outbox if su.email in m.to]
        conferir('o superadministrador é avisado da venda, sem nome nem e-mail de quem pagou',
                 any('Novo plano pago' in m.subject for m in para_su)
                 and not any(pedido.email in m.body or 'Roteiro' in m.body for m in para_su))
        r = cliente.get(f'/contratar/pedido/{pedido.id}/?retorno=pago')
        conferir('no navegador que pediu: botão para criar a clínica',
                 f'/signup/{token}/' in r.content.decode() and b'http-equiv="refresh"' not in r.content)
        r = Client().get(f'/contratar/pedido/{pedido.id}/?retorno=pago')
        conferir('em outro navegador: só o e-mail mascarado, sem o link',
                 token not in r.content.decode() and pedido.email not in r.content.decode()
                 and 'Pagamento confirmado' in r.content.decode())
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_pago_2', tipo='CHECKOUT_PAID', payload=pago).id)
        conferir('segundo aviso de pagamento: nenhum convite a mais',
                 Invitation.objects.filter(pedido_asaas=pedido).count() == 1
                 and Pedido.objects.get(id=pedido.id).convite_id == convite.id)

        user, tenant, membership, aceite = accept_platform_invitation(
            token, pedido.email, 'Senha-forte-roteiro-1', 'Clínica do Roteiro Ltda',
            cnpj_valido('77880099000100'[:12]), contract_powers=True,
        )
        conferir('o convite cria a clínica no plano pago', tenant.plan == 'complete')
        conferir('e o aceite grava a forma de pagamento do pedido',
                 aceite.periodicidade == 'trimestral' and aceite.plan == 'complete')
        r = cliente.get(f'/contratar/pedido/{pedido.id}/')
        conferir('depois do cadastro, a página diz que a clínica já existe', 'já foi criada' in r.content.decode())

        print('=== 7. cobranças seguintes, sem suspender nada ===')
        mail.outbox = []
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_sub', tipo='SUBSCRIPTION_CREATED',
            payload=aviso('evt_sub', 'SUBSCRIPTION_CREATED', subscription={
                'id': 'sub_roteiro', 'checkoutSession': pedido.checkout_id, 'cycle': 'QUARTERLY'})).id)
        pedido.refresh_from_db()
        conferir('a assinatura fica ligada ao pedido', pedido.assinatura_id == 'sub_roteiro')
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_atraso', tipo='PAYMENT_OVERDUE',
            payload=aviso('evt_atraso', 'PAYMENT_OVERDUE', payment={
                'id': 'pay_2', 'subscription': 'sub_roteiro', 'status': 'OVERDUE', 'value': 525.0,
                'billingType': 'CREDIT_CARD', 'dueDate': '2027-02-12'})).id)
        cobranca = Cobranca.objects.get(payment_id='pay_2')
        conferir('a cobrança atrasada é gravada no pedido',
                 cobranca.pedido_id == pedido.id and cobranca.status == 'OVERDUE'
                 and str(cobranca.vencimento) == '2027-02-12')
        conferir('e o superadministrador é avisado',
                 any('vencida' in m.subject for m in mail.outbox if su.email in m.to))
        tenant.refresh_from_db()
        conferir('a clínica continua no plano e ativa', tenant.plan == 'complete' and tenant.status == 'active',
                 (tenant.plan, tenant.status))
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_estorno', tipo='PAYMENT_REFUNDED',
            payload=aviso('evt_estorno', 'PAYMENT_REFUNDED', payment={
                'id': 'pay_1', 'checkoutSession': pedido.checkout_id, 'status': 'REFUNDED', 'value': 525.0})).id)
        conferir('estorno pela sessão do checkout: gravado e avisado',
                 Cobranca.objects.get(payment_id='pay_1').status == 'REFUNDED'
                 and any('estornada' in m.subject for m in mail.outbox))
        e = servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_alheio', tipo='PAYMENT_RECEIVED',
            payload=aviso('evt_alheio', 'PAYMENT_RECEIVED', payment={'id': 'pay_fora', 'value': 10})).id)
        conferir('cobrança de outra origem: ignorada, sem linha',
                 e.processado_em and 'ignorado' in e.erro and not Cobranca.objects.filter(payment_id='pay_fora').exists())

        print('=== 8. expirado, pago depois, valor divergente, desconhecido ===')
        _, outro = pedido_pago(cliente, 'basic', 'anual', email=f'exp{SUFIXO}')
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_exp', tipo='CHECKOUT_EXPIRED',
            payload=aviso('evt_exp', 'CHECKOUT_EXPIRED', checkout={'id': outro.checkout_id})).id)
        outro.refresh_from_db()
        conferir('checkout expirado: pedido expirado', outro.status == StatusPedido.EXPIRADO)
        valor = preco_na_periodicidade('basic', 'anual')['pagamento'] / 100
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_tarde', tipo='CHECKOUT_PAID', payload=aviso('evt_tarde', 'CHECKOUT_PAID', checkout={
                'id': outro.checkout_id, 'items': [{'quantity': 1, 'value': valor}]})).id)
        outro.refresh_from_db()
        conferir('pago depois de expirado: vale, com convite', outro.status == StatusPedido.PAGO and outro.convite_id)
        _, divergente = pedido_pago(cliente, 'basic', 'anual', email=f'div{SUFIXO}')
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_div', tipo='CHECKOUT_PAID', payload=aviso('evt_div', 'CHECKOUT_PAID', checkout={
                'id': divergente.checkout_id, 'items': [{'quantity': 1, 'value': 1.00}]})).id)
        divergente.refresh_from_db()
        conferir('valor divergente: pago, sem convite, com a falha anotada',
                 divergente.status == StatusPedido.PAGO and divergente.convite_id is None and 'diferente' in divergente.falha)
        e = servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_desconhecido', tipo='CHECKOUT_PAID',
            payload=aviso('evt_desconhecido', 'CHECKOUT_PAID', checkout={'id': 'checkout-de-outro-lugar'})).id)
        conferir('checkout que não é desta instalação: ignorado', e.processado_em and 'ignorado' in e.erro)

        print('=== 9. falha no processamento e a varredura ===')
        _, fragil = pedido_pago(cliente, 'basic', 'semestral', email=f'fragil{SUFIXO}')
        ev = EventoAsaas.objects.create(event_id='evt_fragil', tipo='CHECKOUT_PAID', payload=aviso(
            'evt_fragil', 'CHECKOUT_PAID', checkout={'id': fragil.checkout_id}))
        with mock.patch('tenancy.invitations.issue_invitation', side_effect=RuntimeError('banco caiu')):
            servicos.processar_evento(ev.id)
        ev.refresh_from_db()
        fragil.refresh_from_db()
        conferir('falhou: não processado, tentativa e erro anotados, pedido intacto',
                 ev.processado_em is None and ev.tentativas == 1 and 'banco caiu' in ev.erro
                 and fragil.status == StatusPedido.AGUARDANDO)
        EventoAsaas.objects.filter(id=ev.id).update(recebido_em=timezone.now() - timezone.timedelta(minutes=5))
        servicos.varrer()
        ev.refresh_from_db()
        fragil.refresh_from_db()
        conferir('a varredura retoma e conclui', ev.processado_em and fragil.status == StatusPedido.PAGO)
        cache.delete('contratar:127.0.0.1')
        cliente.post('/contratar/basic/', dict(base, li_o_contrato='on', email=f'parado{SUFIXO}'))
        parado = Pedido.objects.order_by('-created_at').first()
        Pedido.objects.filter(id=parado.id).update(created_at=timezone.now() - timezone.timedelta(minutes=20))
        servicos.varrer()
        parado.refresh_from_db()
        conferir('pedido preparando há 15 minutos vira falho', parado.status == StatusPedido.FALHOU)

        print('=== 10. o console ===')
        dispositivo = TOTPDevice.objects.create(user=su, name='roteiro-contratacao', confirmed=True)
        s = Client(SERVER_NAME='localhost')
        s.force_login(su)
        requisicao = type('R', (), {'session': s.session, 'user': su})()
        otp_login(requisicao, dispositivo)
        from accounts.mfa import mark_recent_mfa
        mark_recent_mfa(requisicao)
        requisicao.session.save()
        s.cookies['sessionid'] = requisicao.session.session_key
        r = s.get('/instalacao/contratacao/')
        conferir('a tela abre e lista os pedidos', r.status_code == 200 and str(pedido.id) in r.content.decode(),
                 r.status_code)
        conferir('quem não é superadministrador não abre', cliente.get('/instalacao/contratacao/').status_code in (302, 404))
        s.post('/instalacao/contratacao/', {'acao': 'desligar'})
        conferir('desligar é um clique', not Configuracao.carregar().ativo)
        with mock.patch.object(contract, 'VERSAO', '2.0'):
            s.post('/instalacao/contratacao/', {'acao': 'ligar', 'confirmacao': 'LIGAR', 'motivo': 'roteiro'})
            conferir('com o contrato 2.0, não liga (a cláusula 4.3 não prevê a Asaas)', not Configuracao.carregar().ativo)
        with mock.patch.object(contract, 'VERSAO', '2.1'):
            s.post('/instalacao/contratacao/', {'acao': 'ligar', 'confirmacao': 'ligar', 'motivo': 'roteiro'})
            conferir('sem a palavra exata, não liga', not Configuracao.carregar().ativo)
            s.post('/instalacao/contratacao/', {'acao': 'ligar', 'confirmacao': 'LIGAR', 'motivo': ''})
            conferir('sem motivo, não liga', not Configuracao.carregar().ativo)
            s.post('/instalacao/contratacao/', {'acao': 'ligar', 'confirmacao': 'LIGAR', 'motivo': 'roteiro'})
            conferir('com a 2.1, a palavra e o motivo, liga', Configuracao.carregar().ativo)
        conferir('as mudanças na trilha', AuditEvent.objects.filter(
            actor=su, action__in=['ops.checkout_enabled', 'ops.checkout_disabled']).count() == 2)

        print('=== 11. a vitrine ===')
        html = Client().get('/').content.decode()
        conferir('ligado: "Contratar agora" no Básico e no Completo',
                 '/contratar/basic/' in html and '/contratar/complete/' in html)
        conferir('ligado: nunca no Gratuito nem no Personalizado',
                 '/contratar/free/' not in html and '/contratar/custom/' not in html)
        conferir('ligado: a frase "Não há pagamento on-line" sai (cartões e FAQ)',
                 'Não há pagamento on-line' not in html and 'Pagamento on-line, teleconsulta' not in html)
        conferir('ligado: o FAQ diz como se contrata pela página', 'sem renovação automática' in html)
        llms = Client().get('/llms-full.txt').content.decode()
        conferir('ligado: o llms-full.txt diz o mesmo que a página',
                 'Não há pagamento on-line' not in llms and 'pela Asaas' in llms)
        Configuracao.objects.update(ativo=False)
        html = Client().get('/').content.decode()
        conferir('desligado: a vitrine fica como era',
                 '/contratar/' not in html and 'Não há pagamento on-line' in html and 'Quero este plano' in html)
        conferir('desligado: o llms-full.txt também',
                 'Não há pagamento on-line' in Client().get('/llms-full.txt').content.decode())

        raise Desfazer
except Desfazer:
    pass

print('=== 12. a chave da API só no worker ===')
raiz = Path(dj_settings.BASE_DIR)
stack = (raiz / 'docker-stack.yml').read_text(encoding='utf-8')
bloco_app = stack.split('\n  app:')[1].split('\n  celery_worker:')[0]
bloco_worker = stack.split('\n  celery_worker:')[1].split('\n  celery_beat:')[0]
conferir('o app não recebe a chave da API da Asaas', 'NEURODOC_ASAAS_API_KEY' not in bloco_app)
conferir('o app recebe o token do webhook', 'NEURODOC_ASAAS_WEBHOOK_TOKEN' in bloco_app)
conferir('o worker recebe os dois', 'NEURODOC_ASAAS_API_KEY' in bloco_worker
         and 'NEURODOC_ASAAS_WEBHOOK_TOKEN' in bloco_worker)
runtime = (raiz / 'ops' / 'make_runtime.py').read_text(encoding='utf-8')
conferir('o runtime do app não lista a chave da API',
         "'PFX_MASTER_KEY', 'SECRETS_MASTER_KEY', 'ASAAS_WEBHOOK_TOKEN']" in runtime)
conferir('nenhuma view chama a API da Asaas',
         'asaas.chamar' not in (raiz / 'contratacao' / 'views.py').read_text(encoding='utf-8')
         and 'criar_checkout' not in (raiz / 'contratacao' / 'views.py').read_text(encoding='utf-8'))

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('check_contratacao: tudo certo.')
