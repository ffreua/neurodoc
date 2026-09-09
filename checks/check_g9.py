"""G9: comunicacao em massa, com as salvaguardas que a tornam admissivel."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

import re

from django.contrib.messages import get_messages
from django.core import mail
from django.utils import timezone

from accounts.models import User
from communications import marketing
from communications.models import (
    CampaignStatus, MarketingCampaign, MarketingRecipient, MessagingSettings, RecipientStatus,
)
from patients.models import Patient, PatientContact
from tenancy.models import Membership, Tenant

failures = []
criados = []
tenant = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')


def note(r):
    itens = [str(m) for m in get_messages(r.wsgi_request)]
    return itens[-1] if itens else '(sem aviso)'


def client_for(email, t=tenant):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(t.id)
    s.save()
    return c


owner = client_for('doctor-a@demo.neurodoc.local')
secretary = client_for('secretary-a@demo.neurodoc.local')

# O servidor de e-mail da clinica precisa estar ativo; sem host proprio o
# envio sai pelo backend em memoria da instalacao.
ms = MessagingSettings.objects.get(tenant=tenant)
estado_ms = (ms.email_enabled, ms.email_from_name, ms.email_from_address)
ms.email_enabled = True
ms.email_from_name = 'Clinica Demo A'
ms.email_from_address = 'contato@clinica-demo.example.com'
ms.smtp_host = ''
ms.save()

pacientes = list(Patient.objects.filter(tenant=tenant)[:3])
contatos = []
for i, p in enumerate(pacientes):
    c = PatientContact.objects.create(
        tenant=tenant, patient=p, name=f'Contato G9 {i}', relationship='self',
        email=f'g9-{i}@example.com', phone='')
    contatos.append(c)
    criados.append(c)

print('=== 1. sem consentimento, ninguem entra na lista ===')
elegiveis = marketing.eligible_contacts(tenant.id)
print('  contatos criados:', len(contatos), '| elegiveis:', elegiveis.count())
if elegiveis.filter(id__in=[c.id for c in contatos]).exists():
    failures.append('contato sem consentimento entrou na lista')

print('=== 2. consentimento registrado com procedencia ===')
for c in contatos[:2]:
    c.marketing_opt_in_at = timezone.now()
    c.marketing_opt_in_evidence = 'assinou no balcao (teste)'
    c.save()
elegiveis = marketing.eligible_contacts(tenant.id)
print('  agora elegiveis (dos criados):',
      elegiveis.filter(id__in=[c.id for c in contatos]).count())
if elegiveis.filter(id__in=[c.id for c in contatos]).count() != 2:
    failures.append('os contatos que consentiram nao entraram na lista')

print('=== 3. so quem administra alcanca as telas ===')
for label, c, esperado in [('owner', owner, 200), ('secretaria', secretary, 404)]:
    code = c.get('/app/org/campanhas/').status_code
    print(f'  {label:11} -> {code}')
    if code != esperado:
        failures.append(f'{label} em campanhas: esperava {esperado}, veio {code}')

print('=== 4. criar campanha monta a lista congelada ===')
r = owner.post('/app/org/campanhas/nova/', {
    'subject': 'Campanha de teste G9',
    'body_text': 'Mensagem de teste da campanha.',
    'per_minute': '2',
}, follow=True)
campanha = MarketingCampaign.objects.filter(subject='Campanha de teste G9').first()
criados.append(campanha)
print('  ->', note(r))
print('  destinatarios:', campanha.counts.get('total') if campanha else None)
if campanha is None:
    failures.append('a campanha nao foi criada')
    raise SystemExit(1)
if campanha.status != CampaignStatus.DRAFT:
    failures.append('a campanha nasceu fora de rascunho')

print('=== 5. ritmo acima do teto e recusado ===')
r = owner.post('/app/org/campanhas/nova/', {
    'subject': 'Rapida demais', 'body_text': 'x', 'per_minute': '5000',
}, follow=True)
print('  recusou:', 'O máximo é' in r.content.decode())
if 'O máximo é' not in r.content.decode():
    failures.append('aceitou ritmo acima do teto')

print('=== 6. disparo respeita o ritmo (fatia por minuto) ===')
mail.outbox = []
marketing.start(campanha)
campanha.refresh_from_db()
print('  status:', campanha.status)
resultado = marketing.send_batch(campanha)
print('  fatia:', resultado)
print('  e-mails na caixa:', len(mail.outbox))
if len(mail.outbox) > campanha.per_minute:
    failures.append(f'a fatia enviou {len(mail.outbox)}, acima do ritmo {campanha.per_minute}')

print('=== 7. TODA mensagem leva o link de descadastro ===')
sem_link = [m for m in mail.outbox if '/descadastrar/' not in m.body]
print('  mensagens sem link:', len(sem_link))
if sem_link:
    failures.append(f'{len(sem_link)} mensagem(ns) sairam sem link de descadastro')
if mail.outbox:
    corpo = mail.outbox[0].body
    print('  diz por que a pessoa recebeu:', 'porque autorizou' in corpo)
    print('  separa divulgacao de atendimento:', 'canais de sempre' in corpo)
    print('  remetente:', mail.outbox[0].from_email)
    if 'porque autorizou' not in corpo:
        failures.append('o rodape nao explica por que a pessoa recebeu')

print('=== 8. o descadastro e um clique, sem conta ===')
link = re.search(r'/descadastrar/([A-Za-z0-9_-]+)/', mail.outbox[0].body).group(1)
anon = Client()
r = anon.get(f'/descadastrar/{link}/')
print('  GET pede confirmacao:', r.status_code == 200 and 'Não quero mais receber' in r.content.decode())
if 'Não quero mais receber' not in r.content.decode():
    failures.append('o GET do descadastro nao pede confirmacao')
# GET nao pode descadastrar sozinho (cliente de e-mail pre-carrega links)
alvo = PatientContact.objects.get(marketing_unsubscribe_token=link)
if alvo.marketing_opt_out_at is not None:
    failures.append('o GET descadastrou sem confirmacao')

r = anon.post(f'/descadastrar/{link}/')
alvo.refresh_from_db()
print('  POST descadastrou:', alvo.marketing_opt_out_at is not None)
print('  avisa que o atendimento continua:', 'fazem parte do cuidado' in r.content.decode())
if alvo.marketing_opt_out_at is None:
    failures.append('o descadastro nao funcionou')

print('=== 9. o consentimento original NAO e apagado ===')
print('  opt_in preservado:', alvo.marketing_opt_in_at is not None)
print('  procedencia preservada:', bool(alvo.marketing_opt_in_evidence))
if alvo.marketing_opt_in_at is None:
    failures.append('o descadastro apagou a prova do consentimento')

print('=== 10. quem se descadastrou e PULADO no envio seguinte ===')
# Devolve o contato para a fila desta campanha e reenvia.
MarketingRecipient.objects.filter(campaign=campanha, contact=alvo).update(
    status=RecipientStatus.PENDING)
mail.outbox = []
marketing.send_batch(campanha, limit=10)
linha = MarketingRecipient.objects.get(campaign=campanha, contact=alvo)
print('  status do descadastrado:', linha.status, '|', linha.detail[:40])
print('  recebeu mensagem:', any(alvo.email in m.to for m in mail.outbox))
if linha.status != RecipientStatus.SKIPPED:
    failures.append('quem se descadastrou nao foi pulado')
if any(alvo.email in m.to for m in mail.outbox):
    failures.append('MENSAGEM ENVIADA A QUEM SE DESCADASTROU')

print('=== 11. reenvio nao duplica quem ja recebeu ===')
enviadas_antes = MarketingRecipient.objects.filter(
    campaign=campanha, status=RecipientStatus.SENT).count()
mail.outbox = []
marketing.send_batch(campanha, limit=50)
print('  ja enviadas:', enviadas_antes, '| novas mensagens:', len(mail.outbox))
if any(m.to[0] in [r.email for r in MarketingRecipient.objects.filter(
        campaign=campanha, status=RecipientStatus.SENT)[:enviadas_antes]] for m in mail.outbox):
    failures.append('reenvio duplicou mensagem para quem ja recebeu')

print('=== 12. campanha sem servidor da clinica e recusada ===')
ms.email_enabled = False
ms.save()
nova = MarketingCampaign.objects.create(
    tenant=tenant, subject='Sem servidor', body_text='x', per_minute=5)
criados.append(nova)
marketing.build_recipients(nova)
try:
    marketing.guard(nova)
    failures.append('aceitou disparar sem servidor de e-mail da clinica')
    print('  ACEITOU (nao deveria)')
except marketing.CampaignBlocked as exc:
    print('  ->', str(exc)[:80])
ms.email_enabled = True
ms.save()

print('=== 13. isolamento: a clinica B nao ve a campanha da A ===')
owner_b = client_for('doctor-a@demo.neurodoc.local', tenant_b)
body = owner_b.get('/app/org/campanhas/').content.decode()
print('  clinica B ve a campanha da A:', 'Campanha de teste G9' in body)
if 'Campanha de teste G9' in body:
    failures.append('a campanha vazou entre organizacoes')
code = owner_b.get(f'/app/org/campanhas/{campanha.id}/').status_code
print('  abrir a campanha da A pela clinica B -> HTTP', code)
if code != 404:
    failures.append(f'campanha de outra clinica acessivel (HTTP {code})')

print('=== 14. a lista da clinica B nao inclui contatos da A ===')
elegiveis_b = marketing.eligible_contacts(tenant_b.id)
ids_a = {c.id for c in contatos}
print('  contatos da A na lista da B:', elegiveis_b.filter(id__in=ids_a).count())
if elegiveis_b.filter(id__in=ids_a).exists():
    failures.append('a lista da clinica B incluiu contatos da clinica A')

# limpeza
for obj in criados:
    if obj is None:
        continue
    if isinstance(obj, MarketingCampaign):
        MarketingRecipient.objects.filter(campaign=obj).delete()
        MarketingCampaign.objects.filter(id=obj.id).delete()
MarketingRecipient.objects.filter(contact__in=contatos).delete()
PatientContact.objects.filter(id__in=[c.id for c in contatos]).delete()
ms.email_enabled, ms.email_from_name, ms.email_from_address = estado_ms
ms.save()

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: G9 completo.')
