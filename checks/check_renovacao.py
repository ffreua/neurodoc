"""Vigência por período e renovação pelo sistema (1.47, contrato 2.2) tenta ser quebrada.

Cada forma de pagamento é um período — doze, seis ou três meses, pago de uma
vez —, nada renova sozinho, e o responsável renova em Organização → Plano e
renovação. A Asaas é **simulada**, como em `check_contratacao`.

O que este roteiro cobra:

- **o primeiro período** nasce no aceite do plano pago, com o fim do aceite;
- **o aviso**: fora dos quinze dias, nada; dentro, a faixa no alto da tela,
  **só para o responsável** (a secretária não vê nem abre a tela); vencido, a
  faixa diz que venceu e que nada foi bloqueado;
- **renovar**: fora da janela e com o checkout desligado, recusado sem pedido;
  na janela, o pedido nasce com a clínica, o plano dela e o preço do catálogo,
  e o checkout vai ao worker; o segundo clique reaproveita o pedido aberto; o
  corpo do checkout diz que é renovação e não cria assinatura;
- **o pagamento** abre o período seguinte **emendado no fim do atual** (pagar
  antes não encurta nada), sem mudar o plano, com e-mail a quem renovou e ao
  console; o aviso repetido não abre outro período; um segundo pagamento
  emenda depois do primeiro; renovar depois de vencido começa agora;
- **os e-mails do dia**: quinze dias antes, uma vez; vencida, uma vez ao
  responsável e ao console — e a clínica continua no plano e ativa;
- **o plano trocado no console** cala o aviso;
- **o console** registra período à mão (com o código, exigindo a nota) e
  lista as vigências.

Tudo numa transação desfeita.

    docker compose exec -T app python manage.py shell < checks/check_renovacao.py
"""
import uuid
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from contratacao import asaas, servicos, vigencias
from contratacao.models import Configuracao, EventoAsaas, Pedido, StatusPedido, Vigencia
from tenancy.contracts import somar_meses
from tenancy.invitations import issue_invitation
from tenancy.models import InvitationPurpose, Membership, MembershipStatus, Role
from tenancy.plans import PlanCode, preco_na_periodicidade
from tenancy.services import accept_platform_invitation

falhas = []
SUFIXO = '@renovacao.invalid'
AVISO = 'data-nd-aviso="vigencia"'


def conferir(rotulo, ok, detalhe=''):
    print(f"  {'ok  ' if ok else 'FALHA'} {rotulo}" + (f' -> {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(f'{rotulo} {detalhe}')


def cnpj(base):
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


def contratar(plano, periodicidade, base):
    _, token = issue_invitation(InvitationPurpose.PLATFORM, plan=plano, periodicidade=periodicidade)
    user, tenant, _, aceite = accept_platform_invitation(
        token, f'dono-{uuid.uuid4().hex[:8]}{SUFIXO}', 'Senha-forte-123!',
        f'CLINICA RENOVACAO {base} LTDA', cnpj(base), contract_powers=True,
    )
    user.first_name, user.last_name = 'Dra.', 'Renova'
    user.email_verified_at = timezone.now()
    user.save(update_fields=['first_name', 'last_name', 'email_verified_at'])
    return user, tenant, aceite


def entrar(user, tenant):
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def mover_fim(vigencia, fim):
    Vigencia.objects.filter(id=vigencia.id).update(
        inicio=min(vigencia.inicio, fim - timezone.timedelta(days=30)), fim=fim,
        aviso_antes_em=None, aviso_vencido_em=None)
    vigencia.refresh_from_db()
    return vigencia


contador = {'n': 0}


def checkout_simulado(corpo):
    contador['n'] += 1
    cid = f'00000000-0000-4000-9000-{contador["n"]:012d}'
    checkout_simulado.ultimo = corpo
    return {'id': cid, 'link': f'https://www.asaas.com/000/checkoutSession/show/{cid}'}


def pagar(pedido, event_id):
    servicos.preparar_checkout(pedido.id)
    pedido.refresh_from_db()
    valor = pedido.valor_pagamento_centavos / 100
    servicos.processar_evento(EventoAsaas.objects.create(
        event_id=event_id, tipo='CHECKOUT_PAID', payload={
            'id': event_id, 'event': 'CHECKOUT_PAID', 'checkout': {
                'id': pedido.checkout_id, 'items': [{'quantity': 1, 'value': valor}]}}).id)
    pedido.refresh_from_db()
    return pedido


try:
    with transaction.atomic(), \
            mock.patch('django.db.transaction.on_commit', imediato), \
            mock.patch('contratacao.tasks.preparar_checkout_task.delay') as delay_checkout, \
            mock.patch.object(asaas, 'criar_checkout', side_effect=checkout_simulado):
        Configuracao.objects.update_or_create(singleton=True, defaults={'ativo': True})
        su = User.objects.create_superuser(email=f'su-{uuid.uuid4().hex[:6]}{SUFIXO}', password='Senha-forte-123!')

        print('=== 1. o primeiro período nasce no aceite ===')
        dono, clinica, aceite = contratar(PlanCode.COMPLETE, 'trimestral', '661100220001')
        vig = Vigencia.objects.get(tenant=clinica)
        conferir('um período, do aceite, até o fim do aceite (três meses)',
                 vig.origem == 'aceite' and vig.aceite_id == aceite.id and vig.fim == aceite.expires_at
                 and vig.fim.date() == somar_meses(aceite.created_at, 3).date())
        sec_user = User.objects.create_user(email=f'sec-{uuid.uuid4().hex[:6]}{SUFIXO}', password='Senha-forte-123!')
        sec_user.email_verified_at = timezone.now()
        sec_user.save(update_fields=['email_verified_at'])
        Membership.objects.create(tenant=clinica, user=sec_user, roles=[Role.SECRETARY],
                                  status=MembershipStatus.ACTIVE, activated_at=timezone.now())
        c_dono, c_sec = entrar(dono, clinica), entrar(sec_user, clinica)

        print('=== 2. o aviso e a janela ===')
        agora = timezone.now()
        mover_fim(vig, agora + timezone.timedelta(days=40))
        r = c_dono.get('/app/org/plano/')
        html = r.content.decode()
        conferir('fora da janela: a tela abre sem a faixa e sem o botão',
                 r.status_code == 200 and AVISO not in html and 'Disponível a partir de' in html, r.status_code)
        c_dono.post('/app/org/plano/', {'periodicidade': 'anual'})
        conferir('fora da janela: POST não cria pedido', not Pedido.objects.filter(tenant=clinica).exists())
        mover_fim(vig, agora + timezone.timedelta(days=17))
        conferir('a 16 dias do último dia: sem faixa', AVISO not in c_dono.get('/app/org/plano/').content.decode())
        mover_fim(vig, agora + timezone.timedelta(days=10))
        html = c_dono.get('/app/org/plano/').content.decode()
        conferir('a 10 dias: a faixa do responsável, com o dia e o link de renovar',
                 AVISO in html and 'Não há renovação automática' in html
                 and vigencias.ultimo_dia(vig.fim).strftime('%d/%m/%Y') in html and '/app/org/plano/' in html)
        conferir('e o botão de ir ao pagamento, com as três vigências',
                 'Ir para o pagamento' in html and html.count('name="periodicidade"') == 3)
        r = c_sec.get(reverse('reporting:dashboard'), follow=True)
        conferir('a secretária não vê a faixa', r.status_code == 200 and AVISO not in r.content.decode(),
                 r.status_code)
        conferir('nem abre a tela do plano', c_sec.get('/app/org/plano/').status_code in (403, 404))
        c_sec.post('/app/org/plano/', {'periodicidade': 'anual'})
        conferir('nem renova', not Pedido.objects.filter(tenant=clinica).exists())

        print('=== 3. renovar ===')
        Configuracao.objects.update(ativo=False)
        c_dono.post('/app/org/plano/', {'periodicidade': 'anual'})
        conferir('checkout desligado: recusado sem pedido', not Pedido.objects.filter(tenant=clinica).exists())
        conferir('e a tela diz que está fora do ar', 'fora do ar' in c_dono.get('/app/org/plano/').content.decode())
        Configuracao.objects.update(ativo=True)
        r = c_dono.post('/app/org/plano/', {'periodicidade': 'mensal'})
        conferir('período inventado: 400 e nenhum pedido',
                 r.status_code == 400 and not Pedido.objects.filter(tenant=clinica).exists(), r.status_code)
        r = c_dono.post('/app/org/plano/', {'periodicidade': 'anual'})
        pedido = Pedido.objects.get(tenant=clinica)
        preco = preco_na_periodicidade('complete', 'anual')
        conferir('na janela: o pedido nasce com a clínica e leva à página do pedido',
                 r.status_code == 302 and r['Location'] == f'/contratar/pedido/{pedido.id}/', r.get('Location'))
        conferir('com o plano da clínica, o anual do catálogo e quem pediu',
                 pedido.plano == 'complete' and pedido.periodicidade == 'anual'
                 and pedido.valor_pagamento_centavos == preco['pagamento'] and pedido.solicitado_por_id == dono.id
                 and pedido.email == dono.email)
        conferir('o checkout vai ao worker', delay_checkout.call_count >= 1)
        conferir('a trilha registra o pedido de renovação', AuditEvent.objects.filter(
            action='contratacao.renovacao_pedida', tenant_id=clinica.id).exists())
        r = c_dono.post('/app/org/plano/', {'periodicidade': 'trimestral'})
        conferir('o segundo clique volta ao mesmo pedido, sem abrir outro',
                 Pedido.objects.filter(tenant=clinica).count() == 1
                 and r['Location'] == f'/contratar/pedido/{pedido.id}/')
        servicos.preparar_checkout(pedido.id)
        corpo = checkout_simulado.ultimo
        conferir('o checkout diz que é renovação, avulso, sem assinatura',
                 'Renovação' in corpo['items'][0]['description'] and corpo['chargeTypes'] == ['DETACHED']
                 and 'subscription' not in corpo, corpo['items'][0]['description'])
        r = c_dono.get(f'/contratar/pedido/{pedido.id}/?retorno=pago')
        conferir('a página do pedido diz "Renovação" e espera', 'Renovação do plano' in r.content.decode()
                 and 'Um momento' in r.content.decode())

        print('=== 4. o pagamento abre o período seguinte ===')
        fim_antes = vig.fim
        mail.outbox = []
        pedido = pagar(pedido, 'evt_renova_1')
        nova = Vigencia.objects.filter(pedido=pedido).first()
        conferir('pago: um período novo, de renovação', pedido.status == StatusPedido.PAGO and nova is not None
                 and nova.origem == 'renovacao' and pedido.convite_id is None)
        conferir('emendado no fim do atual (pagar antes não encurta nada), por doze meses',
                 nova and nova.inicio == fim_antes and nova.fim == somar_meses(fim_antes, 12),
                 nova and (nova.inicio, nova.fim))
        clinica.refresh_from_db()
        conferir('o plano não mudou', clinica.plan == 'complete')
        conferir('e-mail a quem renovou e ao console',
                 any(dono.email in m.to and 'Renovação confirmada' in m.subject for m in mail.outbox)
                 and any(su.email in m.to and 'Renovação paga' in m.subject for m in mail.outbox))
        conferir('a faixa some', AVISO not in c_dono.get('/app/org/plano/').content.decode())
        r = c_dono.get(f'/contratar/pedido/{pedido.id}/')
        conferir('a página do pedido mostra o novo período',
                 'Renovação confirmada' in r.content.decode()
                 and nova.ultimo_dia.strftime('%d/%m/%Y') in r.content.decode())
        servicos.processar_evento(EventoAsaas.objects.create(
            event_id='evt_renova_1b', tipo='CHECKOUT_PAID', payload={
                'id': 'evt_renova_1b', 'event': 'CHECKOUT_PAID',
                'checkout': {'id': pedido.checkout_id}}).id)
        conferir('o aviso repetido não abre outro período', Vigencia.objects.filter(tenant=clinica).count() == 2)
        outro = vigencias.criar_pedido_de_renovacao(clinica, dono, 'trimestral')
        outro = pagar(outro, 'evt_renova_2')
        terceira = Vigencia.objects.filter(pedido=outro).first()
        conferir('um segundo pagamento emenda depois do primeiro',
                 terceira and terceira.inicio == nova.fim and terceira.fim == somar_meses(nova.fim, 3))
        conferir('a trilha registra as renovações', AuditEvent.objects.filter(
            action='contratacao.renovado', tenant_id=clinica.id).count() == 2)

        print('=== 5. os e-mails do dia ===')
        dono_b, clinica_b, _ = contratar(PlanCode.BASIC, 'semestral', '661100230001')
        vig_b = mover_fim(Vigencia.objects.get(tenant=clinica_b), agora + timezone.timedelta(days=9))
        dono_c, clinica_c, _ = contratar(PlanCode.BASIC, 'anual', '661100240001')
        vig_c = mover_fim(Vigencia.objects.get(tenant=clinica_c), agora - timezone.timedelta(days=2))
        mail.outbox = []
        vigencias.avisar(agora)
        conferir('quinze dias antes: um e-mail ao responsável, com o link da tela',
                 sum(1 for m in mail.outbox if dono_b.email in m.to and 'vence em' in m.subject) == 1
                 and any('/app/org/plano/' in m.body for m in mail.outbox if dono_b.email in m.to))
        conferir('vencida: um e-mail ao responsável e um ao console',
                 sum(1 for m in mail.outbox if dono_c.email in m.to and 'venceu' in m.subject) == 1
                 and any(su.email in m.to and 'Vigência vencida' in m.subject for m in mail.outbox))
        conferir('a clínica com período pago à frente não recebe nada',
                 not any(dono.email in m.to for m in mail.outbox))
        mail.outbox = []
        vigencias.avisar(agora + timezone.timedelta(hours=24))
        conferir('no dia seguinte, nenhum e-mail repetido',
                 not any(dono_b.email in m.to or dono_c.email in m.to for m in mail.outbox),
                 [m.subject for m in mail.outbox])
        clinica_c.refresh_from_db()
        conferir('vencida continua no plano e ativa', clinica_c.plan == 'basic' and clinica_c.status == 'active')
        html = entrar(dono_c, clinica_c).get('/app/org/plano/').content.decode()
        conferir('a faixa diz que venceu e que nada foi bloqueado',
                 AVISO in html and 'venceu em' in html and 'Nada foi apagado nem bloqueado' in html)
        pedido_c = vigencias.criar_pedido_de_renovacao(clinica_c, dono_c, 'trimestral')
        antes = timezone.now()
        pedido_c = pagar(pedido_c, 'evt_renova_c')
        nova_c = Vigencia.objects.get(pedido=pedido_c)
        conferir('renovar depois de vencido começa agora, e não no fim que passou',
                 nova_c.inicio >= antes and nova_c.fim == somar_meses(nova_c.inicio, 3))

        print('=== 6. o plano trocado no console cala o aviso ===')
        clinica_b.plan = PlanCode.FREE
        clinica_b.save(update_fields=['plan'])
        conferir('sem situação nem faixa', vigencias.situacao(clinica_b) is None
                 and AVISO not in entrar(dono_b, clinica_b).get('/app/org/plano/').content.decode())

        print('=== 7. o console ===')
        dispositivo = TOTPDevice.objects.create(user=su, name='roteiro-renovacao', confirmed=True)
        s = Client(SERVER_NAME='localhost')
        s.force_login(su)
        requisicao = type('R', (), {'session': s.session, 'user': su})()
        otp_login(requisicao, dispositivo)
        from accounts.mfa import mark_recent_mfa
        mark_recent_mfa(requisicao)
        requisicao.session.save()
        s.cookies['sessionid'] = requisicao.session.session_key
        _, clinica_d, _ = contratar(PlanCode.CUSTOM, 'anual', '661100250001')
        conferir('o Personalizado não ganha período no aceite', not Vigencia.objects.filter(tenant=clinica_d).exists())
        s.post('/instalacao/contratacao/', {'acao': 'registrar_vigencia', 'tenant': str(clinica_d.id),
                                            'periodicidade': 'semestral', 'inicio': '2026-11-01', 'nota': ''})
        conferir('sem dizer de onde vem: nada registrado', not Vigencia.objects.filter(tenant=clinica_d).exists())
        s.post('/instalacao/contratacao/', {'acao': 'registrar_vigencia', 'tenant': 'nao-e-uuid',
                                            'periodicidade': 'semestral', 'inicio': '2026-11-01', 'nota': 'x'})
        conferir('clínica inválida: nada registrado', Vigencia.objects.filter(origem='console').count() == 0)
        s.post('/instalacao/contratacao/', {'acao': 'registrar_vigencia', 'tenant': str(clinica_d.id),
                                            'periodicidade': 'semestral', 'inicio': '2026-11-01',
                                            'valor': '1.234,50', 'nota': 'Pix recebido em 01/11'})
        manual = Vigencia.objects.filter(tenant=clinica_d).first()
        conferir('registrado: seis meses a partir da meia-noite de Brasília, com o valor',
                 manual is not None and manual.origem == 'console' and manual.valor_centavos == 123450
                 and timezone.localtime(manual.inicio).strftime('%d/%m/%Y %H:%M') == '01/11/2026 00:00'
                 and manual.ultimo_dia.strftime('%d/%m/%Y') == '30/04/2027',
                 manual and (manual.valor_centavos, manual.inicio, manual.fim))
        conferir('na trilha', AuditEvent.objects.filter(action='ops.vigencia_registrada', actor=su).exists())
        html = s.get('/instalacao/contratacao/').content.decode()
        conferir('a tela lista as vigências e marca o pedido de renovação',
                 'Vigências' in html and 'renovação' in html and 'Pix recebido em 01/11' in html)
        conferir('quem não é superadministrador não registra',
                 c_dono.post('/instalacao/contratacao/', {'acao': 'registrar_vigencia'}).status_code in (302, 403, 404))

        raise Desfazer
except Desfazer:
    pass

if falhas:
    raise SystemExit(f'FALHA: {len(falhas)} verificação(ões): ' + '; '.join(falhas))
print('OK: o período nasce no aceite, o responsável é avisado quinze dias antes e renova pelo\n'
      '    sistema, o pagamento emenda o período seguinte, e vencer não bloqueia nada.')
