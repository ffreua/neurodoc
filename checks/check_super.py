"""O console da instalacao, do lado de dentro.

O outro teste provou que ele recusa. Este prova que ele serve — e que o
que ele mostra nao inclui conteudo clinico, que e a decisao que governa o
recurso.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import Encounter
from patients.models import Patient

falhas = []
criados = []

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


su = superadmin_descartavel()
if su is None:
    raise SystemExit('sem superusuario para testar')

device = TOTPDevice.objects.filter(user=su, confirmed=True).first()
if device is None:
    device = TOTPDevice.objects.create(user=su, name='teste', confirmed=True)
    criados.append(device.id)

# Sessao com o segundo fator ja verificado. `force_login` sozinho nao
# marca `is_verified()`; e essa diferenca que o console exige.
client = Client()
client.force_login(su)
request = type('R', (), {'session': client.session, 'user': su})()
otp_login(request, device)
request.session.save()
client.cookies['sessionid'] = request.session.session_key

print('superusuario:', su.email, '| MFA verificada na sessao')
print()

rotas = {
    '/instalacao/': ['Organiza', 'Servi', 'Banco de dados'],
    '/instalacao/organizacoes/': ['Todas as cl'],
    '/instalacao/usuarios/': ['Contas da instala', su.email],
    '/instalacao/auditoria/': ['Trilha'],
}
for rota, esperados in rotas.items():
    r = client.get(rota)
    corpo = r.content.decode(errors='replace')
    faltando = [t for t in esperados if t not in corpo]
    print(f'  {rota:32} -> {r.status_code} {"" if not faltando else "FALTA " + str(faltando)}')
    if r.status_code != 200:
        falhas.append(f'{rota} devolveu {r.status_code} para superusuario com MFA')
    elif faltando:
        falhas.append(f'{rota} nao mostrou {faltando}')

# --- a trilha atravessa organizacoes ---
r = client.get('/instalacao/auditoria/')
corpo = r.content.decode(errors='replace')
tenants_na_trilha = set(
    AuditEvent.objects.exclude(tenant__isnull=True).values_list('tenant__slug', flat=True)[:200]
)
print()
print('  organizacoes com eventos:', len(tenants_na_trilha))
if len(tenants_na_trilha) < 2:
    print('  (a demonstracao tem eventos em menos de duas clinicas — nao da para provar aqui)')

# --- filtro por desfecho ---
r = client.get('/instalacao/auditoria/?outcome=denied')
print('  filtro outcome=denied ->', r.status_code)
if r.status_code != 200:
    falhas.append('o filtro por desfecho quebrou')

# --- busca de usuario ---
r = client.get('/instalacao/usuarios/?q=secretary')
corpo = r.content.decode(errors='replace')
print('  busca "secretary" acha ->', 'secretary-a@demo.neurodoc.local' in corpo)
if 'secretary-a@demo.neurodoc.local' not in corpo:
    falhas.append('a busca de usuarios nao encontrou uma conta existente')

# --- e o que ele NAO mostra: conteudo clinico ---
#
# A afirmacao do recurso e que auditar e saber quem fez o que, e nao ler o
# que foi escrito. Se um texto de prontuario aparecer numa destas telas, a
# afirmacao e falsa.
enc = Encounter.objects.exclude(chief_complaint='').first()
paciente = Patient.objects.first()
vazamentos = []
for rota in rotas:
    corpo = client.get(rota).content.decode(errors='replace')
    if enc is not None and enc.chief_complaint and enc.chief_complaint[:30] in corpo:
        vazamentos.append(f'{rota}: queixa principal de atendimento')
    if paciente is not None and paciente.cpf and paciente.cpf in corpo:
        vazamentos.append(f'{rota}: CPF de paciente')
    if paciente is not None and paciente.full_name and paciente.full_name in corpo:
        vazamentos.append(f'{rota}: nome de paciente')
print()
print('  conteudo clinico nas telas ->', vazamentos or 'nenhum')
if vazamentos:
    falhas.extend(f'vazamento no console: {v}' for v in vazamentos)

# --- nem segredo ---
segredos = []
for rota in rotas:
    corpo = client.get(rota).content.decode(errors='replace')
    if dj_settings.SECRET_KEY[:16] in corpo:
        segredos.append(f'{rota}: SECRET_KEY')
    if dj_settings.SECRETS_MASTER_KEY and str(dj_settings.SECRETS_MASTER_KEY)[:12] in corpo:
        segredos.append(f'{rota}: SECRETS_MASTER_KEY')
print('  segredos nas telas ->', segredos or 'nenhum')
if segredos:
    falhas.extend(f'segredo exposto: {s}' for s in segredos)

TOTPDevice.objects.filter(id__in=criados).delete()
print()
print('---')
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: o console serve a quem opera o servidor, e nao abre prontuario.')
