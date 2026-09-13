"""G4+G5: provedor de IA por clinica e SMTP da clinica, com os testes."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# A caixa em memoria, independentemente do que o ambiente diga.
#
# Este roteiro afirma sobre `mail.outbox`, que so existe no backend
# `locmem`. Com o envio ligado (Mailpit no ambiente local), o backend
# padrao passa a ser o que enfileira, a caixa fica vazia e o roteiro
# falharia por configuracao do ambiente -- nao por regressao.
#
# `send_mail` le `EMAIL_BACKEND` a cada chamada, entao fixar aqui basta.
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'


from django.contrib.messages import get_messages
from django.core import mail

from accounts.models import User
from ai.models import AIProviderSettings
from communications.models import MessagingSettings
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
failures = []


def note(r):
    items = [str(m) for m in get_messages(r.wsgi_request)]
    return items[-1] if items else '(sem aviso)'


def client_for(email, slug=TENANT):
    user = User.objects.get(email=email)
    m = Membership.objects.get(user=user, tenant__slug=slug)
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(m.tenant_id)
    s.save()
    return c, m


# Estado limpo: a linha de configuracao sobrevive entre execucoes, e uma
# chave deixada pela rodada anterior faz o teste "ativar sem chave" passar
# por engano.
AIProviderSettings.objects.filter(tenant__slug=TENANT).delete()
MessagingSettings.objects.filter(tenant__slug=TENANT).update(
    email_enabled=False, email_from_address='', email_from_name='',
    smtp_host='', smtp_port=None, smtp_user='',
    smtp_password_ciphertext='', smtp_password_metadata={}, smtp_password_hint='',
    smtp_use_tls=True, smtp_use_ssl=False,
)

owner, owner_m = client_for('doctor-a@demo.neurodoc.local')
manager, _ = client_for('manager-a@demo.neurodoc.local')
secretary, _ = client_for('secretary-a@demo.neurodoc.local')
owner_b, _ = client_for('doctor-a@demo.neurodoc.local', 'demo-clinica-b')

print('=== 1. quem alcanca as telas ===')
for label, c, expected in [('owner', owner, 200), ('gestor', manager, 200), ('secretaria', secretary, 404)]:
    for route in ['/app/org/ia/', '/app/org/mensageria/']:
        code = c.get(route).status_code
        print(f'  {label:11} {route:24} -> {code}')
        if code != expected:
            failures.append(f'{label} em {route}: esperava {expected}, veio {code}')

print('=== 2. IA: ativar sem chave e sem modelo e recusado ===')
r = owner.post('/app/org/ia/salvar/', {
    'enabled': 'on', 'provider': 'openrouter', 'base_url': '', 'model': '', 'api_key': '',
}, follow=True)
body = r.content.decode()
print('  recusou por falta de chave:', 'informar a chave da API' in body)
print('  recusou por falta de modelo:', 'Escolha o modelo antes de ativar' in body)
if 'informar a chave da API' not in body:
    failures.append('ativou a IA sem chave')

print('=== 3. IA: provedor fora da lista exige endereco ===')
r = owner.post('/app/org/ia/salvar/', {
    'provider': 'custom', 'base_url': '', 'model': '', 'api_key': 'sk-teste',
}, follow=True)
print('  recusou custom sem endereco:', 'exige o endereço da API' in r.content.decode())
if 'exige o endereço da API' not in r.content.decode():
    failures.append('aceitou provedor custom sem endereco')

print('=== 4. IA: salvar desativada, com chave cifrada ===')
r = owner.post('/app/org/ia/salvar/', {
    'provider': 'openrouter', 'base_url': '', 'model': '', 'api_key': 'sk-or-v1-chave-de-teste',
}, follow=True)
row = AIProviderSettings.objects.get(tenant__slug=TENANT)
print('  ->', note(r))
print('  provedor:', row.provider, '| tem chave:', row.has_api_key, '| dica:', row.api_key_hint)
print('  texto claro NAO esta no banco:', 'sk-or-v1-chave-de-teste' not in row.api_key_ciphertext)
if not row.has_api_key:
    failures.append('a chave nao foi gravada')
if 'sk-or-v1-chave-de-teste' in row.api_key_ciphertext:
    failures.append('a chave foi gravada em texto claro')
if row.api_key() != 'sk-or-v1-chave-de-teste':
    failures.append('a chave nao volta ao valor original ao decifrar')

print('=== 5. IA: campo em branco NAO apaga a chave ===')
owner.post('/app/org/ia/salvar/', {
    'provider': 'openrouter', 'base_url': '', 'model': '', 'api_key': '',
}, follow=True)
row.refresh_from_db()
print('  chave preservada:', row.has_api_key)
if not row.has_api_key:
    failures.append('salvar com o campo em branco apagou a chave')

print('=== 6. IA: trocar de provedor limpa a lista de modelos ===')
row.available_models = ['modelo-a', 'modelo-b']
row.model = 'modelo-a'
row.save()
owner.post('/app/org/ia/salvar/', {
    'provider': 'anthropic', 'base_url': '', 'model': 'modelo-a', 'api_key': '',
}, follow=True)
row.refresh_from_db()
print('  provedor:', row.provider, '| modelos:', row.available_models)
if row.available_models:
    failures.append('trocar de provedor manteve a lista de modelos do anterior')

print('=== 7a. carregar modelos: chamada real ao provedor ===')
row.provider = 'openrouter'
row.save()
r = owner.post('/app/org/ia/modelos/', {'provider': 'openrouter', 'base_url': ''}, follow=True)
aviso = note(r)
row.refresh_from_db()
print('  ->', aviso[:120])
print('  modelos guardados:', len(row.available_models or []))
if 'sk-or-v1' in aviso:
    failures.append('a chave vazou para a mensagem de tela')
# O /models do OpenRouter e publico: a lista chega mesmo com chave falsa.
# A mensagem NAO pode afirmar que a chave foi aceita.
if row.available_models and 'chave foi aceita' in aviso:
    failures.append('a tela afirmou que a chave foi aceita sem ter provado isso')

print('=== 7b. chave invalida e reprovada no teste do modelo ===')
if row.available_models:
    row.model = row.available_models[0]
    row.save(update_fields=['model'])
    r = owner.post('/app/org/ia/testar/', {}, follow=True)
    aviso = note(r)
    print('  ->', aviso[:140])
    if 'respondeu' in aviso:
        failures.append('chave falsa passou no teste do modelo')
    if 'sk-or-v1' in aviso:
        failures.append('a chave vazou para a mensagem de tela')
else:
    print('  (sem lista de modelos; teste pulado)')

print('=== 8. isolamento: a clinica B tem a propria configuracao ===')
owner_b.get('/app/org/ia/')
rows = {r.tenant.slug: r for r in AIProviderSettings.objects.select_related('tenant')}
print('  linhas por clinica:', sorted(rows))
b = rows.get('demo-clinica-b')
print('  clinica B tem chave?', b.has_api_key if b else '(sem linha)')
if b is None:
    failures.append('a clinica B nao ganhou linha propria')
elif b.has_api_key:
    failures.append('a chave da clinica A vazou para a clinica B')

print('=== 9. SMTP da clinica: salvar e preservar senha ===')
r = owner.post('/app/org/mensageria/email-da-clinica/', {
    'email_enabled': 'on', 'email_from_name': 'Clinica Demo A',
    'email_from_address': 'contato@clinica-demo.example.com', 'email_reply_to': '',
    'smtp_host': 'smtp.example.com', 'smtp_port': '587', 'smtp_user': 'contato@clinica-demo.example.com',
    'smtp_use_tls': 'on', 'smtp_password': 'senha-de-teste',
}, follow=True)
ms = MessagingSettings.objects.get(tenant__slug=TENANT)
print('  ->', note(r))
print('  ativo:', ms.email_enabled, '| remetente:', ms.sender_header(), '| tem senha:', ms.has_smtp_password)
print('  senha em claro NAO esta no banco:', 'senha-de-teste' not in ms.smtp_password_ciphertext)
if not ms.email_enabled or not ms.has_smtp_password:
    failures.append('o SMTP da clinica nao foi gravado')
if ms.smtp_password() != 'senha-de-teste':
    failures.append('a senha nao volta ao valor original ao decifrar')

owner.post('/app/org/mensageria/email-da-clinica/', {
    'email_enabled': 'on', 'email_from_name': 'Clinica Demo A',
    'email_from_address': 'contato@clinica-demo.example.com', 'email_reply_to': '',
    'smtp_host': 'smtp.example.com', 'smtp_port': '465', 'smtp_user': 'contato@clinica-demo.example.com',
    'smtp_use_ssl': 'on', 'smtp_password': '',
}, follow=True)
ms.refresh_from_db()
print('  senha preservada ao trocar a porta:', ms.has_smtp_password, '| porta:', ms.smtp_port)
if not ms.has_smtp_password:
    failures.append('salvar com senha em branco apagou a senha')

print('=== 10. SMTP: TLS e SSL juntos e recusado ===')
r = owner.post('/app/org/mensageria/email-da-clinica/', {
    'email_enabled': 'on', 'email_from_name': 'X', 'email_from_address': 'x@example.com',
    'smtp_host': 'smtp.example.com', 'smtp_port': '587', 'smtp_user': 'x',
    'smtp_use_tls': 'on', 'smtp_use_ssl': 'on', 'smtp_password': '',
}, follow=True)
print('  recusou TLS+SSL:', 'alternativos' in r.content.decode())
if 'alternativos' not in r.content.decode():
    failures.append('aceitou TLS e SSL ao mesmo tempo')

print('=== 11. quem assina o e-mail: medico > clinica > instalacao ===')
from communications.email import resolve_sender

ms.refresh_from_db()
sender = resolve_sender(tenant_id=ms.tenant_id)
print('  sem medico -> remetente da clinica:', sender.header if sender else None)
if sender is None or 'contato@clinica-demo.example.com' not in sender.header:
    failures.append('o remetente da clinica nao foi escolhido')

doctor_m = Membership.objects.select_related('email_settings').get(
    user__email='doctor-a@demo.neurodoc.local', tenant__slug=TENANT,
)
from communications.models import DoctorEmailSettings

de, _ = DoctorEmailSettings.objects.get_or_create(
    tenant_id=doctor_m.tenant_id, physician_membership=doctor_m,
)
de.enabled = True
de.from_name = 'Dra. Ana Neuro'
de.from_email = 'ana@clinica-demo.example.com'
de.save()
doctor_m = Membership.objects.select_related('email_settings').get(id=doctor_m.id)
sender = resolve_sender(physician_membership=doctor_m)
print('  com medico -> remetente do medico:', sender.header if sender else None)
if sender is None or 'ana@clinica-demo.example.com' not in sender.header:
    failures.append('o remetente do medico nao teve prioridade')
de.enabled = False
de.save()

print('=== 12a. teste com servidor inexistente falha com mensagem legivel ===')
mail.outbox = []
r = owner.post('/app/org/mensageria/email-da-clinica/testar/',
               {'to_email': 'gestor@example.com'}, follow=True)
aviso = note(r)
print('  ->', aviso, '| enviados:', len(mail.outbox))
if 'conexão SMTP falhou' not in aviso:
    failures.append(f'servidor inexistente nao deu erro de conexao: {aviso}')
if mail.outbox:
    failures.append('enviou e-mail apesar de a conexao falhar')

print('=== 12b. sem servidor proprio, o envio usa o da instalacao ===')
# Clinica que so troca o remetente e manda pelo servidor da instalacao —
# que em desenvolvimento e o backend em memoria.
owner.post('/app/org/mensageria/email-da-clinica/', {
    'email_enabled': 'on', 'email_from_name': 'Clinica Demo A',
    'email_from_address': 'contato@clinica-demo.example.com', 'email_reply_to': '',
    'smtp_host': '', 'smtp_port': '', 'smtp_user': '', 'smtp_password': '',
}, follow=True)
mail.outbox = []
r = owner.post('/app/org/mensageria/email-da-clinica/testar/',
               {'to_email': 'gestor@example.com'}, follow=True)
print('  ->', note(r))
print('  mensagens na caixa:', len(mail.outbox))
if len(mail.outbox) != 1:
    failures.append(f'o teste nao enviou e-mail ({len(mail.outbox)} na caixa)')
else:
    msg = mail.outbox[0]
    print('  de:', msg.from_email, '| para:', msg.to, '| assunto:', msg.subject)
    if 'contato@clinica-demo.example.com' not in msg.from_email:
        failures.append('o teste nao usou o remetente da clinica')
    if 'gestor@example.com' not in msg.to:
        failures.append('o teste nao foi para o endereco informado')

print('=== 13. teste de e-mail com endereco invalido ===')
mail.outbox = []
r = owner.post('/app/org/mensageria/email-da-clinica/testar/',
               {'to_email': 'nao-e-email'}, follow=True)
print('  ->', note(r), '| enviados:', len(mail.outbox))
if mail.outbox:
    failures.append('enviou teste para endereco invalido')

print('=== 14. secretaria nao configura nada disso ===')
for route in ['/app/org/ia/salvar/', '/app/org/ia/testar/',
              '/app/org/mensageria/email-da-clinica/']:
    code = secretary.post(route, {}).status_code
    print(f'  {route:44} -> {code}')
    if code != 404:
        failures.append(f'a secretaria alcancou {route} (HTTP {code})')

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: G4+G5 completos.')
