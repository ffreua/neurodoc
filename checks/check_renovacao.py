"""Vigência por período e renovação pelo sistema (1.47, contrato 2.2) tenta ser quebrada.

Cada forma de pagamento é um período — doze, seis ou três meses, pago de uma
vez —, nada renova sozinho, e o responsável renova em Organização → Plano e
renovação. A Asaas é **simulada**, como em `check_contratacao`.

O que este roteiro cobra (contrato 2.2, decisões da Dra. Karina):

- **o primeiro período** nasce no aceite do plano pago, com o fim do aceite;
- **o aviso**: fora dos trinta dias, nada; dentro, a faixa no alto da tela,
  **só para o responsável** (a secretária não vê nem abre a tela);
- **renovar pede aceite novo**: sem "li e aceito" ou sem os poderes, 400 e
  nenhum pedido; com eles, o pedido grava versão, hash, texto inteiro, hora e
  navegador, e diz que não há arrependimento — sem um segundo
  `ContractAcceptance`; fora da janela e com o checkout desligado, recusado;
  o segundo clique reaproveita o pedido aberto;
- **o pagamento** abre o período seguinte **emendado no fim do atual**, com o
  e-mail dizendo a versão aceita; o aviso repetido não abre outro período;
- **os e-mails**: trinta dias antes e quinze, uma vez cada (o período
  registrado já nos quinze ganha só o segundo); vencida, ao responsável com
  a data do Gratuito e ao console;
- **o Gratuito**: com catorze dias de vencida, nada; com dezesseis, a clínica
  passa ao Gratuito, fica o médico mais antigo, os outros perdem o papel
  (suspenso quem não tinha outro), e-mail uma vez; a faixa e a tela oferecem
  renovar o plano de antes, e o pagamento devolve plano e médicos até o
  limite;
- **o que não entra**: a clínica sem período (as antigas), a de plano trocado
  no console e a encerrada;
- **o console** registra período à mão, recusa clínica no Gratuito que não
  venceu, e devolve o plano à que passou ao Gratuito.

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
from tenancy import contract
from tenancy.contracts import sha_do_texto, somar_meses
from tenancy.invitations import issue_invitation
from tenancy.models import ContractAcceptance, InvitationPurpose, Membership, MembershipStatus, Role
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
        aviso_30_em=None, aviso_15_em=None, aviso_vencido_em=None)
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


def renovar(cliente, periodicidade, aceite=True, poderes=True):
    dados = {'periodicidade': periodicidade}
    if aceite:
        dados['aceite'] = 'on'
    if poderes:
        dados['poderes'] = 'on'
    return cliente.post('/app/org/plano/', dados, HTTP_USER_AGENT='RoteiroRenovacao/1.0')


def medico(tenant, papeis, dias_atras):
    u = User.objects.create_user(email=f'med-{uuid.uuid4().hex[:6]}{SUFIXO}', password='Senha-forte-123!')
    return Membership.objects.create(
        tenant=tenant, user=u, roles=papeis, status=MembershipStatus.ACTIVE,
        activated_at=timezone.now() - timezone.timedelta(days=dias_atras))


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
        conferir('o aceite do cadastro é o da 2.2, com os sete dias de arrependimento',
                 aceite.version == contract.VERSAO == '2.2'
                 and round((aceite.withdrawal_deadline - aceite.created_at).total_seconds() / 86400) == 7)
        sec_user = User.objects.create_user(email=f'sec-{uuid.uuid4().hex[:6]}{SUFIXO}', password='Senha-forte-123!')
        sec_user.email_verified_at = timezone.now()
        sec_user.save(update_fields=['email_verified_at'])
        Membership.objects.create(tenant=clinica, user=sec_user, roles=[Role.SECRETARY],
                                  status=MembershipStatus.ACTIVE, activated_at=timezone.now())
        c_dono, c_sec = entrar(dono, clinica), entrar(sec_user, clinica)

        print('=== 2. o aviso e a janela de trinta dias ===')
        agora = timezone.now()
        mover_fim(vig, agora + timezone.timedelta(days=45))
        r = c_dono.get('/app/org/plano/')
        html = r.content.decode()
        conferir('fora da janela: a tela abre sem a faixa e sem o botão, e diz os dois avisos',
                 r.status_code == 200 and AVISO not in html and 'Disponível a partir de' in html
                 and 'com 30 e com 15 dias' in html, r.status_code)
        renovar(c_dono, 'anual')
        conferir('fora da janela: POST não cria pedido', not Pedido.objects.filter(tenant=clinica).exists())
        mover_fim(vig, agora + timezone.timedelta(days=33))
        conferir('a 32 dias do último dia: sem faixa', AVISO not in c_dono.get('/app/org/plano/').content.decode())
        mover_fim(vig, agora + timezone.timedelta(days=25))
        html = c_dono.get('/app/org/plano/').content.decode()
        conferir('a 24 dias: a faixa do responsável, com o dia e o link de renovar',
                 AVISO in html and 'Não há renovação automática' in html
                 and vigencias.ultimo_dia(vig.fim).strftime('%d/%m/%Y') in html and '/app/org/plano/' in html)
        conferir('e o botão de ir ao pagamento, com as três vigências e as duas caixas do aceite',
                 'Ir para o pagamento' in html and html.count('name="periodicidade"') == 3
                 and 'name="aceite"' in html and 'name="poderes"' in html)
        conferir('o aceite aponta o contrato, diz a versão e que não há arrependimento',
                 '/contrato/' in html and 'versão 2.2' in html and 'não há prazo de arrependimento' in html)
        r = c_sec.get(reverse('reporting:dashboard'), follow=True)
        conferir('a secretária não vê a faixa', r.status_code == 200 and AVISO not in r.content.decode(),
                 r.status_code)
        conferir('nem abre a tela do plano', c_sec.get('/app/org/plano/').status_code in (403, 404))
        renovar(c_sec, 'anual')
        conferir('nem renova', not Pedido.objects.filter(tenant=clinica).exists())

        print('=== 3. renovar pede aceite novo ===')
        Configuracao.objects.update(ativo=False)
        renovar(c_dono, 'anual')
        conferir('checkout desligado: recusado sem pedido', not Pedido.objects.filter(tenant=clinica).exists())
        conferir('e a tela diz que está fora do ar', 'fora do ar' in c_dono.get('/app/org/plano/').content.decode())
        Configuracao.objects.update(ativo=True)
        r = renovar(c_dono, 'mensal')
        conferir('período inventado: 400 e nenhum pedido',
                 r.status_code == 400 and not Pedido.objects.filter(tenant=clinica).exists(), r.status_code)
        r = renovar(c_dono, 'anual', aceite=False)
        conferir('sem "li e aceito": 400, a recusa em português e nenhum pedido',
                 r.status_code == 400 and 'é preciso aceitar o contrato' in r.content.decode()
                 and not Pedido.objects.filter(tenant=clinica).exists(), r.status_code)
        r = renovar(c_dono, 'anual', poderes=False)
        conferir('sem declarar poderes: 400 e nenhum pedido',
                 r.status_code == 400 and not Pedido.objects.filter(tenant=clinica).exists(), r.status_code)
        r = renovar(c_dono, 'anual')
        pedido = Pedido.objects.get(tenant=clinica)
        preco = preco_na_periodicidade('complete', 'anual')
        conferir('com o aceite: o pedido nasce com a clínica e leva à página do pedido',
                 r.status_code == 302 and r['Location'] == f'/contratar/pedido/{pedido.id}/', r.get('Location'))
        conferir('com o plano da clínica, o anual do catálogo e quem pediu',
                 pedido.plano == 'complete' and pedido.periodicidade == 'anual'
                 and pedido.valor_pagamento_centavos == preco['pagamento'] and pedido.solicitado_por_id == dono.id
                 and pedido.email == dono.email)
        conferir('o aceite gravado no pedido: versão, hash, texto inteiro, hora, navegador e poderes',
                 pedido.contrato_versao == '2.2' and pedido.aceite_sha256 == sha_do_texto()
                 and pedido.aceite_texto == contract.texto_simples() and pedido.aceite_em is not None
                 and pedido.aceite_user_agent == 'RoteiroRenovacao/1.0' and pedido.poderes_declarados)
        conferir('o texto aceito diz que a renovação não tem arrependimento',
                 'não se aplica às renovações' in pedido.aceite_texto)
        conferir('o checkout vai ao worker', delay_checkout.call_count >= 1)
        conferir('a trilha registra o pedido com a versão e o hash', AuditEvent.objects.filter(
            action='contratacao.renovacao_pedida', tenant_id=clinica.id,
            integrity_metadata__contrato_sha256=pedido.aceite_sha256).exists())
        r = renovar(c_dono, 'trimestral')
        conferir('o segundo clique volta ao mesmo pedido, sem abrir outro',
                 Pedido.objects.filter(tenant=clinica).count() == 1
                 and r['Location'] == f'/contratar/pedido/{pedido.id}/')
        conferir('nenhum segundo ContractAcceptance na renovação',
                 ContractAcceptance.objects.filter(tenant=clinica).count() == 1)
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
        confirmacao = [m for m in mail.outbox if dono.email in m.to and 'Renovação confirmada' in m.subject]
        conferir('e-mail a quem renovou, com a versão aceita e sem arrependimento, e ao console',
                 len(confirmacao) == 1 and 'versão 2.2' in confirmacao[0].body
                 and 'não há prazo de arrependimento' in confirmacao[0].body
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

        print('=== 5. os e-mails de 30 e 15 dias, e o de vencida ===')
        dono_b, clinica_b, _ = contratar(PlanCode.BASIC, 'semestral', '661100230001')
        vig_b = mover_fim(Vigencia.objects.get(tenant=clinica_b), agora + timezone.timedelta(days=25))
        dono_e, clinica_e, _ = contratar(PlanCode.BASIC, 'trimestral', '661100260001')
        mover_fim(Vigencia.objects.get(tenant=clinica_e), agora + timezone.timedelta(days=9))
        dono_c, clinica_c, _ = contratar(PlanCode.BASIC, 'anual', '661100240001')
        vig_c = mover_fim(Vigencia.objects.get(tenant=clinica_c), agora - timezone.timedelta(days=2))
        mail.outbox = []
        vigencias.avisar(agora)

        def de(dono_x, trecho):
            return [m for m in mail.outbox if dono_x.email in m.to and trecho in m.subject]

        conferir('trinta dias antes: um e-mail, com o link, o Gratuito e o arrependimento',
                 len(de(dono_b, 'vence em')) == 1 and '/app/org/plano/' in de(dono_b, 'vence em')[0].body
                 and 'plano Gratuito' in de(dono_b, 'vence em')[0].body
                 and 'não há prazo de arrependimento' in de(dono_b, 'vence em')[0].body)
        vig_b.refresh_from_db()
        conferir('carimbado como o de 30, e não o de 15', vig_b.aviso_30_em and vig_b.aviso_15_em is None)
        conferir('registrada já dentro dos quinze dias: só o de 15, uma vez',
                 len(de(dono_e, 'vence em')) == 1
                 and Vigencia.objects.filter(tenant=clinica_e, aviso_15_em__isnull=False,
                                             aviso_30_em__isnull=False).exists())
        conferir('vencida: um e-mail ao responsável, com a data do Gratuito, e um ao console',
                 len(de(dono_c, 'venceu')) == 1
                 and vigencias.situacao(clinica_c)['gratuito_em'].strftime('%d/%m/%Y') in de(dono_c, 'venceu')[0].body
                 and any(su.email in m.to and 'Vigência vencida' in m.subject for m in mail.outbox))
        conferir('a clínica com período pago à frente não recebe nada',
                 not any(dono.email in m.to for m in mail.outbox))
        mail.outbox = []
        vigencias.avisar(agora + timezone.timedelta(hours=24))
        conferir('no dia seguinte, nenhum e-mail repetido',
                 not any(x.email in m.to for x in (dono_b, dono_c, dono_e) for m in mail.outbox),
                 [m.subject for m in mail.outbox])
        mover_fim(vig_b, agora + timezone.timedelta(days=10))
        Vigencia.objects.filter(id=vig_b.id).update(aviso_30_em=agora)
        mail.outbox = []
        vigencias.avisar(agora)
        conferir('chegando aos quinze dias: o segundo e-mail, uma vez', len(de(dono_b, 'vence em')) == 1)
        clinica_c.refresh_from_db()
        conferir('vencida há dois dias continua no plano e ativa',
                 clinica_c.plan == 'basic' and clinica_c.status == 'active')
        html = entrar(dono_c, clinica_c).get('/app/org/plano/').content.decode()
        conferir('a faixa diz que venceu e quando passa ao Gratuito',
                 AVISO in html and 'venceu em' in html and 'passa ao plano Gratuito em' in html)
        pedido_c = vigencias.criar_pedido_de_renovacao(clinica_c, dono_c, 'trimestral')
        antes = timezone.now()
        pedido_c = pagar(pedido_c, 'evt_renova_c')
        nova_c = Vigencia.objects.get(pedido=pedido_c)
        conferir('renovar depois de vencido começa agora, e não no fim que passou',
                 nova_c.inicio >= antes and nova_c.fim == somar_meses(nova_c.inicio, 3))

        print('=== 6. quinze dias depois do fim, o Gratuito ===')
        dono_g, clinica_g, _ = contratar(PlanCode.BASIC, 'trimestral', '661100270001')
        antigo = medico(clinica_g, [Role.DOCTOR], 30)
        novo = medico(clinica_g, [Role.DOCTOR], 2)
        socio = medico(clinica_g, [Role.DOCTOR, Role.MANAGER], 1)
        vig_g = mover_fim(Vigencia.objects.get(tenant=clinica_g), agora - timezone.timedelta(days=14))
        mail.outbox = []
        vigencias.avisar(agora)
        clinica_g.refresh_from_db()
        conferir('com catorze dias de vencida: ainda no plano', clinica_g.plan == 'basic')
        conferir('rebaixar antes do prazo recusa', vigencias.rebaixar(vig_g.id, agora) is False)
        vig_g = mover_fim(vig_g, agora - timezone.timedelta(days=16))
        mail.outbox = []
        resultado = vigencias.avisar(agora)
        clinica_g.refresh_from_db()
        vig_g.refresh_from_db()
        conferir('com dezesseis dias: o Gratuito, carimbado', clinica_g.plan == 'free'
                 and vig_g.rebaixada_em is not None and resultado['gratuito'] == 1, resultado)
        for m in (antigo, novo, socio):
            m.refresh_from_db()
        conferir('fica o médico mais antigo; os outros perdem o papel',
                 Role.DOCTOR in antigo.roles and Role.DOCTOR not in novo.roles and Role.DOCTOR not in socio.roles)
        conferir('quem não tinha outro papel é suspenso; o sócio gestor continua ativo',
                 novo.status == MembershipStatus.SUSPENDED and socio.status == MembershipStatus.ACTIVE
                 and Role.MANAGER in socio.roles)
        conferir('os retirados ficam anotados no período', len(vig_g.medicos_retirados) == 2)
        conferir('o dono continua ativo e responsável',
                 Membership.objects.filter(tenant=clinica_g, user=dono_g, status=MembershipStatus.ACTIVE,
                                           roles__contains=[Role.OWNER]).exists())
        conferir('e-mail ao responsável e ao console', len(de(dono_g, 'passou ao plano Gratuito')) == 1
                 and any(su.email in m.to and 'passou ao Gratuito' in m.subject for m in mail.outbox))
        conferir('na trilha', AuditEvent.objects.filter(action='contratacao.passou_ao_gratuito',
                                                        tenant_id=clinica_g.id).exists())
        mail.outbox = []
        vigencias.avisar(agora + timezone.timedelta(days=1))
        conferir('a rodada seguinte não repete nada', not any(dono_g.email in m.to for m in mail.outbox)
                 and vigencias.rebaixar(vig_g.id, agora) is False)
        c_g = entrar(dono_g, clinica_g)
        html = c_g.get('/app/org/plano/').content.decode()
        conferir('a faixa diz que passou ao Gratuito, e a tela oferece renovar o Básico',
                 AVISO in html and 'passou ao plano Gratuito' in html and 'Ir para o pagamento' in html
                 and 'Plano Básico' in html)
        r = renovar(c_g, 'semestral')
        pedido_g = Pedido.objects.get(tenant=clinica_g)
        conferir('o pedido é do Básico, e não do Gratuito', r.status_code == 302 and pedido_g.plano == 'basic'
                 and pedido_g.valor_pagamento_centavos == preco_na_periodicidade('basic', 'semestral')['pagamento'])
        antes = timezone.now()
        pedido_g = pagar(pedido_g, 'evt_renova_g')
        clinica_g.refresh_from_db()
        for m in (antigo, novo, socio):
            m.refresh_from_db()
        nova_g = Vigencia.objects.get(pedido=pedido_g)
        conferir('pago: o plano volta, com período começando agora',
                 clinica_g.plan == 'basic' and nova_g.inicio >= antes)
        conferir('e os médicos voltam até o limite do Básico (dois)',
                 Role.DOCTOR in antigo.roles
                 and sum(1 for m in (novo, socio) if Role.DOCTOR in m.roles) == 1)
        conferir('na trilha', AuditEvent.objects.filter(action='contratacao.plano_restabelecido',
                                                        tenant_id=clinica_g.id).exists())
        conferir('a faixa some', AVISO not in c_g.get('/app/org/plano/').content.decode())

        print('=== 7. o que não entra na regra ===')
        dono_h, clinica_h, _ = contratar(PlanCode.BASIC, 'anual', '661100280001')
        Vigencia.objects.filter(tenant=clinica_h).delete()
        mail.outbox = []
        vigencias.avisar(agora)
        clinica_h.refresh_from_db()
        conferir('clínica sem período (as antigas): sem situação, sem aviso, sem Gratuito',
                 vigencias.situacao(clinica_h) is None and clinica_h.plan == 'basic'
                 and not any(dono_h.email in m.to for m in mail.outbox)
                 and AVISO not in entrar(dono_h, clinica_h).get('/app/org/plano/').content.decode())
        clinica_b.plan = PlanCode.COMPLETE
        clinica_b.save(update_fields=['plan'])
        conferir('plano trocado no console: sem situação nem faixa', vigencias.situacao(clinica_b) is None
                 and AVISO not in entrar(dono_b, clinica_b).get('/app/org/plano/').content.decode())
        vig_b = mover_fim(Vigencia.objects.filter(tenant=clinica_b).first(), agora - timezone.timedelta(days=20))
        vigencias.avisar(agora)
        clinica_b.refresh_from_db()
        conferir('e não passa ao Gratuito pelo período antigo', clinica_b.plan == 'complete')
        clinica_b.status = 'closed'
        clinica_b.plan = PlanCode.BASIC
        clinica_b.save(update_fields=['status', 'plan'])
        conferir('clínica encerrada não é rebaixada', vigencias.rebaixar(vig_b.id, agora) is False)

        print('=== 8. o console ===')
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
        livre = clinica_h
        livre.plan = PlanCode.FREE
        livre.save(update_fields=['plan'])
        s.post('/instalacao/contratacao/', {'acao': 'registrar_vigencia', 'tenant': str(livre.id),
                                            'periodicidade': 'anual', 'inicio': '2026-11-01', 'nota': 'x'})
        conferir('clínica no Gratuito (sem ter vencido): nada registrado',
                 not Vigencia.objects.filter(tenant=livre).exists())
        dono_f, clinica_f, _ = contratar(PlanCode.COMPLETE, 'trimestral', '661100290001')
        vig_f = mover_fim(Vigencia.objects.get(tenant=clinica_f), agora - timezone.timedelta(days=20))
        vigencias.rebaixar(vig_f.id, agora)
        clinica_f.refresh_from_db()
        html = s.get('/instalacao/contratacao/').content.decode()
        conferir('a clínica que passou ao Gratuito aparece para registrar, e a lista diz desde quando',
                 str(clinica_f.id) in html and 'Gratuito desde' in html and clinica_f.plan == 'free')
        s.post('/instalacao/contratacao/', {'acao': 'registrar_vigencia', 'tenant': str(clinica_f.id),
                                            'periodicidade': 'anual', 'inicio': timezone.localdate().isoformat(),
                                            'nota': 'Pix recebido hoje'})
        clinica_f.refresh_from_db()
        conferir('registrar o período dela devolve o Completo',
                 clinica_f.plan == 'complete'
                 and Vigencia.objects.filter(tenant=clinica_f, origem='console', plano='complete').exists())
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
print('OK: o período nasce no aceite, o responsável é avisado com trinta e quinze dias e renova\n'
      '    pelo sistema com aceite novo, o pagamento emenda o período seguinte, e quinze dias\n'
      '    depois do fim sem renovar a clínica passa ao Gratuito — e volta ao renovar.')
