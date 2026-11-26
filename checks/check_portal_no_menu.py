"""O que chega pelo portal sai do sino e fica no menu Portal (2026-11-26).

Pedido do titular: as solicitacoes e os exames enviados pelo portal nao
avisam mais no sino; ficam no menu, num grupo "Portal" com dois itens --
Solicitacoes e Exames enviados --, cada um com o contador amarelo do que
espera alguem, e o grupo com a soma.

O que se cobra:

- um pedido feito pelo caminho real do portal (`portal.submit`) nao cria
  aviso no sino;
- o medico ve o grupo Portal, os dois itens e os contadores certos (o de
  solicitacoes sobe com o pedido, o total e a soma);
- a secretaria nao ve o grupo, e a clinica B nao conta o pedido da A;
- o item "Assinatura" do menu nao acende na tela de exames enviados.

O detalhe dos exames (lista, Ciente, alerta do prontuario) esta em
`check_exames_do_portal`.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import re

from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.test import Client, RequestFactory

from documents import portal
from documents.models import DocumentRequest, DocumentRequestKind
from notifications.models import Notification
from patients.models import Patient, PatientStatus, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


clinica = Tenant.objects.get(slug='demo-clinica-a')
clinica_b = Tenant.objects.get(slug='demo-clinica-b')


def vinculo(tenant, papel):
    return Membership.objects.filter(
        tenant=tenant, roles__contains=[papel], status=MembershipStatus.ACTIVE,
    ).select_related('user').first()


def logado(m, tenant):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def contador(corpo, rotulo):
    m = re.search(rotulo + r'\s*<span class="badge[^>]*>(\d+)</span>', corpo)
    return int(m.group(1)) if m else 0


def portal_do_menu(corpo):
    m = re.search(r'<span class="nxl-mtext">Portal</span>\s*<span class="badge[^>]*>\s*(\d+)\s*</span>', corpo)
    return int(m.group(1)) if m else 0


medico = vinculo(clinica, Role.DOCTOR)
secretaria = vinculo(clinica, Role.SECRETARY)
medico_b = vinculo(clinica_b, Role.DOCTOR)
doc = logado(medico, clinica)

paciente = Patient.objects.create(
    tenant=clinica, full_name='ROTEIRO PORTAL NO MENU', registration_stage=RegistrationStage.COMPLETE,
    status=PatientStatus.ACTIVE, birth_date_unknown_reason='Roteiro de verificacao.',
)
pedidos = []
try:
    print('=== 1. o pedido do portal nao avisa no sino ===')
    antes_menu = doc.get('/app/patients/').content.decode()
    solic_antes = contador(antes_menu, 'Solicitações')
    exames_antes = contador(antes_menu, 'Exames enviados')
    avisos_antes = Notification.objects.filter(kind='portal_request').count()
    b_antes = (contador(logado(medico_b, clinica_b).get('/app/patients/').content.decode(), 'Solicitações')
               if medico_b else 0)

    cache.delete('portal:submit:127.0.0.1')
    req = RequestFactory().post('/solicitacoes/', REMOTE_ADDR='127.0.0.1')
    req.session = SessionStore()
    pedido = portal.submit(
        req, clinica, paciente, DocumentRequestKind.PRESCRIPTION_SIMPLE,
        'ROTEIRO PORTAL NO MENU', True, {'medicacoes': [{'nome': 'Keppra', 'dose': '', 'uso': ''}]},
    )
    pedidos.append(pedido.id)
    confere(Notification.objects.filter(kind='portal_request').count() == avisos_antes,
            'nenhum aviso de solicitacao no sino')

    print('=== 2. o grupo Portal e os contadores ===')
    menu = doc.get('/app/patients/').content.decode()
    confere('<span class="nxl-mtext">Portal</span>' in menu, 'o medico ve o grupo Portal')
    confere('/app/documents/solicitacoes/' in menu and '/app/documents/exames-do-portal/' in menu,
            'com Solicitacoes e Exames enviados')
    confere(contador(menu, 'Solicitações') == solic_antes + 1,
            f'o contador de solicitacoes subiu ({solic_antes} -> {contador(menu, "Solicitações")})')
    confere(contador(menu, 'Exames enviados') == exames_antes, 'o de exames nao mudou')
    confere(portal_do_menu(menu) == contador(menu, 'Solicitações') + contador(menu, 'Exames enviados'),
            f'o total do grupo e a soma ({portal_do_menu(menu)})')

    print('=== 3. quem nao ve, e quem nao conta ===')
    if secretaria:
        corpo = logado(secretaria, clinica).get('/app/patients/').content.decode()
        confere('<span class="nxl-mtext">Portal</span>' not in corpo, 'a secretaria nao ve o grupo')
    if medico_b:
        corpo_b = logado(medico_b, clinica_b).get('/app/patients/').content.decode()
        confere(contador(corpo_b, 'Solicitações') == b_antes, 'a clinica B nao conta o pedido da A')

    print('=== 4. o menu acende o item certo ===')
    tela = doc.get('/app/documents/exames-do-portal/').content.decode()
    trecho = tela[tela.find('<span class="nxl-mtext">Assinatura</span>') - 400:
                  tela.find('<span class="nxl-mtext">Assinatura</span>')]
    confere('active' not in trecho.split('<li')[-1], 'Assinatura nao acende na tela de exames enviados')
    confere('nxl-menu-visible' in tela[tela.find('<span class="nxl-mtext">Portal</span>'):][:3000],
            'e o submenu do Portal abre')
finally:
    DocumentRequest.objects.filter(id__in=pedidos).delete()
    Patient.objects.filter(id=paciente.id).delete()

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: solicitacoes e exames do portal fora do sino, no menu Portal com os contadores.')
