"""O convite carrega o plano contratado, e o console emite e troca?

Tenta quebrar. As perguntas sao:

- a organizacao criada nasce no plano do convite, ou no `free` fixo de antes?
- override do convite chega a organizacao?
- convite de colaborador consegue mexer em plano? (nao deve)
- o console emite, mostra o token uma vez so, e revoga?
- revogar convite ja usado desfaz a clinica? (nao deve, e deve recusar)
- trocar plano sem motivo passa?
- campo de limite em branco vira zero? (nao deve: em branco e "usa o plano")
- superadministrador sem MFA alcanca as telas novas?
"""
import re

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from tenancy import limits
from tenancy.invitations import issue_invitation
from tenancy.models import Invitation, InvitationPurpose, Tenant
from tenancy.plans import PlanCode
from tenancy.services import accept_platform_invitation

falhas = []
CNPJ_TESTE = '20804182000160'    # Freua Servicos Medicos Especializados Ltda
CNPJ_OVERRIDE = '11444777000323'  # sintetico, digitos verificadores conferidos
EMAIL_TESTE = 'teste-convite-plano@example.invalid'

def apagar_organizacoes(cnpjs, emails):
    """Derruba vinculo e trilha antes da organizacao.

    Duas chaves `PROTECT` apontam para `Tenant`: `Membership.tenant` e
    `AuditEvent.tenant`. Apagar o tenant direto levanta `ProtectedError`, e
    o roteiro morreria na limpeza depois de ter passado -- que se le como
    falha do que ele verifica.

    Que a trilha proteja a organizacao e o desenho certo: auditoria que
    some junto com o objeto auditado nao e auditoria. Apagar evento aqui so
    se justifica porque sao os eventos que este proprio roteiro acabou de
    gerar, em organizacoes sinteticas que ele mesmo criou -- **nunca** faca
    isto fora de um banco de demonstracao.
    """
    from audit.models import AuditEvent
    from tenancy.models import Membership

    Membership.objects.filter(tenant__cnpj__in=cnpjs).delete()
    AuditEvent.objects.filter(tenant__cnpj__in=cnpjs).delete()
    Tenant.objects.filter(cnpj__in=cnpjs).delete()
    User.objects.filter(email__in=emails).delete()


# limpeza de rodadas anteriores
apagar_organizacoes([CNPJ_TESTE, CNPJ_OVERRIDE], [EMAIL_TESTE, 'teste-override@example.invalid'])

def superadmin_descartavel():
    """Um superadministrador **do roteiro**, nunca a conta de uma pessoa.

    `force_login` grava `last_login`, e `last_login` entra no hash de
    `default_token_generator`: logar numa conta invalida o link de
    definicao de senha pendente dela. Pegar "o primeiro superusuario"
    funcionava enquanto havia contas de teste no banco; num banco limpo,
    a unica conta com `is_superuser` e a de quem opera o sistema -- e o
    roteiro passava a derrubar o link dessa pessoa.
    """
    from accounts.models import User as _User
    from django.utils import timezone as _tz

    conta, criada = _User.objects.get_or_create(
        email='check-superadmin@example.invalid',
        defaults={'is_active': True, 'is_staff': True, 'is_superuser': True},
    )
    if criada:
        conta.set_password('CheckS3nha!2026')
    conta.is_staff = True
    conta.is_superuser = True
    conta.is_active = True
    conta.email_verified_at = conta.email_verified_at or _tz.now()
    conta.save()
    return conta


superadmin = superadmin_descartavel()

print('=== 1. o convite carrega o plano, e a organizacao nasce nele ===')
convite, token = issue_invitation(
    InvitationPurpose.PLATFORM, issued_by=superadmin,
    plan=PlanCode.CUSTOM, plan_note='Consultorio do responsavel pelo produto',
)
print(f'  convite emitido: plano={convite.plan} nota={convite.plan_note!r}')
user, tenant, membership = accept_platform_invitation(
    token, EMAIL_TESTE, 'SenhaDeTeste!2026',
    'Freua Servicos Medicos Especializados Ltda', CNPJ_TESTE,
)
print(f'  organizacao criada: plano={tenant.plan} nota={tenant.plan_note!r}')
print(f'  limites: pacientes={limits.patient_limit(tenant)} medicos={limits.doctor_limit(tenant)}')
if tenant.plan != PlanCode.CUSTOM:
    falhas.append(f'a organizacao nasceu em {tenant.plan}, nao no plano do convite')
if limits.patient_limit(tenant) is not None or limits.doctor_limit(tenant) is not None:
    falhas.append('custom sem override nao ficou ilimitado na organizacao criada')
if tenant.plan_note != convite.plan_note:
    falhas.append('a nota do convite nao chegou a organizacao')

print('=== 2. override do convite chega a organizacao ===')
convite2, token2 = issue_invitation(
    InvitationPurpose.PLATFORM, issued_by=superadmin,
    plan=PlanCode.BASIC, patient_limit_override=1200, doctor_limit_override=3,
)
_, tenant2, _ = accept_platform_invitation(
    token2, 'teste-override@example.invalid', 'SenhaDeTeste!2026',
    'Clinica Override Teste Ltda', CNPJ_OVERRIDE,
)
print(f'  plano={tenant2.plan} pacientes={limits.patient_limit(tenant2)} medicos={limits.doctor_limit(tenant2)}')
if (limits.patient_limit(tenant2), limits.doctor_limit(tenant2)) != (1200, 3):
    falhas.append('o override do convite nao chegou a organizacao')

print('=== 3. convite de colaborador nao mexe em plano ===')
colaborador, _ = issue_invitation(
    InvitationPurpose.COLLABORATOR, issued_by=superadmin, target_tenant=tenant2,
    role_grants=['secretary'], plan=PlanCode.CUSTOM, patient_limit_override=99999,
)
print(f'  plano no convite de colaborador={colaborador.plan} override={colaborador.patient_limit_override}')
if colaborador.plan != PlanCode.FREE or colaborador.patient_limit_override is not None:
    falhas.append('convite de colaborador aceitou plano/override e poderia alterar contrato')

print('=== 4. plano desconhecido e recusado na emissao ===')
try:
    issue_invitation(InvitationPurpose.PLATFORM, issued_by=superadmin, plan='ouro')
    falhas.append('emitir convite com plano inexistente passou')
    print('  PASSOU (nao deveria)')
except ValueError as exc:
    print(f'  recusado: {exc}')

print('=== 5. o console: sem MFA nao entra ===')
sem_mfa = Client()
sem_mfa.force_login(superadmin)
for url in ['/instalacao/convites/', '/instalacao/organizacoes/']:
    r = sem_mfa.get(url)
    print(f'  {url:32} sem MFA -> {r.status_code} (404 esperado)')
    if r.status_code != 404:
        falhas.append(f'{url} abriu para superadministrador sem MFA')

print('=== 6. o console emite, mostra o token uma vez, e revoga ===')
device = TOTPDevice.objects.filter(user=superadmin, confirmed=True).first()
criou_device = False
if device is None:
    device = TOTPDevice.objects.create(user=superadmin, name='check', confirmed=True)
    criou_device = True

console = Client()
console.force_login(superadmin)
sessao = console.session
sessao['otp_device_id'] = device.persistent_id
sessao.save()

r = console.get('/instalacao/convites/')
print(f'  GET convites -> {r.status_code}')
if r.status_code != 200:
    falhas.append('a tela de convites nao abriu para superadministrador com MFA')

antes = Invitation.objects.filter(purpose=InvitationPurpose.PLATFORM).count()
r = console.post('/instalacao/convites/', {
    'plan': PlanCode.COMPLETE, 'ttl_days': '14',
    'email_binding': 'lead@example.invalid', 'plan_note': 'Venda de teste',
})
corpo = r.content.decode()
depois = Invitation.objects.filter(purpose=InvitationPurpose.PLATFORM).count()
token_na_tela = re.search(r'id="nd-token" readonly value="([^"]+)"', corpo)
print(f'  POST emitir -> {r.status_code}  convites {antes} -> {depois}')
print(f'  token aparece na resposta={token_na_tela is not None}')
if depois != antes + 1:
    falhas.append('o console nao emitiu o convite')
if token_na_tela is None:
    falhas.append('o token nao apareceu na tela de emissao')
else:
    novamente = console.get('/instalacao/convites/')
    repetiu = token_na_tela.group(1) in novamente.content.decode()
    print(f'  token reaparece ao recarregar={repetiu} (False esperado)')
    if repetiu:
        falhas.append('o token continua visivel depois de recarregar a tela')

emitido = Invitation.objects.filter(purpose=InvitationPurpose.PLATFORM).order_by('-created_at').first()
print(f'  plano gravado={emitido.plan} vinculo={emitido.email_binding}')
if emitido.plan != PlanCode.COMPLETE:
    falhas.append('o console gravou o plano errado no convite')

r = console.post(f'/instalacao/convites/{emitido.id}/revogar/', follow=True)
emitido.refresh_from_db()
print(f'  revogar -> {r.status_code}  revogado={emitido.revoked_at is not None}')
if emitido.revoked_at is None:
    falhas.append('revogar convite nao funcionou')

print('=== 7. convite ja usado nao se revoga ===')
convite.refresh_from_db()
r = console.post(f'/instalacao/convites/{convite.id}/revogar/', follow=True)
convite.refresh_from_db()
ainda_existe = Tenant.objects.filter(cnpj=CNPJ_TESTE).exists()
print(f'  revogado={convite.revoked_at is not None} (False esperado)  clinica intacta={ainda_existe}')
if convite.revoked_at is not None:
    falhas.append('um convite ja consumido foi revogado')
if not ainda_existe:
    falhas.append('revogar convite usado afetou a organizacao criada')

print('=== 8. trocar plano: exige motivo, e em branco nao vira zero ===')
r = console.post(f'/instalacao/organizacoes/{tenant2.id}/plano/', {
    'plan': PlanCode.COMPLETE, 'plan_note': '',
}, follow=True)
tenant2.refresh_from_db()
print(f'  sem motivo -> plano continua {tenant2.plan} (basic esperado)')
if tenant2.plan != PlanCode.BASIC:
    falhas.append('trocou o plano sem motivo escrito')

r = console.post(f'/instalacao/organizacoes/{tenant2.id}/plano/', {
    'plan': PlanCode.COMPLETE, 'plan_note': 'Upgrade contratado',
    'patient_limit_override': '', 'doctor_limit_override': '',
}, follow=True)
tenant2.refresh_from_db()
print(f'  com motivo -> plano={tenant2.plan} override_pacientes={tenant2.patient_limit_override}')
print(f'  limite efetivo={limits.patient_limit(tenant2)} (3000 esperado, nao 0)')
if tenant2.plan != PlanCode.COMPLETE:
    falhas.append('a troca de plano com motivo nao gravou')
if tenant2.patient_limit_override is not None:
    falhas.append('campo em branco virou um numero em vez de nulo')
if limits.patient_limit(tenant2) != 3000:
    falhas.append(f'limite efetivo saiu {limits.patient_limit(tenant2)}, esperado 3000')

print('=== 9. a troca vai para a trilha, com o de-para ===')
evento = AuditEvent.objects.filter(action='tenancy.tenant_plan_changed').order_by('-created_at').first()
if evento is None:
    falhas.append('a troca de plano nao gerou evento de auditoria')
    print('  nenhum evento')
else:
    meta = evento.integrity_metadata or {}
    tem_depara = 'from' in meta and 'to' in meta
    print(f'  evento={evento.action}  de-para presente={tem_depara}')
    print(f'    de={meta.get("from")}')
    print(f'    para={meta.get("to")}')
    if not tem_depara:
        falhas.append('o evento da troca nao registrou de/para')

print('=== 10. zero e um limite de verdade, tambem pelo console ===')
console.post(f'/instalacao/organizacoes/{tenant2.id}/plano/', {
    'plan': PlanCode.COMPLETE, 'plan_note': 'Suspensao comercial',
    'patient_limit_override': '0', 'doctor_limit_override': '',
}, follow=True)
tenant2.refresh_from_db()
print(f'  override=0 -> limite={limits.patient_limit(tenant2)} bloqueado={limits.patient_status(tenant2).blocked}')
if limits.patient_limit(tenant2) != 0 or not limits.patient_status(tenant2).blocked:
    falhas.append('zero pelo console nao virou limite de verdade')

# limpeza
apagar_organizacoes([CNPJ_TESTE, CNPJ_OVERRIDE], [EMAIL_TESTE, 'teste-override@example.invalid'])
Invitation.objects.filter(issued_by=superadmin, consumed_at__isnull=True,
                          email_binding__in=['lead@example.invalid', '']).delete()
if criou_device:
    device.delete()

print('---')
if falhas:
    for line in falhas:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o convite carrega o plano, e o console emite, revoga e troca com motivo.')
