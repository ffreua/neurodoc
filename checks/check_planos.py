"""Os limites do plano valem, e valem nos seis lugares?

Tenta quebrar. As perguntas sao:

- override vence o plano? nulo cai no plano? `custom` e mesmo ilimitado?
- zero e um limite de verdade, ou e tratado como "nao configurado"?
- no limite, o cadastro completo **e** o pre-cadastro da agenda recusam?
- arquivar libera vaga, e desarquivar volta a ocupar?
- clinica acima do teto (rebaixamento) perde alguma coisa?
- os quatro caminhos do papel medico respeitam o limite?
- a emissao de convite de medico e recusada no limite?
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from patients.models import Patient, PatientStatus
from tenancy import limits
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.plans import PLANS, PlanCode

failures = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
plano_original = (tenant_a.plan, tenant_a.patient_limit_override, tenant_a.doctor_limit_override)


def restaurar():
    tenant_a.plan, tenant_a.patient_limit_override, tenant_a.doctor_limit_override = plano_original
    tenant_a.save(update_fields=['plan', 'patient_limit_override', 'doctor_limit_override'])


def com_limite(pacientes=None, medicos=None, plano=None):
    tenant_a.plan = plano or tenant_a.plan
    tenant_a.patient_limit_override = pacientes
    tenant_a.doctor_limit_override = medicos
    tenant_a.save(update_fields=['plan', 'patient_limit_override', 'doctor_limit_override'])
    tenant_a.refresh_from_db()


def entrar(email, tenant=None):
    tenant = tenant or tenant_a
    user = User.objects.get(email=email)
    membership = Membership.objects.get(user=user, tenant=tenant)
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


print('=== 1. o catalogo confere com a especificacao ===')
esperado = {
    PlanCode.FREE: (50, 1),
    PlanCode.BASIC: (3500, 2),
    PlanCode.COMPLETE: (12000, 5),
    PlanCode.CUSTOM: (None, None),
}
for code, (pac, med) in esperado.items():
    real = (PLANS[code]['max_patients'], PLANS[code]['max_doctors'])
    print(f'  {PLANS[code]["label"]:14} pacientes={real[0]} medicos={real[1]} ok={real == (pac, med)}')
    if real != (pac, med):
        failures.append(f'{code}: catalogo diz {real}, especificacao diz {(pac, med)}')

print('=== 2. override vence o plano; nulo cai no plano ===')
com_limite(plano=PlanCode.FREE)
print(f'  free sem override           -> {limits.patient_limit(tenant_a)} (50 esperado)')
if limits.patient_limit(tenant_a) != 50:
    failures.append('nulo nao caiu no limite do plano')
com_limite(pacientes=1200, plano=PlanCode.BASIC)
print(f'  basic com override 1200     -> {limits.patient_limit(tenant_a)} (1200 esperado)')
if limits.patient_limit(tenant_a) != 1200:
    failures.append('override nao venceu o plano')
com_limite(plano=PlanCode.CUSTOM)
ilimitado = limits.patient_limit(tenant_a) is None and limits.doctor_limit(tenant_a) is None
print(f'  custom sem override         -> ilimitado={ilimitado}')
if not ilimitado:
    failures.append('custom sem override nao ficou ilimitado')

print('=== 3. zero e um limite de verdade, nao "nao configurado" ===')
com_limite(pacientes=0, plano=PlanCode.COMPLETE)
zero_vale = limits.patient_limit(tenant_a) == 0 and limits.patient_status(tenant_a).blocked
print(f'  override 0 -> limite={limits.patient_limit(tenant_a)} bloqueado={limits.patient_status(tenant_a).blocked}')
if not zero_vale:
    failures.append('override 0 foi tratado como ausente e devolveu o limite do plano')

print('=== 4. o aviso comeca em 80%, e nao antes ===')
ativos = Patient.objects.filter(tenant=tenant_a, status=PatientStatus.ACTIVE).count()
print(f'  pacientes ativos na clinica A: {ativos}')

# A fronteira e testada com numeros sinteticos, e nao mexendo no limite da
# clinica. Com poucos pacientes ativos nao existe limite inteiro que caia
# entre 80% e 100%: com 3 pacientes, o limite teria de estar em (3, 3.75] --
# e 4 da 75%. O roteiro acusava um defeito que era aritmetica dele.
# A fronteira e `>= 80%`: 79% nao avisa, 80% avisa. O caso de 79 estava
# escrito como `True` na primeira versao deste roteiro -- e o roteiro
# acusava o produto por acertar.
for uso, limite, espera in [(79, 100, False), (80, 100, True), (95, 100, True),
                            (75, 100, False), (3, 4, False), (100, 100, False)]:
    st = limits.LimitStatus('patients', uso, limite, 'Teste')
    print(f'  uso={uso:3}/{limite:3} = {st.percent:3}%  aviso={st.warning}  bloqueado={st.blocked}')
    if st.warning != espera:
        failures.append(f'{uso}/{limite} ({st.percent}%): aviso={st.warning}, esperado {espera}')
# Cheio nao e aviso: e bloqueio.
cheio = limits.LimitStatus('patients', 100, 100, 'Teste')
if cheio.warning or not cheio.blocked:
    failures.append('no limite exato, o estado deveria ser bloqueado e nao aviso')

# E na clinica de verdade: com o dobro do uso, nao avisa.
com_limite(pacientes=max(ativos * 2, 2), plano=PlanCode.COMPLETE)
st = limits.patient_status(tenant_a)
print(f'  clinica real: {st.usage}/{st.limit} = {st.percent}% aviso={st.warning}')
if st.warning:
    failures.append('avisou com a clinica na metade da cota')

print('=== 5. no limite, as DUAS portas recusam ===')
com_limite(pacientes=ativos, plano=PlanCode.COMPLETE)
secretaria = entrar('secretary-a@demo.neurodoc.local')

r = secretaria.get('/app/patients/new/')
r = secretaria.post('/app/patients/new/', {
    'full_name': 'Teste Limite Plano', 'cpf': '93541134780', 'birth_date': '1990-01-01',
    'sex_at_registration': 'female', 'country': 'BR', 'payment_category': 'private',
    'referral_source': 'not_informed', 'marital_status': 'not_informed',
})
corpo = r.content.decode()
criado = Patient.objects.filter(tenant=tenant_a, full_name='Teste Limite Plano').exists()
print(f'  cadastro completo   -> {r.status_code}  paciente criado={criado}')
print(f'    mensagem nomeia plano e numeros={"Completo" in corpo and str(ativos) in corpo}')
if r.status_code != 409 or criado:
    failures.append(f'o cadastro completo passou do limite (status {r.status_code}, criado={criado})')

from tenancy.context import AccessContext
from tenancy.limits import PlanLimitReached
from scheduling.services import quick_register_patient
import uuid as _uuid

ctx = AccessContext(
    user_id=User.objects.get(email='secretary-a@demo.neurodoc.local').id,
    tenant_id=tenant_a.id,
    membership_id=Membership.objects.get(user__email='secretary-a@demo.neurodoc.local', tenant=tenant_a).id,
    permissions=frozenset(), request_id=_uuid.uuid4(),
)
try:
    quick_register_patient(ctx, 'Teste Pre Cadastro Limite', '11999990000')
    print('  pre-cadastro agenda -> PASSOU (nao deveria)')
    failures.append('o pre-cadastro da agenda ignorou o limite do plano')
except PlanLimitReached as exc:
    print(f'  pre-cadastro agenda -> recusado: {str(exc)[:60]}...')

print('=== 6. arquivar libera vaga; desarquivar volta a ocupar ===')
alvo = Patient.objects.filter(tenant=tenant_a, status=PatientStatus.ACTIVE).order_by('-created_at').first()
antes = limits.patient_usage(tenant_a)
alvo.status = PatientStatus.ARCHIVED
alvo.save(update_fields=['status'])
depois = limits.patient_usage(tenant_a)
print(f'  uso {antes} -> {depois} ao arquivar   liberou={depois == antes - 1}')
print(f'  bloqueado agora={limits.patient_status(tenant_a).blocked} (False esperado)')
if depois != antes - 1 or limits.patient_status(tenant_a).blocked:
    failures.append('arquivar nao liberou vaga')
alvo.status = PatientStatus.ACTIVE
alvo.save(update_fields=['status'])
print(f'  uso volta a {limits.patient_usage(tenant_a)} ao desarquivar')
if limits.patient_usage(tenant_a) != antes:
    failures.append('desarquivar nao voltou a ocupar vaga')

print('=== 7. rebaixamento congela: nada some ===')
com_limite(pacientes=1, plano=PlanCode.FREE)
st = limits.patient_status(tenant_a)
acessiveis = Patient.objects.filter(tenant=tenant_a).count()
medico = entrar('doctor-a@demo.neurodoc.local')
r_lista = medico.get('/app/patients/')
r_ficha = medico.get(f'/app/patients/{alvo.id}/')
print(f'  limite=1 uso={st.usage} bloqueado={st.blocked}')
print(f'  pacientes no banco={acessiveis}  lista={r_lista.status_code}  ficha={r_ficha.status_code}')
if r_lista.status_code != 200 or r_ficha.status_code != 200:
    failures.append('rebaixar o plano tirou acesso a paciente ja cadastrado')
if Patient.objects.filter(tenant=tenant_a).count() != acessiveis:
    failures.append('rebaixar o plano apagou paciente')
print(f'  aviso de bloqueio na lista={"Limite do plano" in r_lista.content.decode()}')

print('=== 8. papel medico: os quatro caminhos ===')
com_limite(medicos=limits.doctor_usage(tenant_a), plano=PlanCode.COMPLETE)
usados = limits.doctor_usage(tenant_a)
print(f'  medicos ativos={usados}, limite={limits.doctor_limit(tenant_a)}')

dono = entrar('doctor-a@demo.neurodoc.local')
m_secretaria = Membership.objects.get(user__email='secretary-a@demo.neurodoc.local', tenant=tenant_a)
r = dono.post(f'/app/org/equipe/{m_secretaria.id}/papeis/', {'roles': ['secretary', 'doctor']}, follow=True)
m_secretaria.refresh_from_db()
virou = Role.DOCTOR in (m_secretaria.roles or [])
print(f'  (a) conceder papel   -> virou medico={virou} (False esperado)')
if virou:
    failures.append('conceder papel medico passou do limite')

r = dono.post('/app/org/equipe/', {'email': 'novo-medico@example.invalid', 'roles': ['doctor']})
recusou = b'limite' in r.content.lower() or b'permite at' in r.content.lower()
print(f'  (b) emitir convite   -> recusado={recusou}')
if not recusou:
    failures.append('a emissao de convite de medico ignorou o limite')

from tenancy.services import _assert_doctor_vacancy
from tenancy.models import Invitation, InvitationPurpose


class _ConviteFalso:
    role_grants = [Role.DOCTOR]
    target_tenant = tenant_a


try:
    _assert_doctor_vacancy(_ConviteFalso())
    print('  (c/d) aceite         -> PASSOU (nao deveria)')
    failures.append('o aceite de convite ignorou o limite de medicos')
except PlanLimitReached as exc:
    print(f'  (c/d) aceite         -> recusado: {str(exc)[:50]}...')

print('=== 9. ilimitado nao bloqueia nada ===')
com_limite(plano=PlanCode.CUSTOM)
st_p, st_m = limits.patient_status(tenant_a), limits.doctor_status(tenant_a)
print(f'  pacientes: ilimitado={st_p.unlimited} bloqueado={st_p.blocked} aviso={st_p.warning} {st_p.percent}%')
print(f'  medicos:   ilimitado={st_m.unlimited} bloqueado={st_m.blocked}')
if st_p.blocked or st_p.warning or st_m.blocked:
    failures.append('plano ilimitado bloqueou ou avisou')

r = secretaria.post('/app/patients/new/', {
    'full_name': 'Teste Ilimitado Plano', 'cpf': '93541134780', 'birth_date': '1990-01-01',
    'sex_at_registration': 'female', 'country': 'BR', 'payment_category': 'private',
    'referral_source': 'not_informed', 'marital_status': 'not_informed',
}, follow=True)
criado = Patient.objects.filter(tenant=tenant_a, full_name='Teste Ilimitado Plano').first()
print(f'  cadastro em plano ilimitado -> criado={criado is not None}')
if criado is None:
    failures.append('plano ilimitado recusou um cadastro')
else:
    Patient.objects.filter(id=criado.id).delete()

print()
print('=== 7. o card do consumo, no painel de indicadores ===')
#
# Renderizado isoladamente, com `LimitStatus` montado a mao: as faixas
# precisam ser conferidas nos valores de borda (79, 80, 99, 100), e nao da
# para produzir 80 % exatos mexendo no limite de uma clinica que tem tres
# pacientes. A regra em si (`warning` a partir de 80 %, `blocked` no
# limite) e a mesma ja exercitada acima nas seis portas -- aqui a pergunta
# e se a TELA mostra o que a regra diz.
from django.template.loader import render_to_string

from tenancy.limits import LimitStatus


def _cartao(usage, limit):
    return render_to_string('reporting/_card_plano.html', {
        'plano': LimitStatus('patients', usage, limit, 'Completo'),
        'email_suporte': 'suporte@exemplo.invalid',
        'tenant': tenant_a,
    })


def _faixa(html):
    if 'bg-danger' in html:
        return 'vermelho'
    if 'bg-warning' in html:
        return 'ambar'
    if 'bg-success' in html:
        return 'verde'
    return 'sem cor'


for usage, limite, esperada, espera_botao in [
    (10, 100, 'verde', False),
    (79, 100, 'verde', False),      # 79 % ainda e verde
    (80, 100, 'ambar', True),       # o limiar exato
    (99, 100, 'ambar', True),
    (100, 100, 'vermelho', True),   # sem vaga
    (120, 100, 'vermelho', True),   # rebaixamento: acima do teto, e nada foi apagado
]:
    html = _cartao(usage, limite)
    faixa = _faixa(html)
    tem_botao = 'Falar com o suporte' in html
    ok = faixa == esperada and tem_botao == espera_botao
    print(f'  {"ok  " if ok else "FALHA"} {usage}/{limite} -> {faixa:<9} botao_de_upgrade={tem_botao}')
    if not ok:
        failures.append(f'o card mostrou {faixa} com botao={tem_botao} em {usage}/{limite}')

# O numero tem de estar escrito, e nao so pintado: cor sozinha nao informa
# quem nao a distingue, e barra sozinha nao informa quem usa leitor de tela.
html = _cartao(85, 100)
for trecho in ['85', '100', '85%', 'aria-valuenow="85"']:
    if trecho not in html:
        failures.append(f'o card nao mostra {trecho!r} por escrito')
print(f'  {"ok  " if all(t in html for t in ["85", "100", "85%"]) else "FALHA"} '
      'o numero aparece escrito, alem da barra')

# Plano ilimitado nao tem barra nem alarme: `None` e ilimitado em todo o
# `tenancy/plans.py`, e uma barra cheia ali diria o contrario do que e.
html = _cartao(500, None)
sem_barra = 'nd-plano-barra' not in html
sem_botao = 'Falar com o suporte' not in html
print(f'  {"ok  " if sem_barra and sem_botao else "FALHA"} ilimitado: sem barra e sem alarme')
if not (sem_barra and sem_botao):
    failures.append('o card desenhou barra ou alarme para plano ilimitado')

restaurar()
print(f'--- plano da clinica A restaurado: {tenant_a.plan}')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o limite do plano vale nas seis portas, e nao apaga o que ja existe.')
