"""O caminho de entrada do superadministrador sem vinculo em clinica.

Conta descartavel, para nao gastar o link real. O que este teste tenta
quebrar: o link nao abrir, a conta entrar sem MFA, a tela de "nenhuma
organizacao" ser um beco sem saida, e o link continuar valendo depois de
usado.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from io import StringIO

from django.contrib.auth.tokens import default_token_generator
from django.core.management import call_command
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent

EMAIL = 'descartavel-super@example.invalid'
SENHA = 'S3nhaEscolhida!2026'
falhas = []


def descartar_conta():
    """Apaga a conta do teste e o que a prende.

    A trilha de auditoria prende o usuario por `PROTECT`, e prende com
    razao: apagar a conta apagaria o registro do que ela fez. Aqui os
    eventos sao do proprio teste, entao saem junto — o que nao vale para
    conta de gente.
    """
    alvo = User.objects.filter(email=EMAIL)
    TOTPDevice.objects.filter(user__in=alvo).delete()
    AuditEvent.objects.filter(actor__in=alvo).delete()
    alvo.delete()


descartar_conta()

saida = StringIO()
call_command('create_superadmin', EMAIL, '--first-name', 'Descartavel',
             '--invite', stdout=saida)
texto = saida.getvalue()
user = User.objects.get(email=EMAIL)
print('conta criada | senha utilizavel:', user.has_usable_password())
# Utilizavel de proposito: uma senha aleatoria que ninguem viu impede o
# login igual a uma inutilizavel, e — ao contrario dela — nao e descartada
# em silencio pelo `PasswordResetForm`. Sem isso, perdido o link do
# convite, a conta ficaria sem caminho de volta.
if not user.has_usable_password():
    falhas.append('--invite deixou a conta sem senha utilizavel: o "Esqueci minha senha" '
                  'descarta essas contas em silencio')
if '/accounts/reset/' not in texto:
    falhas.append('o comando nao imprimiu o link de definicao de senha')

# --- 0. "Esqueci minha senha" alcanca a conta recem-convidada ---
from django.contrib.auth.forms import PasswordResetForm

formulario = PasswordResetForm({'email': EMAIL})
formulario.is_valid()
encontrados = list(formulario.get_users(EMAIL))
print('"Esqueci minha senha" encontra a conta ->', bool(encontrados))
if not encontrados:
    falhas.append('o formulario de recuperacao nao encontra a conta convidada')

uid = urlsafe_base64_encode(force_bytes(user.pk))
token = default_token_generator.make_token(user)
link = f'/accounts/reset/{uid}/{token}/'

# --- 1. o link abre e aceita a senha ---
c = Client()
r = c.get(link, follow=True)
print('abrir o link ->', r.status_code, '| formulario:',
      'new_password1' in r.content.decode())
if r.status_code != 200 or 'new_password1' not in r.content.decode():
    falhas.append('o link de definicao de senha nao abriu o formulario')

destino = r.request['PATH_INFO']
r = c.post(destino, {'new_password1': SENHA, 'new_password2': SENHA}, follow=True)
user.refresh_from_db()
print('definir senha ->', r.status_code, '| senha utilizavel agora:',
      user.has_usable_password())
if not user.check_password(SENHA):
    falhas.append('a senha escolhida no link nao foi gravada')

# --- 2. o link nao vale duas vezes ---
c2 = Client()
r = c2.get(link, follow=True)
reutilizavel = 'new_password1' in r.content.decode()
print('reutilizar o link ->', 'AINDA VALE' if reutilizavel else 'invalidado')
if reutilizavel:
    falhas.append('o link de definicao de senha continuou valendo depois de usado')

# --- 3. entra com a senha, e cai na MFA ---
c3 = Client()
# O campo e `username`, herdado do `AuthenticationForm` do Django — o
# rotulo e que diz "Email".
r = c3.post('/accounts/login/', {'username': EMAIL, 'password': SENHA}, follow=True)
if not r.wsgi_request.user.is_authenticated:
    falhas.append('o login com a senha recem-definida nao autenticou')
caminho = r.request['PATH_INFO']
print('login ->', caminho)
if 'mfa' not in caminho and 'setup' not in caminho:
    # sem dispositivo, o sistema pode levar direto ao cadastro do segundo fator
    print('  (nao caiu na MFA; conferindo se o console ja abre — nao deveria)')

# --- 4. sem MFA, o console recusa ---
r = c3.get('/instalacao/')
print('console sem MFA ->', r.status_code)
if r.status_code != 404:
    falhas.append(f'o console abriu sem MFA (HTTP {r.status_code})')

# --- 5. a tela de "nenhuma organizacao" nao e um beco sem saida ---
r = c3.get('/accounts/select-organization/', follow=True)
corpo = r.content.decode()
tem_saida = ('mfa/setup' in corpo) or ('/instalacao/' in corpo)
print('tela sem organizacao aponta caminho ->', 'sim' if tem_saida else 'NAO')
print('  (menciona MFA:', 'mfa/setup' in corpo, '| menciona console:',
      '/instalacao/' in corpo, ')')
if not tem_saida:
    falhas.append('a tela de "nenhuma organizacao" nao oferece saida ao superadministrador')

# --- 6. configura a MFA e o console abre ---
r = c3.get('/accounts/mfa/setup/')
print('abrir cadastro de MFA ->', r.status_code)
if r.status_code != 200:
    falhas.append(f'a tela de cadastro de MFA devolveu {r.status_code}')
else:
    device = TOTPDevice.objects.filter(user=user).order_by('-id').first()
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = __import__('time').time()
    codigo = str(totp.token()).zfill(device.digits)
    r = c3.post('/accounts/mfa/setup/', {'code': codigo}, follow=True)
    device.refresh_from_db()
    print('confirmar MFA ->', r.status_code, '| dispositivo confirmado:', device.confirmed)
    if not device.confirmed:
        falhas.append('a MFA nao foi confirmada com um codigo valido')

    # A sessao do cadastro ja fica verificada; o console tem de abrir.
    r = c3.get('/instalacao/')
    print('console com MFA ->', r.status_code)
    if r.status_code != 200:
        falhas.append(f'o console nao abriu depois da MFA (HTTP {r.status_code})')

# ---------------------------------------------------------------- limpeza
descartar_conta()
print('conta descartavel removida')

print('---')
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: o superadministrador entra, define senha, configura MFA e alcanca o console.')
