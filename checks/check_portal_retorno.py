"""O portal barra quem nao consulta ha tempo demais -- e so quem deve?

Tenta quebrar. As perguntas sao:

- a conta de meses e de calendario, ou 30 dias vezes N?
- quem consultou ontem passa, e quem consultou ha um ano nao?
- o prazo do medico vence o da clinica, e nulo herda?
- da para furar o bloqueio com uma sessao aberta antes de o medico apertar?
- da para furar indo direto em /solicitar/?
- a tela recusa sem mentir sobre o que o CFM exige?
- um medico consegue mudar o prazo de outro?
"""
import datetime

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter
from documents import portal, portal_retorno
from documents.portal_retorno import _somar_meses, bloqueio, janela_em_meses
from patients.models import Patient, PatientStatus
from tenancy.models import (
    PORTAL_REQUEST_WINDOW_DEFAULT, ClinicProfile, Membership, MembershipStatus,
    PortalRequestWindow, Role, Tenant,
)

falhas = []

clinica = Tenant.objects.get(slug='demo-clinica-a')
perfil = ClinicProfile.objects.filter(tenant=clinica).first()
medico = Membership.objects.filter(
    tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).first()

if None in (perfil, medico):
    print('  (demonstracao incompleta; roteiro pulado)')
    raise SystemExit(0)

# Estado original, devolvido no fim mesmo se o roteiro quebrar no meio.
import atexit

_original = (
    perfil.patient_portal_enabled, perfil.patient_portal_max_months,
    medico.patient_portal_max_months,
)

# Paciente proprio, e nao o da demonstracao.
#
# A primeira versao deste roteiro empurrava os atendimentos semeados 4000
# dias para tras para simular "consulta antiga" -- e nao os devolvia.
# `check_g10` quebrou por causa disso, num roteiro que nao tem nada a ver
# com o portal. Dado de demonstracao e de quem for usar o sistema depois;
# quem precisa de um caso proprio, cria o seu.
_paciente = Patient.objects.create(
    tenant=clinica, full_name='Paciente Do Roteiro De Retorno',
    cpf='15350946056', birth_date=datetime.date(1985, 7, 20),
    status=PatientStatus.ACTIVE,
)
paciente = _paciente


def restaurar():
    perfil.patient_portal_enabled, perfil.patient_portal_max_months = _original[0], _original[1]
    perfil.save(update_fields=['patient_portal_enabled', 'patient_portal_max_months'])
    Membership.objects.filter(id=medico.id).update(patient_portal_max_months=_original[2])
    Encounter.objects.filter(tenant=clinica, patient=_paciente).delete()
    Patient.objects.filter(id=_paciente.id).delete()


atexit.register(restaurar)

print('=== 1. a conta e de meses de calendario ===')
casos = [
    (datetime.datetime(2026, 1, 31), 1, '28/02/2026'),
    (datetime.datetime(2026, 1, 31), 3, '30/04/2026'),
    (datetime.datetime(2026, 1, 31), 6, '31/07/2026'),
    (datetime.datetime(2024, 2, 29), 12, '28/02/2025'),
    (datetime.datetime(2026, 8, 15), 18, '15/02/2028'),
]
for origem, meses, esperado in casos:
    obtido = _somar_meses(origem, meses).strftime('%d/%m/%Y')
    print(f'  {origem.strftime("%d/%m/%Y")} + {meses:2} meses -> {obtido} ({esperado} esperado)')
    if obtido != esperado:
        falhas.append(f'{origem.date()} + {meses} meses deu {obtido}, e nao {esperado}')
# Trinta dias vezes seis daria 180; seis meses de calendario dao 181 a 184.
_dias = (_somar_meses(datetime.datetime(2026, 1, 1), 6) - datetime.datetime(2026, 1, 1)).days
print(f'  1/1 + 6 meses = {_dias} dias (nao 180)')
if _dias == 180:
    falhas.append('a conta de meses virou 30 dias vezes N')

print('=== 2. o padrao e 6 meses, e ele vale sem ninguem configurar ===')
print(f'  PORTAL_REQUEST_WINDOW_DEFAULT = {PORTAL_REQUEST_WINDOW_DEFAULT}')
if int(PORTAL_REQUEST_WINDOW_DEFAULT) != 6:
    falhas.append(f'o padrao deixou de ser 6 meses: {PORTAL_REQUEST_WINDOW_DEFAULT}')
esperadas = {3, 4, 6, 9, 12, 15, 18}
if set(PortalRequestWindow.values) != esperadas:
    falhas.append(f'as opcoes mudaram: {sorted(PortalRequestWindow.values)}')
print(f'  opcoes oferecidas = {sorted(PortalRequestWindow.values)}')

print('=== 3. o prazo do medico vence o da clinica; nulo herda ===')
perfil.patient_portal_max_months = 12
perfil.save(update_fields=['patient_portal_max_months'])
Membership.objects.filter(id=medico.id).update(patient_portal_max_months=None)
medico.refresh_from_db()


class _Encontro:
    def __init__(self, vinculo):
        self.physician_membership = vinculo


print(f'  clinica=12, medico=nulo -> {janela_em_meses(perfil, _Encontro(medico))} (12 esperado)')
if janela_em_meses(perfil, _Encontro(medico)) != 12:
    falhas.append('vinculo nulo nao herdou o prazo da clinica')

Membership.objects.filter(id=medico.id).update(patient_portal_max_months=3)
medico.refresh_from_db()
print(f'  clinica=12, medico=3    -> {janela_em_meses(perfil, _Encontro(medico))} (3 esperado)')
if janela_em_meses(perfil, _Encontro(medico)) != 3:
    falhas.append('o prazo do medico nao venceu o da clinica')

print(f'  sem atendimento nenhum  -> {janela_em_meses(perfil, None)} (12 esperado)')
if janela_em_meses(perfil, None) != 12:
    falhas.append('sem atendimento, a janela deixou de cair na clinica')

print('=== 4. consulta recente passa; consulta antiga nao ===')


def com_consulta(dias_atras):
    """Um atendimento datado, para exercitar a fronteira.

    So do paciente deste roteiro: nada do que ele faz alcanca o dado da
    demonstracao.
    """
    Encounter.objects.filter(tenant=clinica, patient=paciente).delete()
    return Encounter.objects.create(
        tenant=clinica, patient=paciente, physician_membership=medico,
        occurred_at=timezone.now() - datetime.timedelta(days=dias_atras),
    )


Membership.objects.filter(id=medico.id).update(patient_portal_max_months=3)
medico.refresh_from_db()
for dias, deve_bloquear in [(1, False), (80, False), (100, True), (400, True)]:
    com_consulta(dias)
    b = bloqueio(perfil, paciente)
    bloqueou = b is not None
    print(f'  ultima consulta ha {dias:4} dia(s), janela de 3 meses -> '
          f'{"bloqueado" if bloqueou else "liberado"}')
    if bloqueou != deve_bloquear:
        falhas.append(
            f'consulta ha {dias} dias com janela de 3 meses: '
            f'{"bloqueou" if bloqueou else "liberou"} e nao deveria'
        )

print('=== 5. paciente sem consulta nenhuma ===')
# O paciente deste roteiro fica sem atendimento nenhum -- e como se
# tivesse acabado de ser cadastrado e ainda nao tivesse consultado.
Encounter.objects.filter(tenant=clinica, patient=paciente).delete()
_novo = paciente
if True:                                   # mantem o bloco indentado
    b = bloqueio(perfil, _novo)
    print(f'  sem atendimento -> {"bloqueado" if b else "liberado"}  '
          f'nunca_consultou={getattr(b, "nunca_consultou", None)}')
    if b is None or not b.nunca_consultou:
        falhas.append('paciente sem nenhuma consulta nao foi bloqueado como tal')
    # E a tela dele diz outra coisa: "ainda nao temos consulta sua", e nao
    # "faz tempo demais". Sao dois casos, e confundi-los manda a pessoa
    # procurar uma consulta que nunca houve.
    perfil.patient_portal_enabled = True
    perfil.save(update_fields=['patient_portal_enabled'])
    _c = Client()
    _r = _c.post(f'/solicitacoes/{clinica.slug}/', {
        'cpf': _novo.cpf, 'birth_date': _novo.birth_date.isoformat(), 'privacy_ack': '1',
    })
    _corpo = _r.content.decode(errors='replace')
    print(f'  identificacao -> HTTP {_r.status_code}  '
          f'fala em "ainda nao"={"Ainda não temos" in _corpo}')
    if _r.status_code != 403 or 'Ainda não temos' not in _corpo:
        falhas.append('a tela nao distinguiu "nunca consultou" de "consulta antiga"')


print('=== 6. o portal de verdade: as tres portas ===')
perfil.patient_portal_enabled = True
perfil.save(update_fields=['patient_portal_enabled'])
com_consulta(400)                      # antigo, com janela de 3 meses
Membership.objects.filter(id=medico.id).update(patient_portal_max_months=3)

dados = {
    'cpf': paciente.cpf,
    'birth_date': paciente.birth_date.isoformat(),
    'privacy_ack': '1',
}
c = Client()
r = c.post(f'/solicitacoes/{clinica.slug}/', dados)
corpo = r.content.decode(errors='replace')
print(f'  identificacao com consulta antiga -> HTTP {r.status_code}')
if r.status_code != 403:
    falhas.append(f'a identificacao respondeu {r.status_code} para consulta antiga')
if 'art. 37' not in corpo:
    falhas.append('a tela de bloqueio nao cita o art. 37 do Codigo de Etica Medica')
if 'não estabelece um número de meses' not in corpo:
    falhas.append('a tela de bloqueio deixou de esclarecer que o CFM nao fixa o prazo')
# Nao pode dizer que o CFM exige N meses: seria inventar uma regra.
import re

if re.search(r'CFM[^.]{0,60}(exige|determina|obriga)[^.]{0,30}\d+\s*meses', corpo):
    falhas.append('a tela atribui ao CFM um prazo em meses que ele nao fixa')

# E a sessao nao ficou aberta: /solicitar/ nao entrega o formulario.
r2 = c.get(f'/solicitacoes/{clinica.slug}/solicitar/')
print(f'  /solicitar/ depois do bloqueio    -> HTTP {r2.status_code} '
      f'(302 para a identificacao esperado)')
if r2.status_code == 200:
    falhas.append('o formulario abriu por link direto depois do bloqueio')

print('=== 7. sessao aberta antes nao vale depois do aperto ===')
com_consulta(100)                      # 100 dias
Membership.objects.filter(id=medico.id).update(patient_portal_max_months=12)
c2 = Client()
r = c2.post(f'/solicitacoes/{clinica.slug}/', dados)
print(f'  com janela de 12 meses, identificacao -> HTTP {r.status_code} (302 esperado)')
if r.status_code != 302:
    falhas.append('a identificacao barrou quem estava dentro da janela')

# O medico aperta para 3 meses com a sessao ja aberta.
Membership.objects.filter(id=medico.id).update(patient_portal_max_months=3)
r = c2.get(f'/solicitacoes/{clinica.slug}/solicitar/')
print(f'  medico apertou para 3; GET /solicitar/ -> HTTP {r.status_code} (403 esperado)')
if r.status_code != 403:
    falhas.append('a sessao aberta antes do aperto continuou valendo')

# E o POST tambem e recusado, nao so o GET.
c3 = Client()
Membership.objects.filter(id=medico.id).update(patient_portal_max_months=12)
c3.post(f'/solicitacoes/{clinica.slug}/', dados)
Membership.objects.filter(id=medico.id).update(patient_portal_max_months=3)
r = c3.post(f'/solicitacoes/{clinica.slug}/solicitar/', {
    'kind': 'prescription_simple', 'requester': 'self',
    'medications': 'Qualquer coisa',
})
print(f'  POST de envio depois do aperto        -> HTTP {r.status_code} (403 esperado)')
if r.status_code != 403:
    falhas.append('o envio passou com a janela ja fechada')

print('=== 8. quem consultou dentro do prazo segue normalmente ===')
com_consulta(10)
Membership.objects.filter(id=medico.id).update(patient_portal_max_months=3)
c4 = Client()
r = c4.post(f'/solicitacoes/{clinica.slug}/', dados)
print(f'  identificacao -> HTTP {r.status_code} (302 esperado)')
r = c4.get(f'/solicitacoes/{clinica.slug}/solicitar/')
print(f'  formulario    -> HTTP {r.status_code} (200 esperado)')
if r.status_code != 200:
    falhas.append('quem consultou dentro do prazo nao chegou ao formulario')

print('=== 9. um medico nao mexe no prazo de outro ===')
outro = Membership.objects.filter(
    tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).exclude(id=medico.id).first()
if outro is None:
    print('  (so ha um medico nesta clinica; secao pulada)')
else:
    antes_outro = outro.patient_portal_max_months
    usuario = User.objects.get(id=medico.user_id)
    app = Client()
    app.force_login(usuario)
    sessao = app.session
    sessao['tenant_id'] = str(clinica.id)
    sessao.save()
    # Posta o id do outro vinculo junto, tentando redirecionar a gravacao.
    app.post('/app/documents/solicitacoes/', {
        'meses': '18', 'membership_id': str(outro.id), 'membership': str(outro.id),
    })
    outro.refresh_from_db()
    medico.refresh_from_db()
    print(f'  prazo do outro medico: {antes_outro} -> {outro.patient_portal_max_months} '
          f'(inalterado esperado)')
    print(f'  prazo de quem postou:  -> {medico.patient_portal_max_months} (18 esperado)')
    if outro.patient_portal_max_months != antes_outro:
        falhas.append('um medico alterou o prazo de outro pelo formulario')
    if medico.patient_portal_max_months != 18:
        falhas.append('o medico nao conseguiu alterar o proprio prazo')
    # Valor fora da lista e recusado.
    r = app.post('/app/documents/solicitacoes/', {'meses': '7'})
    print(f'  valor fora da lista (7 meses) -> HTTP {r.status_code} (404 esperado)')
    if r.status_code != 404:
        falhas.append('a tela aceitou um prazo fora das opcoes')

restaurar()

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o portal so aceita pedido de quem consultou dentro do prazo de quem atende.')
