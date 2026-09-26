"""Chave longa nao pode estourar a coluna da dica.

Regressao do DataError ao salvar uma chave de IA de verdade: a mascara
tinha o tamanho do segredo e as colunas de dica tem 40 caracteres.
"""
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

from accounts.models import User
from ai.models import AIProviderSettings
from communications.models import DoctorEmailSettings, MessagingSettings
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
failures = []

user = User.objects.get(email='doctor-a@demo.neurodoc.local')
m = Membership.objects.get(user=user, tenant__slug=TENANT)
c = Client()
c.force_login(user)
s = c.session
s['tenant_id'] = str(m.tenant_id)
s.save()


def note(r):
    items = [str(x) for x in get_messages(r.wsgi_request)]
    return items[-1] if items else '(sem aviso)'


# Chave no formato e no tamanho de uma do OpenRouter.
LONG_KEY = 'sk-or-v1-' + '9f3c8a2b7e1d4056' * 4          # 73 caracteres
LONG_PASSWORD = 'S3nh4-mu1t0-l0nga-' + 'z' * 60          # 78 caracteres

print('=== 1. IA: chave longa salva sem estourar a coluna ===')
print('  tamanho da chave:', len(LONG_KEY))
r = c.post('/app/org/ia/salvar/', {
    'provider': 'openrouter', 'base_url': '', 'model': '', 'api_key': LONG_KEY,
}, follow=True)
print('  ->', note(r))
row = AIProviderSettings.objects.get(tenant__slug=TENANT)
print('  dica:', row.api_key_hint, '| tamanho:', len(row.api_key_hint))
if not row.has_api_key:
    failures.append('a chave longa nao foi gravada')
if len(row.api_key_hint) > 40:
    failures.append(f'a dica estourou a coluna ({len(row.api_key_hint)})')
if row.api_key() != LONG_KEY:
    failures.append('a chave longa nao volta intacta ao decifrar')
if LONG_KEY[-8:-4] in row.api_key_hint:
    failures.append('a dica revela mais do que os ultimos 4 caracteres')

print('=== 2. SMTP da clinica: senha longa ===')
print('  tamanho da senha:', len(LONG_PASSWORD))
r = c.post('/app/org/mensageria/email-da-clinica/', {
    'email_enabled': 'on', 'email_from_name': 'Clinica', 'email_from_address': 'x@example.com',
    'email_reply_to': '', 'smtp_host': 'smtp.example.com', 'smtp_port': '587',
    'smtp_user': 'x@example.com', 'smtp_use_tls': 'on', 'smtp_password': LONG_PASSWORD,
}, follow=True)
print('  ->', note(r))
ms = MessagingSettings.objects.get(tenant__slug=TENANT)
print('  dica:', ms.smtp_password_hint, '| tamanho:', len(ms.smtp_password_hint))
if not ms.has_smtp_password:
    failures.append('a senha longa nao foi gravada')
if len(ms.smtp_password_hint) > 40:
    failures.append(f'a dica do SMTP estourou a coluna ({len(ms.smtp_password_hint)})')
if ms.smtp_password() != LONG_PASSWORD:
    failures.append('a senha longa nao volta intacta ao decifrar')

print('=== 3. SMS: chave longa ===')
r = c.post('/app/org/mensageria/sms/', {
    'sms_enabled': '', 'sms_sender_name': 'Clinica', 'api_key': LONG_KEY,
}, follow=True)
print('  ->', note(r))
ms.refresh_from_db()
print('  dica:', ms.sms_api_key_hint, '| tamanho:', len(ms.sms_api_key_hint))
if len(ms.sms_api_key_hint) > 40:
    failures.append(f'a dica do SMS estourou a coluna ({len(ms.sms_api_key_hint)})')

print('=== 4. e-mail do medico: senha longa ===')
doctor = Membership.objects.get(user__email='doctor-b@demo.neurodoc.local', tenant__slug=TENANT)
r = c.post(f'/app/org/mensageria/email/{doctor.id}/', {
    'enabled': '', 'from_name': 'Dr', 'from_email': 'dr@example.com', 'reply_to': '',
    'smtp_host': 'smtp.example.com', 'smtp_port': '587', 'smtp_user': 'dr@example.com',
    'use_tls': 'on', 'smtp_password': LONG_PASSWORD,
}, follow=True)
print('  ->', note(r))
de = DoctorEmailSettings.objects.filter(physician_membership=doctor).first()
if de is not None:
    print('  dica:', de.smtp_password_hint, '| tamanho:', len(de.smtp_password_hint))
    if len(de.smtp_password_hint) > 40:
        failures.append(f'a dica do medico estourou a coluna ({len(de.smtp_password_hint)})')

# devolve tudo ao estado limpo
AIProviderSettings.objects.all().delete()
MessagingSettings.objects.update(
    email_enabled=False, email_from_address='', email_from_name='',
    smtp_host='', smtp_port=None, smtp_user='',
    smtp_password_ciphertext='', smtp_password_metadata={}, smtp_password_hint='',
    sms_api_key_ciphertext='', sms_api_key_metadata={}, sms_api_key_hint='',
    sms_sender_name='')
DoctorEmailSettings.objects.filter(physician_membership=doctor).delete()

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: segredo de qualquer tamanho cabe na dica, nos quatro lugares.')
