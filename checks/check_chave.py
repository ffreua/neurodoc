"""Separacao da chave-mestra de segredos e a rotacao que a torna possivel.

O que este teste tenta quebrar: definir a SECRETS_MASTER_KEY sem rotacionar
(que quebraria em silencio a chave de SMS, o SMTP e a IA de toda clinica),
a rotacao rodada duas vezes, e o segredo que nao abre com nenhuma das duas
chaves parando o lote inteiro.
"""
from io import StringIO

from cryptography.fernet import Fernet
from django.conf import settings as dj_settings
from django.core.management import call_command

from ai.models import AIProviderSettings
from base.crypto import (
    SecretUnavailable, decrypt_secret, master_key_is_shared, rewrap_secret,
)
from communications.models import MessagingSettings
from tenancy.models import Tenant

falhas = []
criados = []

CHAVE_ANTIGA = dj_settings.PFX_MASTER_KEY
CHAVE_NOVA = dj_settings.SECRETS_MASTER_KEY

print('=' * 66)
print('1. AS DUAS CHAVES SAO DISTINTAS')
print('=' * 66)
print('  SECRETS_MASTER_KEY definida ->', bool(CHAVE_NOVA))
print('  igual a do PFX              ->', CHAVE_NOVA == CHAVE_ANTIGA)
print('  alerta de chave compartilhada ->', master_key_is_shared())
if not CHAVE_NOVA:
    falhas.append('SECRETS_MASTER_KEY nao esta definida')
if CHAVE_NOVA and CHAVE_NOVA == CHAVE_ANTIGA:
    falhas.append('a chave de segredos e a mesma do certificado de assinatura')
if master_key_is_shared():
    falhas.append('o sistema ainda considera a chave compartilhada')


def cifra_com(chave, valor):
    """Cifra como a versao antiga cifrava: envelope, embrulhado por `chave`."""
    data_key = Fernet.generate_key()
    ciphertext = Fernet(data_key).encrypt(valor.encode())
    wrapped = Fernet(chave.encode()).encrypt(data_key)
    return ciphertext.decode(), {'wrapped_key': wrapped.decode()}


print()
print('=' * 66)
print('2. SEGREDO DA CHAVE ANTIGA NAO ABRE SOZINHO')
print('=' * 66)

tenant = Tenant.objects.get(slug='demo-clinica-a')
SEGREDO_SMS = 'chave-de-sms-de-teste-0123456789'
SEGREDO_IA = 'sk-teste-de-ia-abcdefghijklmnopqrstuvwxyz'

msg, _ = MessagingSettings.objects.get_or_create(tenant=tenant)
antes_msg = (msg.sms_api_key_ciphertext, dict(msg.sms_api_key_metadata or {}))
msg.sms_api_key_ciphertext, msg.sms_api_key_metadata = cifra_com(CHAVE_ANTIGA, SEGREDO_SMS)
msg.save(update_fields=['sms_api_key_ciphertext', 'sms_api_key_metadata'])

ia, ia_criado = AIProviderSettings.objects.get_or_create(tenant=tenant)
antes_ia = (ia.api_key_ciphertext, dict(ia.api_key_metadata or {}))
ia.api_key_ciphertext, ia.api_key_metadata = cifra_com(CHAVE_ANTIGA, SEGREDO_IA)
ia.save(update_fields=['api_key_ciphertext', 'api_key_metadata'])

for rotulo, texto, meta in [('SMS', msg.sms_api_key_ciphertext, msg.sms_api_key_metadata),
                            ('IA ', ia.api_key_ciphertext, ia.api_key_metadata)]:
    try:
        decrypt_secret(texto, meta)
        print(f'  {rotulo} cifrado na chave antiga -> ABRIU (nao deveria)')
        falhas.append(f'{rotulo}: segredo da chave antiga abriu com a nova')
    except SecretUnavailable:
        print(f'  {rotulo} cifrado na chave antiga -> nao abre, como esperado')

print()
print('=' * 66)
print('3. A ROTACAO DEVOLVE O ACESSO')
print('=' * 66)

# O texto cifrado antes da rotacao, para provar que ela nao o reescreve.
cifrado_antes = msg.sms_api_key_ciphertext
embrulho_antes = (msg.sms_api_key_metadata or {}).get('wrapped_key')

saida = StringIO()
call_command('rotate_secrets_master_key', stdout=saida)
print(' ', saida.getvalue().strip().splitlines()[-1])

msg.refresh_from_db()
ia.refresh_from_db()
for rotulo, texto, meta, esperado in [
    ('SMS', msg.sms_api_key_ciphertext, msg.sms_api_key_metadata, SEGREDO_SMS),
    ('IA ', ia.api_key_ciphertext, ia.api_key_metadata, SEGREDO_IA),
]:
    try:
        valor = decrypt_secret(texto, meta)
        igual = valor == esperado
        print(f'  {rotulo} depois da rotacao -> abre, valor {"intacto" if igual else "DIFERENTE"}')
        if not igual:
            falhas.append(f'{rotulo}: o valor mudou na rotacao')
    except SecretUnavailable as exc:
        print(f'  {rotulo} depois da rotacao -> NAO ABRE ({exc})')
        falhas.append(f'{rotulo}: continuou fechado depois da rotacao')

# O valor cifrado nao pode ter sido reescrito: quem muda e o embrulho.
# E o que torna a rotacao barata e mantem o valor em claro fora da
# memoria do processo em lote.
embrulho_depois = (msg.sms_api_key_metadata or {}).get('wrapped_key')
print('  texto cifrado intacto ->', msg.sms_api_key_ciphertext == cifrado_antes)
print('  embrulho trocado      ->', embrulho_depois != embrulho_antes)
if msg.sms_api_key_ciphertext != cifrado_antes:
    falhas.append('a rotacao reescreveu o valor cifrado; so o embrulho deveria mudar')
if embrulho_depois == embrulho_antes:
    falhas.append('o embrulho nao mudou — a rotacao nao fez nada')

print()
print('=' * 66)
print('4. RODAR DE NOVO NAO ESTRAGA')
print('=' * 66)
saida = StringIO()
call_command('rotate_secrets_master_key', stdout=saida)
linha = saida.getvalue().strip().splitlines()[-1]
print(' ', linha)
if 'reembrulhado' not in linha:
    falhas.append('a segunda rodada nao reportou nada')
msg.refresh_from_db()
try:
    if decrypt_secret(msg.sms_api_key_ciphertext, msg.sms_api_key_metadata) != SEGREDO_SMS:
        falhas.append('a segunda rodada corrompeu o segredo')
    print('  segredo continua intacto -> sim')
except SecretUnavailable:
    falhas.append('a segunda rodada quebrou o segredo')

print()
print('=' * 66)
print('5. SEGREDO PERDIDO NAO PARA O LOTE')
print('=' * 66)
# Embrulho feito com uma terceira chave: nao abre com nenhuma das duas.
terceira = Fernet.generate_key().decode()
msg.sms_api_key_ciphertext, msg.sms_api_key_metadata = cifra_com(terceira, 'perdido')
msg.save(update_fields=['sms_api_key_ciphertext', 'sms_api_key_metadata'])
saida = StringIO()
call_command('rotate_secrets_master_key', stdout=saida)
texto = saida.getvalue()
avisou = 'informados de novo' in texto
print('  o lote terminou e avisou o segredo perdido ->', avisou)
if not avisou:
    falhas.append('o segredo ilegivel nao foi reportado')

# O da IA, que estava bom, tem de continuar bom.
ia.refresh_from_db()
try:
    if decrypt_secret(ia.api_key_ciphertext, ia.api_key_metadata) != SEGREDO_IA:
        falhas.append('o segredo bom foi corrompido pela presenca de um ilegivel')
    print('  o segredo bom sobreviveu ao ilegivel ->', 'sim')
except SecretUnavailable:
    falhas.append('o segredo bom parou de abrir por causa de um ilegivel')

print()
print('=' * 66)
print('6. rewrap_secret RECUSA METADADO SEM EMBRULHO')
print('=' * 66)
try:
    rewrap_secret({}, CHAVE_ANTIGA, CHAVE_NOVA)
    print('  metadado vazio -> ACEITOU (nao deveria)')
    falhas.append('rewrap_secret aceitou metadado sem chave embrulhada')
except SecretUnavailable:
    print('  metadado vazio -> recusado, como esperado')

# ---------------------------------------------------------------- limpeza
msg.sms_api_key_ciphertext, msg.sms_api_key_metadata = antes_msg
msg.save(update_fields=['sms_api_key_ciphertext', 'sms_api_key_metadata'])
if ia_criado:
    ia.delete()
else:
    ia.api_key_ciphertext, ia.api_key_metadata = antes_ia
    ia.save(update_fields=['api_key_ciphertext', 'api_key_metadata'])
print()
print('estado anterior devolvido')

print('---')
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: chave de segredos separada da do certificado, e a rotacao preserva os valores.')
