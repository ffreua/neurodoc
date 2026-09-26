"""G7: entrega ao paciente com link unico, 4 digitos do CPF e impressao."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False
# A caixa em memoria, independentemente do que o ambiente diga.
#
# Este roteiro afirma sobre `mail.outbox`, que so existe no backend
# `locmem`. Com o envio ligado (Mailpit no ambiente local), o backend
# padrao passa a ser o que enfileira, a caixa fica vazia e o roteiro
# falharia por configuracao do ambiente -- nao por regressao.
#
# `send_mail` le `EMAIL_BACKEND` a cada chamada, entao fixar aqui basta.
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'


from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter, EncounterStatus
from communications import access
from communications.models import Delivery, DocumentAccessToken
from documents import issuance
from documents.models import Attachment, MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.models import Patient, PatientContact
from tenancy.models import Membership, Tenant

failures = []
tenant = Tenant.objects.get(slug='demo-clinica-a')
doctor_m = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=tenant)
paciente = Patient.objects.filter(tenant=tenant, cpf__isnull=False).exclude(cpf='').first()
print('paciente:', paciente.full_name, '| CPF termina em', paciente.cpf[-4:])

enc = Encounter.objects.filter(tenant=tenant, patient=paciente).first()
if enc is None:
    enc = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=doctor_m,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT, chief_complaint='g7')

doc = issuance.create_draft(tenant, paciente, enc, doctor_m, doctor_m.user_id,
                            MedicalDocumentKind.PRESCRIPTION,
                            {'prescription_text': 'REMEDIO SECRETO DO TESTE',
                             'special_instructions': '', 'prescription_format': 'simple'})
# Emite sem assinar de verdade, e usa o PDF do rascunho como "assinado":
# o que se testa aqui e a entrega, nao a assinatura (coberta no G6).
doc.status = MedicalDocumentStatus.ISSUED
# Numero unico por execucao: a restricao de unicidade recusaria o
# mesmo numero se uma execucao anterior tivesse deixado lixo.
doc.document_number = f'REC-2026-G7-{timezone.now().timestamp():.0f}'
doc.issued_at = timezone.now()
doc.signed_pdf_attachment = doc.pdf_attachment
doc.save()

contato = PatientContact.objects.filter(patient=paciente).first()
contato_criado = False
if contato is None:
    contato = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name=paciente.full_name, relationship='self',
        phone='+5511999990123', email='paciente@example.com')
    contato_criado = True
estado_anterior = (contato.authorized_for_documents, contato.email_enabled,
                   contato.sms_enabled, contato.verified_email_at, contato.verified_phone_at)
contato.authorized_for_documents = True
contato.email_enabled = True
contato.email = contato.email or 'paciente@example.com'
contato.verified_email_at = timezone.now()
contato.save()

print('=== 1. entrega gera link e mensagem ===')
from communications.services import deliver_document
from django.core import mail

mail.outbox = []
deliveries = deliver_document(doc, force_new_link=True)
print('  entregas:', [(d.channel, d.status) for d in deliveries])
print('  e-mails na caixa:', len(mail.outbox))
if not deliveries:
    failures.append('nenhuma entrega foi criada')
corpo = mail.outbox[0].body if mail.outbox else ''
print('  a mensagem avisa sobre o CPF:', '4 últimos dígitos' in corpo)
print('  a mensagem NAO cita o conteudo:', 'REMEDIO SECRETO' not in corpo)
if 'REMEDIO SECRETO' in corpo:
    failures.append('a mensagem ao paciente vazou conteudo clinico')
if '4 últimos dígitos' not in corpo:
    failures.append('a mensagem nao diz o que sera pedido')

token_row = DocumentAccessToken.objects.filter(document=doc, revoked_at__isnull=True).first()
import re
achado = re.search(r'/d/([A-Za-z0-9_-]+)/', corpo)
raw = achado.group(1) if achado else None
print('  link no corpo:', bool(raw))
if not raw:
    failures.append('o link nao foi para a mensagem')

anon = Client()

print('=== 2. o link sozinho nao entrega o PDF ===')
r = anon.get(f'/d/{raw}/')
body = r.content.decode()
print('  HTTP:', r.status_code, '| pede os 4 digitos:', '4 últimos dígitos do CPF' in body)
print('  NAO mostra o nome do paciente:', paciente.full_name not in body)
if paciente.full_name in body:
    failures.append('a tela de conferencia revelou o nome do paciente antes da prova')
r = anon.get(f'/d/{raw}/arquivo/')
print('  arquivo sem conferencia -> HTTP', r.status_code)
if r.status_code != 404:
    failures.append(f'o PDF saiu sem conferencia (HTTP {r.status_code})')

print('=== 3. resposta errada e recusada e conta tentativa ===')
r = anon.post(f'/d/{raw}/', {'answer': '0000'})
print('  HTTP:', r.status_code, '| avisa:', 'não conferem' in r.content.decode())
if r.status_code != 403:
    failures.append(f'resposta errada devolveu {r.status_code}')
token_row.refresh_from_db()
print('  tentativas registradas:', token_row.otp_attempts)
if token_row.otp_attempts != 1:
    failures.append('a tentativa errada nao foi contada')

print('=== 4. os 4 digitos certos abrem ===')
r = anon.post(f'/d/{raw}/', {'answer': paciente.cpf[-4:]}, follow=True)
body = r.content.decode()
print('  HTTP:', r.status_code, '| tem botao imprimir:', 'Imprimir' in body)
print('  tem botao baixar:', 'Baixar PDF' in body)
if 'Imprimir' not in body or 'Baixar PDF' not in body:
    failures.append('a tela do documento nao oferece imprimir/baixar')

print('=== 5. o CPF inteiro tambem serve ===')
anon2 = Client()
r = anon2.post(f'/d/{raw}/', {'answer': paciente.cpf}, follow=True)
print('  HTTP:', r.status_code, '| abriu:', 'Baixar PDF' in r.content.decode())
if 'Baixar PDF' not in r.content.decode():
    failures.append('o CPF inteiro nao foi aceito')

print('=== 6. o PDF sai, e com cabecalhos de nao-cache ===')
r = anon.get(f'/d/{raw}/arquivo/')
print('  HTTP:', r.status_code, '| tipo:', r.get('Content-Type'))
print('  Cache-Control:', r.get('Cache-Control'))
if r.status_code != 200 or r.get('Content-Type') != 'application/pdf':
    failures.append('o PDF nao foi servido depois da conferencia')
if 'no-store' not in (r.get('Cache-Control') or ''):
    failures.append('o PDF foi servido sem no-store')
r = anon.get(f'/d/{raw}/arquivo/?baixar=1')
print('  download:', r.get('Content-Disposition'))
if 'attachment' not in (r.get('Content-Disposition') or ''):
    failures.append('o download nao veio como anexo')

print('=== 7. tentativas esgotadas travam o link ===')
outro_token, outro_raw = access.create_access_token(doc, contato)
bloqueio = Client()
for i in range(access.MAX_ATTEMPTS):
    r = bloqueio.post(f'/d/{outro_raw}/', {'answer': '1111'})
print('  ultimo HTTP:', r.status_code, '| bloqueou:', 'bloqueado' in r.content.decode())
if r.status_code != 429:
    failures.append(f'o link nao travou apos {access.MAX_ATTEMPTS} tentativas (HTTP {r.status_code})')
# nem a resposta certa abre depois de travado
r = bloqueio.post(f'/d/{outro_raw}/', {'answer': paciente.cpf[-4:]})
print('  resposta certa apos travar -> HTTP', r.status_code)
if r.status_code != 429:
    failures.append('o link travado aceitou a resposta certa')

print('=== 8. reenvio invalida o link anterior ===')
mail.outbox = []
deliver_document(doc, force_new_link=True)
novo_corpo = mail.outbox[0].body if mail.outbox else ''
novo_raw = re.search(r'/d/([A-Za-z0-9_-]+)/', novo_corpo).group(1)
print('  link novo e diferente:', novo_raw != raw)
antigo = Client()
r = antigo.get(f'/d/{raw}/')
print('  link antigo -> HTTP', r.status_code)
if r.status_code != 404:
    failures.append('o link antigo continuou valendo apos o reenvio')
novo = Client()
r = novo.post(f'/d/{novo_raw}/', {'answer': paciente.cpf[-4:]}, follow=True)
print('  link novo abre:', 'Baixar PDF' in r.content.decode())
if 'Baixar PDF' not in r.content.decode():
    failures.append('o link novo nao abriu')

print('=== 9. sessao de um link nao abre outro documento ===')
doc2 = issuance.create_draft(tenant, paciente, enc, doctor_m, doctor_m.user_id,
                             MedicalDocumentKind.REPORT, {'report_text': 'OUTRO DOCUMENTO'})
doc2.status = MedicalDocumentStatus.ISSUED
doc2.signed_pdf_attachment = doc2.pdf_attachment
doc2.issued_at = timezone.now()
doc2.save()
t2, raw2 = access.create_access_token(doc2, contato)
r = novo.get(f'/d/{raw2}/arquivo/')
print('  arquivo de outro documento com a sessao do primeiro -> HTTP', r.status_code)
if r.status_code != 404:
    failures.append('a sessao de um documento serviu para outro')

print('=== 10. paciente sem CPF cai na data de nascimento ===')
sem_cpf = Patient.objects.filter(tenant=tenant, cpf__isnull=True,
                                 birth_date__isnull=False).first()
if sem_cpf is None:
    print('  (sem paciente sem CPF na base; conferindo so a funcao)')
    print('  desafio para paciente com CPF:', access.challenge_kind(token_row))
else:
    enc3 = Encounter.objects.filter(tenant=tenant, patient=sem_cpf).first()
    if enc3 is None:
        enc3 = Encounter.objects.create(
            tenant=tenant, patient=sem_cpf, physician_membership=doctor_m,
            occurred_at=timezone.now(), status=EncounterStatus.DRAFT, chief_complaint='g7b')
    doc3 = issuance.create_draft(tenant, sem_cpf, enc3, doctor_m, doctor_m.user_id,
                                 MedicalDocumentKind.REPORT, {'report_text': 'MENOR'})
    doc3.status = MedicalDocumentStatus.ISSUED
    doc3.signed_pdf_attachment = doc3.pdf_attachment
    doc3.issued_at = timezone.now()
    doc3.save()
    c3 = PatientContact.objects.filter(patient=sem_cpf).first()
    t3, raw3 = access.create_access_token(doc3, c3 or contato)
    cli = Client()
    body = cli.get(f'/d/{raw3}/').content.decode()
    print('  pede data de nascimento:', 'Data de nascimento' in body)
    if 'Data de nascimento' not in body:
        failures.append('paciente sem CPF nao caiu na data de nascimento')
    r = cli.post(f'/d/{raw3}/', {'answer': sem_cpf.birth_date.strftime('%d/%m/%Y')}, follow=True)
    print('  data certa abre:', 'Baixar PDF' in r.content.decode())
    if 'Baixar PDF' not in r.content.decode():
        failures.append('a data de nascimento correta nao abriu o documento')
    DocumentAccessToken.objects.filter(document=doc3).delete()
    Delivery.objects.filter(document=doc3).delete()
    anexo3 = doc3.pdf_attachment_id
    MedicalDocument.objects.filter(id=doc3.id).delete()
    Attachment.objects.filter(id=anexo3).delete()

# limpeza
from communications.models import DeliveryAttempt

for d in [doc, doc2]:
    anexos = [a for a in [d.pdf_attachment_id] if a]
    entregas = Delivery.objects.filter(document=d)
    DeliveryAttempt.objects.filter(delivery__in=entregas).delete()
    entregas.delete()
    DocumentAccessToken.objects.filter(document=d).delete()
    MedicalDocument.objects.filter(id=d.id).delete()
    Attachment.objects.filter(id__in=anexos).delete()
if contato_criado:
    PatientContact.objects.filter(id=contato.id).delete()
else:
    (contato.authorized_for_documents, contato.email_enabled, contato.sms_enabled,
     contato.verified_email_at, contato.verified_phone_at) = estado_anterior
    contato.save()

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: G7 completo.')
