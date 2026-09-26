"""G3 — area administrativa: equipe, papeis, registro profissional, logotipo."""
import struct
import zlib

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import PhysicianProfile, User
from tenancy.models import ClinicProfile, Invitation, Membership, MembershipStatus, Role

TENANT = 'demo-clinica-a'
failures = []


def note(response):
    items = [str(m) for m in get_messages(response.wsgi_request)]
    return items[-1] if items else '(sem aviso)'


def client_for(email):
    user = User.objects.get(email=email)
    membership = Membership.objects.get(user=user, tenant__slug=TENANT)
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(membership.tenant_id)
    s.save()
    return c, membership


def png_bytes(width=8, height=8):
    """PNG minimo valido, montado a mao para nao depender de arquivo externo."""
    raw = b''.join(b'\x00' + b'\xff\x00\x00' * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


owner, owner_membership = client_for('doctor-a@demo.neurodoc.local')
secretary, _ = client_for('secretary-a@demo.neurodoc.local')
manager, _ = client_for('manager-a@demo.neurodoc.local')
doctor_b_membership = Membership.objects.get(
    user__email='doctor-b@demo.neurodoc.local', tenant__slug=TENANT,
)

print('=== 1. quem alcanca a area ===')
for label, c, expected in [('owner', owner, 200), ('secretaria', secretary, 404), ('gestor', manager, 404)]:
    for route in ['/app/org/equipe/', '/app/org/clinica/']:
        code = c.get(route).status_code
        print(f'  {label:11} {route:22} -> {code}')
        if code != expected:
            failures.append(f'{label} em {route}: esperava {expected}, veio {code}')

print('=== 2. alterar papeis de um vinculo ===')
target = Membership.objects.get(user__email='manager-a@demo.neurodoc.local', tenant__slug=TENANT)
original = list(target.roles)
r = owner.post(f'/app/org/equipe/{target.id}/papeis/',
               {'roles': ['manager', 'secretary']}, follow=True)
target.refresh_from_db()
print('  ->', note(r), '| papeis agora:', target.roles)
if sorted(target.roles) != ['manager', 'secretary']:
    failures.append(f'papeis nao mudaram: {target.roles}')

# sem papel nenhum tem de ser recusado
r = owner.post(f'/app/org/equipe/{target.id}/papeis/', {'roles': []}, follow=True)
target.refresh_from_db()
print('  sem papel ->', note(r), '| papeis:', target.roles)
if not target.roles:
    failures.append('vinculo ficou sem papel nenhum')

target.roles = original
target.save(update_fields=['roles'])

print('=== 3. nao se pode derrubar o proprio vinculo ===')
r = owner.post(f'/app/org/equipe/{owner_membership.id}/revoke/', {}, follow=True)
owner_membership.refresh_from_db()
print('  ->', note(r), '| status:', owner_membership.status)
if owner_membership.status != MembershipStatus.ACTIVE:
    failures.append('o owner revogou o proprio vinculo')

print('=== 4. suspender e reativar ===')
r = owner.post(f'/app/org/equipe/{doctor_b_membership.id}/suspend/', {}, follow=True)
doctor_b_membership.refresh_from_db()
print('  suspender ->', note(r), '| status:', doctor_b_membership.status)
if doctor_b_membership.status != MembershipStatus.SUSPENDED:
    failures.append('suspender nao funcionou')

# suspenso nao entra
suspended = Client()
suspended.force_login(User.objects.get(email='doctor-b@demo.neurodoc.local'))
s = suspended.session
s['tenant_id'] = str(doctor_b_membership.tenant_id)
s.save()
code = suspended.get('/app/scheduling/').status_code
print('  vinculo suspenso abrindo a agenda ->', code)
if code == 200:
    failures.append('vinculo suspenso continuou entrando')

r = owner.post(f'/app/org/equipe/{doctor_b_membership.id}/reactivate/', {}, follow=True)
doctor_b_membership.refresh_from_db()
print('  reativar ->', note(r), '| status:', doctor_b_membership.status)
if doctor_b_membership.status != MembershipStatus.ACTIVE:
    failures.append('reativar nao funcionou')

print('=== 5. registro profissional ===')
profile = PhysicianProfile.objects.get(user__email='doctor-b@demo.neurodoc.local')
print('  antes:', profile.crm_number, profile.crm_state, profile.verification_status)
r = owner.post(f'/app/org/equipe/{doctor_b_membership.id}/registro-profissional/', {
    'professional_name': 'Dr. Bruno Clinico', 'crm_number': '77777', 'crm_state': 'rj',
    'rqe': '1234', 'professional_phone': '', 'professional_email': '',
    'professional_address': '',
}, follow=True)
profile.refresh_from_db()
print('  ->', note(r))
print('  depois:', profile.crm_number, profile.crm_state, profile.verification_status)
if profile.verification_status != PhysicianProfile.VerificationStatus.PENDING:
    failures.append('trocar o CRM nao devolveu o registro para validacao')
if profile.crm_state != 'RJ':
    failures.append(f'UF nao normalizada: {profile.crm_state}')

# CRM com letra tem de ser recusado
r = owner.post(f'/app/org/equipe/{doctor_b_membership.id}/registro-profissional/', {
    'professional_name': 'Dr. Bruno Clinico', 'crm_number': 'CRM-12345', 'crm_state': 'SP',
}, follow=True)
print('  CRM invalido ->', note(r))

profile.crm_number, profile.crm_state = '54321', 'SP'
profile.verification_status = PhysicianProfile.VerificationStatus.VERIFIED
profile.save()

print('=== 6. convite ===')
before = Invitation.objects.count()
r = owner.post('/app/org/equipe/', {'email': 'nova-secretaria@example.com',
                                    'roles': ['secretary']}, follow=True)
created = Invitation.objects.count() - before
print('  convite criado:', created, '| token na tela:', b'token' in r.content.lower())
if created != 1:
    failures.append('o convite nao foi criado')

# convidar quem ja tem vinculo
r = owner.post('/app/org/equipe/', {'email': 'secretary-a@demo.neurodoc.local',
                                    'roles': ['secretary']}, follow=True)
body = r.content.decode()
print('  convidar quem ja esta dentro -> recusado:', 'já tem vínculo' in body)
if 'já tem vínculo' not in body:
    failures.append('convidou alguem que ja tem vinculo')

invitation = Invitation.objects.filter(email_binding='nova-secretaria@example.com').first()
page = owner.get('/app/org/equipe/').content.decode()
print('  convite pendente aparece na tela:', 'nova-secretaria@example.com' in page)
if 'nova-secretaria@example.com' not in page:
    failures.append('convite pendente nao aparece na lista')

r = owner.post(f'/app/org/convites/{invitation.id}/cancelar/', {}, follow=True)
invitation.refresh_from_db()
print('  cancelar ->', note(r), '| revogado:', invitation.revoked_at is not None)
if invitation.revoked_at is None:
    failures.append('o convite nao foi cancelado')
from tenancy.invitations import peek_invitation
invitation.delete()

print('=== 7. logotipo ===')
content = png_bytes()
r = owner.post('/app/org/clinica/logotipo/', {
    'logo': SimpleUploadedFile('logo.png', content, content_type='image/png'),
}, follow=True)
profile_c = ClinicProfile.objects.get(tenant__slug=TENANT)
print('  ->', note(r), '| mime:', profile_c.logo_mime, '| bytes:', profile_c.logo_bytes)
if profile_c.logo_mime != 'image/png':
    failures.append(f'logotipo nao gravado: {profile_c.logo_mime!r}')

served = owner.get('/app/org/clinica/logotipo.img')
print('  servido:', served.status_code, served.get('Content-Type'),
      'igual ao enviado:', served.content == content)
if served.status_code != 200 or served.content != content:
    failures.append('o logotipo servido nao confere com o enviado')

# a secretaria ve o logotipo (ele aparece no cabecalho), mas nao administra
code = secretary.get('/app/org/clinica/logotipo.img').status_code
print('  secretaria vendo o logotipo ->', code)
if code != 200:
    failures.append(f'a secretaria nao consegue ver o logotipo ({code})')

# arquivo que nao e imagem
r = owner.post('/app/org/clinica/logotipo/', {
    'logo': SimpleUploadedFile('x.png', b'%PDF-1.4 nao sou imagem', content_type='image/png'),
}, follow=True)
print('  PDF renomeado ->', note(r))
if 'Formato não aceito' not in note(r):
    failures.append('aceitou arquivo que nao e imagem')

# arquivo grande demais
from tenancy.branding import MAX_LOGO_BYTES
big = png_bytes() + b'\x00' * MAX_LOGO_BYTES
r = owner.post('/app/org/clinica/logotipo/', {
    'logo': SimpleUploadedFile('big.png', big, content_type='image/png'),
}, follow=True)
print('  imagem grande ->', note(r))
if 'MB' not in note(r):
    failures.append('aceitou imagem acima do limite')

print('=== 8. identidade da clinica ===')
r = owner.post('/app/org/clinica/', {
    'address_line': 'Av. Paulista, 1000, conj. 51', 'address_district': 'Bela Vista',
    'city': 'São Paulo', 'state': 'sp', 'postal_code': '01310-100',
    'phone': '(11) 3333-0000', 'email': 'contato@clinica.example.com', 'website': '',
}, follow=True)
profile_c.refresh_from_db()
print('  ->', note(r))
print('  cabecalho:', profile_c.address_summary())
if profile_c.state != 'SP':
    failures.append(f'UF nao normalizada: {profile_c.state}')
if 'Av. Paulista' not in profile_c.address_summary():
    failures.append('endereco nao gravado')

r = owner.post('/app/org/clinica/logotipo/', {'action': 'remove'}, follow=True)
profile_c.refresh_from_db()
print('  remover logotipo ->', note(r), '| tem logo:', profile_c.has_logo)
if profile_c.has_logo:
    failures.append('o logotipo nao foi removido')

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: G3 completo.')
