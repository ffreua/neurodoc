"""O portal barra consulta antiga quando mandam barrar -- e so entao?

Tenta quebrar. As perguntas sao:

- o limiar e o da norma (180 dias), ou um numero nosso?
- quem consultou ontem passa, e quem consultou ha 200 dias nao?
- a escolha do medico vence a da clinica, e nulo herda?
- desligado, o portal aceita mesmo quem nao consulta ha anos?
- da para furar indo direto em /solicitar/, ou com sessao aberta antes?
- a tela cita as duas normas com a redacao que consta nelas?
- um medico consegue mudar a escolha de outro?
"""
import atexit
import datetime
import re

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter
from documents.portal_retorno import bloqueio
from patients.models import Patient, PatientStatus
from tenancy.models import (
    PORTAL_RECENT_VISIT_DAYS, ClinicProfile, Membership, MembershipStatus, Role, Tenant,
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

_original = (
    perfil.patient_portal_enabled, perfil.patient_portal_requires_recent_visit,
    medico.patient_portal_requires_recent_visit,
)

# Paciente proprio, e nao o da demonstracao: mexer na data das consultas
# semeadas ja quebrou o `check_g10` uma vez, num roteiro que nao tem nada
# a ver com o portal.
_paciente = Patient.objects.create(
    tenant=clinica, full_name='Paciente Do Roteiro De Retorno',
    cpf='15350946056', birth_date=datetime.date(1985, 7, 20),
    status=PatientStatus.ACTIVE,
)


def restaurar():
    perfil.patient_portal_enabled = _original[0]
    perfil.patient_portal_requires_recent_visit = _original[1]
    perfil.save(update_fields=[
        'patient_portal_enabled', 'patient_portal_requires_recent_visit',
    ])
    Membership.objects.filter(id=medico.id).update(
        patient_portal_requires_recent_visit=_original[2],
    )
    Encounter.objects.filter(tenant=clinica, patient=_paciente).delete()
    Patient.objects.filter(id=_paciente.id).delete()


atexit.register(restaurar)


def com_consulta(dias_atras):
    """Um unico atendimento, datado, para o paciente deste roteiro."""
    Encounter.objects.filter(tenant=clinica, patient=_paciente).delete()
    return Encounter.objects.create(
        tenant=clinica, patient=_paciente, physician_membership=medico,
        occurred_at=timezone.now() - datetime.timedelta(days=dias_atras),
    )


def zera_balde():
    """O limite de tentativas do portal e por IP, e aqui todo cliente e
    127.0.0.1.

    Sao oito tentativas em quinze minutos (`LOOKUP_MAX_ATTEMPTS`), e este
    roteiro faz perto disso. Sem zerar, rodar a bateria duas vezes dentro
    da janela fazia a segunda falhar com 429 -- uma falha que nao e do
    produto, e que manda procurar defeito no lugar errado.
    """
    from django.core.cache import cache

    cache.delete('portal:lookup:127.0.0.1')
    cache.delete('portal:submit:127.0.0.1')


def escolha(clinica_barra, medico_barra):
    perfil.patient_portal_requires_recent_visit = clinica_barra
    perfil.save(update_fields=['patient_portal_requires_recent_visit'])
    Membership.objects.filter(id=medico.id).update(
        patient_portal_requires_recent_visit=medico_barra,
    )
    medico.refresh_from_db()


print('=== 1. o limiar e o da norma ===')
print(f'  PORTAL_RECENT_VISIT_DAYS = {PORTAL_RECENT_VISIT_DAYS}')
if PORTAL_RECENT_VISIT_DAYS != 180:
    falhas.append(
        f'o limiar deixou de ser os 180 dias da Resolucao CFM 2.314/2022: '
        f'{PORTAL_RECENT_VISIT_DAYS}'
    )
# E nao existe mais prazo configuravel: um campo de meses de volta faria a
# tela citar 180 dias e aplicar outro numero.
if any(hasattr(m, 'patient_portal_max_months') for m in (perfil, medico)):
    falhas.append('o prazo configuravel em meses voltou a existir')

print('=== 2. a fronteira dos 180 dias ===')
escolha(True, None)
for dias, deve_bloquear in [(1, False), (179, False), (180, False), (181, True), (400, True)]:
    com_consulta(dias)
    bloqueou = bloqueio(perfil, _paciente) is not None
    print(f'  ultima consulta ha {dias:3} dia(s) -> '
          f'{"bloqueado" if bloqueou else "liberado"}')
    if bloqueou != deve_bloquear:
        falhas.append(
            f'consulta ha {dias} dias: {"bloqueou" if bloqueou else "liberou"}, '
            f'e nao deveria'
        )

print('=== 3. a escolha do medico vence a da clinica; nulo herda ===')
com_consulta(400)
casos = [
    (True, None, True, 'clinica barra, medico segue a clinica'),
    (False, None, False, 'clinica nao barra, medico segue a clinica'),
    (False, True, True, 'clinica nao barra, medico barra'),
    (True, False, False, 'clinica barra, medico libera'),
]
for clinica_barra, medico_barra, esperado, rotulo in casos:
    escolha(clinica_barra, medico_barra)
    obtido = bloqueio(perfil, _paciente) is not None
    print(f'  {rotulo:44} -> {"bloqueado" if obtido else "liberado"}')
    if obtido != esperado:
        falhas.append(f'{rotulo}: esperava {"bloqueio" if esperado else "passagem"}')

print('=== 4. desligado, consulta antiga passa ===')
escolha(False, None)
com_consulta(3000)
print(f'  ultima consulta ha 3000 dias, sem barrar -> '
      f'{"bloqueado" if bloqueio(perfil, _paciente) else "liberado"}')
if bloqueio(perfil, _paciente) is not None:
    falhas.append('com a barreira desligada, consulta antiga ainda foi bloqueada')
# Nem quem nunca consultou.
Encounter.objects.filter(tenant=clinica, patient=_paciente).delete()
print(f'  sem consulta nenhuma, sem barrar         -> '
      f'{"bloqueado" if bloqueio(perfil, _paciente) else "liberado"}')
if bloqueio(perfil, _paciente) is not None:
    falhas.append('com a barreira desligada, quem nunca consultou foi bloqueado')

print('=== 5. ligado, quem nunca consultou e barrado -- e a tela diz isso ===')
escolha(True, None)
b = bloqueio(perfil, _paciente)
print(f'  sem consulta nenhuma -> {"bloqueado" if b else "liberado"}  '
      f'nunca_consultou={getattr(b, "nunca_consultou", None)}')
if b is None or not b.nunca_consultou:
    falhas.append('quem nunca consultou nao foi barrado como tal')

zera_balde()
perfil.patient_portal_enabled = True
perfil.save(update_fields=['patient_portal_enabled'])
dados = {
    'cpf': _paciente.cpf,
    'birth_date': _paciente.birth_date.isoformat(),
    'privacy_ack': '1',
}
r = Client().post(f'/solicitacoes/{clinica.slug}/', dados)
corpo = r.content.decode(errors='replace')
print(f'  identificacao -> HTTP {r.status_code}  '
      f'fala em "ainda nao"={"Ainda não temos" in corpo}')
if r.status_code != 403 or 'Ainda não temos' not in corpo:
    falhas.append('a tela nao distinguiu "nunca consultou" de "consulta antiga"')

zera_balde()
print('=== 6. a tela cita as duas normas como elas sao ===')
com_consulta(400)
c = Client()
r = c.post(f'/solicitacoes/{clinica.slug}/', dados)
corpo = r.content.decode(errors='replace')
achatado = ' '.join(corpo.split())
print(f'  identificacao com consulta antiga -> HTTP {r.status_code}')
if r.status_code != 403:
    falhas.append(f'a identificacao respondeu {r.status_code} para consulta antiga')

# Cada trecho e literal da norma; conferidos na fonte antes de entrar.
trechos = [
    ('CEM, resolucao', 'Resolução CFM nº 2.217/2018'),
    ('CEM, artigo', 'art. 37'),
    ('CEM, conduta vedada', 'sem exame direto do paciente'),
    ('CEM, excecao completa', 'urgência ou emergência e impossibilidade comprovada'),
    ('CEM, paragrafo unico', 'parágrafo único'),
    ('2.314, resolucao', 'Resolução CFM nº 2.314/2022'),
    ('2.314, dispositivo', 'art. 6º, § 2º'),
    ('2.314, prazo literal', 'não superiores a 180 dias'),
]
for rotulo, trecho in trechos:
    achou = trecho in achatado
    print(f'  {rotulo:24} {"ok" if achou else "AUSENTE"}')
    if not achou:
        falhas.append(f'a tela de bloqueio nao traz: {rotulo}')

# E nao inventa a excecao que o texto do CFM nao tem.
if re.search(r'comunicad[ao]s? ao CRM', achatado):
    falhas.append('a tela atribui ao art. 37 uma comunicacao ao CRM que ele nao exige')
if re.search(r'CFM[^.]{0,80}(exige|determina|obriga)[^.]{0,40}\d+\s*meses', achatado):
    falhas.append('a tela atribui ao CFM um prazo em meses que ele nao fixa')

zera_balde()
print('=== 7. as tres portas do portal ===')
r2 = c.get(f'/solicitacoes/{clinica.slug}/solicitar/')
print(f'  /solicitar/ depois do bloqueio -> HTTP {r2.status_code} (302 esperado)')
if r2.status_code == 200:
    falhas.append('o formulario abriu por link direto depois do bloqueio')

# Sessao aberta com a barreira desligada nao vale depois de ela ser ligada.
escolha(False, None)
c2 = Client()
r = c2.post(f'/solicitacoes/{clinica.slug}/', dados)
print(f'  desligado, identificacao       -> HTTP {r.status_code} (302 esperado)')
if r.status_code != 302:
    falhas.append('com a barreira desligada, a identificacao foi barrada')
escolha(True, None)
r = c2.get(f'/solicitacoes/{clinica.slug}/solicitar/')
print(f'  ligou depois; GET /solicitar/  -> HTTP {r.status_code} (403 esperado)')
if r.status_code != 403:
    falhas.append('a sessao aberta antes de ligar a barreira continuou valendo')

escolha(False, None)
zera_balde()
c3 = Client()
c3.post(f'/solicitacoes/{clinica.slug}/', dados)
escolha(True, None)
r = c3.post(f'/solicitacoes/{clinica.slug}/solicitar/', {
    'kind': 'prescription_simple', 'requester': 'self', 'medications': 'Qualquer coisa',
})
print(f'  ligou depois; POST de envio    -> HTTP {r.status_code} (403 esperado)')
if r.status_code != 403:
    falhas.append('o envio passou com a barreira ja ligada')

zera_balde()
print('=== 8. quem consultou dentro do prazo segue normalmente ===')
com_consulta(10)
escolha(True, None)
c4 = Client()
r = c4.post(f'/solicitacoes/{clinica.slug}/', dados)
print(f'  identificacao -> HTTP {r.status_code} (302 esperado)')
r = c4.get(f'/solicitacoes/{clinica.slug}/solicitar/')
print(f'  formulario    -> HTTP {r.status_code} (200 esperado)')
if r.status_code != 200:
    falhas.append('quem consultou dentro do prazo nao chegou ao formulario')

print('=== 9. um medico nao mexe na escolha de outro ===')
outro = Membership.objects.filter(
    tenant=clinica, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).exclude(id=medico.id).first()
if outro is None:
    print('  (so ha um medico nesta clinica; secao pulada)')
else:
    antes_outro = outro.patient_portal_requires_recent_visit
    app = Client()
    app.force_login(User.objects.get(id=medico.user_id))
    sessao = app.session
    sessao['tenant_id'] = str(clinica.id)
    sessao.save()
    app.post('/app/documents/solicitacoes/', {
        'barrar': 'nao', 'membership_id': str(outro.id), 'membership': str(outro.id),
    })
    outro.refresh_from_db()
    medico.refresh_from_db()
    print(f'  escolha do outro medico: {antes_outro} -> '
          f'{outro.patient_portal_requires_recent_visit} (inalterada esperada)')
    print(f'  escolha de quem postou:  -> {medico.patient_portal_requires_recent_visit} '
          f'(False esperado)')
    if outro.patient_portal_requires_recent_visit != antes_outro:
        falhas.append('um medico alterou a escolha de outro pelo formulario')
    if medico.patient_portal_requires_recent_visit is not False:
        falhas.append('o medico nao conseguiu alterar a propria escolha')
    # "Seguir a clinica" e um terceiro estado, e volta a ser nulo.
    app.post('/app/documents/solicitacoes/', {'barrar': 'clinica'})
    medico.refresh_from_db()
    print(f'  voltando a seguir a clinica -> {medico.patient_portal_requires_recent_visit} '
          f'(None esperado)')
    if medico.patient_portal_requires_recent_visit is not None:
        falhas.append('"seguir a clinica" nao devolveu o vinculo ao estado nulo')
    r = app.post('/app/documents/solicitacoes/', {'barrar': 'talvez'})
    print(f'  valor fora da lista -> HTTP {r.status_code} (404 esperado)')
    if r.status_code != 404:
        falhas.append('a tela aceitou uma escolha que nao existe')

restaurar()

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o portal barra consulta com mais de 180 dias quando mandam barrar, e so entao.')
