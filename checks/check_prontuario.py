"""Numero de prontuario, tela de documentos do paciente e trilha de navegacao."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

import json

from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter, EncounterStatus
from documents import issuance
from documents.models import MedicalDocument, MedicalDocumentKind
from patients.models import Patient
from tenancy.models import Membership, Tenant

failures = []
criados = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
doctor_m = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=tenant_a)


def client_for(email, tenant):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


doctor = client_for('doctor-a@demo.neurodoc.local', tenant_a)
secretary = client_for('secretary-a@demo.neurodoc.local', tenant_a)

print('=== 1. todo paciente tem numero, e ele e por clinica ===')
sem = Patient.objects.filter(record_number='').count()
print('  pacientes sem numero:', sem)
if sem:
    failures.append(f'{sem} paciente(s) sem numero de prontuario')

primeiros = {
    t.slug: Patient.objects.filter(tenant=t).order_by('record_number').first().record_number
    for t in (tenant_a, tenant_b)
}
print('  primeiro numero de cada clinica:', primeiros)
if len(set(primeiros.values())) != 1:
    failures.append('as clinicas nao comecam do mesmo numero — a sequencia nao e por clinica')

print('=== 2. paciente novo recebe o proximo numero ===')
antes = Patient.objects.filter(tenant=tenant_a).count()
novo = Patient.objects.create(
    tenant=tenant_a, full_name='Paciente Numerado Teste',
    birth_date_unknown_reason='teste')
criados.append(novo)
print('  numero atribuido:', novo.record_number)
if not novo.record_number:
    failures.append('paciente novo nasceu sem numero')
usados = set(Patient.objects.filter(tenant=tenant_a).values_list('record_number', flat=True))
if len(usados) != Patient.objects.filter(tenant=tenant_a).count():
    failures.append('ha numeros repetidos na mesma clinica')

print('=== 3. apagar um paciente NAO reaproveita o numero ===')
numero_do_apagado = novo.record_number
novo_id = novo.id
Patient.objects.filter(id=novo_id).delete()
criados.remove(novo)
outro = Patient.objects.create(
    tenant=tenant_a, full_name='Paciente Numerado Teste 2',
    birth_date_unknown_reason='teste')
criados.append(outro)
print(f'  apagado tinha {numero_do_apagado}, o novo recebeu {outro.record_number}')
if outro.record_number == numero_do_apagado:
    failures.append('o numero de um paciente apagado foi reaproveitado')

print('=== 4. o numero e imutavel ===')
antes_num = outro.record_number
outro.full_name = 'Nome Alterado'
outro.save()
outro.refresh_from_db()
print('  apos salvar de novo:', outro.record_number)
if outro.record_number != antes_num:
    failures.append('o numero mudou ao salvar o paciente de novo')

print('=== 5. busca por numero encontra o paciente ===')
# Paciente ATIVO: a lista filtra arquivados, e buscar por um arquivado
# devolveria vazio corretamente — o teste e que estaria errado.
alvo = (Patient.objects.filter(tenant=tenant_a, status='active')
        .order_by('record_number').first())
for termo in [alvo.record_number, alvo.record_number.lstrip('0')]:
    body = doctor.get(f'/app/patients/?q={termo}').content.decode()
    achou = alvo.full_name in body
    print(f'  busca por "{termo}": {achou}')
    if not achou:
        failures.append(f'busca por numero "{termo}" nao encontrou o paciente')

r = doctor.get(f'/app/patients/autocomplete/?q={alvo.record_number}')
dados = json.loads(r.content)
print('  autocomplete devolve o numero:',
      bool(dados['results']) and 'record_number' in dados['results'][0])
if not dados['results']:
    failures.append('o autocomplete nao acha por numero')

print('=== 6. tela de documentos do paciente ===')
# Endereco preenchido e **montagem**, nao afirmacao: o documento o imprime
# no cabecalho. `seed_demo` nao preenche endereco, entao procurar um e usar
# o resultado dependia de sobra de outra execucao -- num banco recem-semeado
# vinha `None`, e o `create` abaixo estourava com "patient_id nao pode ser
# nulo", apontando para o encontro quando a causa era o paciente.
paciente = Patient.objects.filter(tenant=tenant_a).exclude(street='').first()
if paciente is None:
    paciente = Patient.objects.filter(tenant=tenant_a).order_by('record_number').first()
    if paciente is None:
        raise SystemExit('FALHA: a clinica de demonstracao esta sem pacientes; rode seed_demo.')
    paciente.street, paciente.number = 'Rua das Acácias', '100'
    paciente.district, paciente.city, paciente.state = 'Centro', 'São Paulo', 'SP'
    paciente.save(update_fields=['street', 'number', 'district', 'city', 'state'])
enc = Encounter.objects.filter(tenant=tenant_a, patient=paciente).first()
if enc is None:
    enc = Encounter.objects.create(
        tenant=tenant_a, patient=paciente, physician_membership=doctor_m,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT, chief_complaint='x')
doc = issuance.create_draft(tenant_a, paciente, enc, doctor_m, doctor_m.user_id,
                            MedicalDocumentKind.REPORT, {'report_text': 'MARCADOR DA TELA'})
criados.append(doc)

r = doctor.get(f'/app/documents/patients/{paciente.id}/documentos/')
body = r.content.decode()
print('  HTTP:', r.status_code)
print('  lista o documento:', 'Relatório' in body)
print('  mostra o numero do prontuario:', paciente.record_number in body)
if r.status_code != 200:
    failures.append(f'a tela de documentos devolveu {r.status_code}')
if paciente.record_number not in body:
    failures.append('a tela de documentos nao mostra o numero do prontuario')

print('=== 7. a tela so mostra os documentos DAQUELE paciente ===')
# A pergunta e se **o documento** do outro aparece, e por isso o que se
# procura no corpo e a identidade dele -- o id e o texto que so ele tem.
#
# Antes procurava-se o nome do outro paciente, e isso acusava falso: ha
# homonimos no banco de demonstracao (os roteiros de permissao deixam
# varios "Teste Permissao Secretaria"), entao o nome do outro e, as vezes,
# tambem o nome do paciente da tela -- e ele aparece no cabecalho e na
# trilha de navegacao, como deve.
outro_paciente = Patient.objects.filter(tenant=tenant_a).exclude(id=paciente.id).first()
enc2 = Encounter.objects.filter(tenant=tenant_a, patient=outro_paciente).first()
if enc2 is None:
    enc2 = Encounter.objects.create(
        tenant=tenant_a, patient=outro_paciente, physician_membership=doctor_m,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT, chief_complaint='y')
doc2 = issuance.create_draft(tenant_a, outro_paciente, enc2, doctor_m, doctor_m.user_id,
                             MedicalDocumentKind.REPORT, {'report_text': 'MARCADOR DO OUTRO'})
criados.append(doc2)
body = doctor.get(f'/app/documents/patients/{paciente.id}/documentos/').content.decode()
vazou = str(doc2.id) in body or 'MARCADOR DO OUTRO' in body
print('  aparece o documento do outro paciente:', vazou)
print('  continua mostrando o documento deste:', str(doc.id) in body)
if vazou:
    failures.append('a tela de documentos misturou pacientes')
if str(doc.id) not in body:
    failures.append('a tela de documentos deixou de mostrar o documento do proprio paciente')

print('=== 8. a secretaria nao abre a tela de documentos ===')
code = secretary.get(f'/app/documents/patients/{paciente.id}/documentos/').status_code
print('  HTTP:', code)
if code != 404:
    failures.append(f'a secretaria alcancou os documentos clinicos (HTTP {code})')

print('=== 9. a trilha do novo documento guarda o caminho ===')
body = doctor.get(f'/app/documents/encounters/{enc.id}/medical/new/').content.decode()
tem_paciente = paciente.full_name in body
tem_atendimento = f'/app/clinical/{enc.id}/' in body
tem_volta = f'/app/documents/encounters/{enc.id}/medical/' in body
print('  cita o paciente:', tem_paciente)
print('  liga ao atendimento:', tem_atendimento)
print('  tem volta para a lista:', tem_volta)
for nome, ok in [('paciente', tem_paciente), ('atendimento', tem_atendimento),
                 ('volta', tem_volta)]:
    if not ok:
        failures.append(f'a trilha do novo documento nao guarda o {nome}')

print('=== 10. o numero sai no PDF ===')
import io
from pypdf import PdfReader
from documents.pdf import render_medical_document_pdf

texto = '\n'.join(pg.extract_text() or '' for pg in
                  PdfReader(io.BytesIO(render_medical_document_pdf(doc))).pages)
print('  prontuario impresso:', paciente.record_number in texto)
if paciente.record_number not in texto:
    failures.append('o numero do prontuario nao saiu no PDF')

# Limpeza na ordem inversa das dependencias: documento -> anexo -> paciente.
# As FKs sao PROTECT, entao apagar o paciente primeiro so estoura.
from documents.models import Attachment

docs = [o for o in criados if isinstance(o, MedicalDocument)]
pacientes_novos = [o for o in criados if isinstance(o, Patient)]
for d in docs:
    anexos = [d.pdf_attachment_id, d.signed_pdf_attachment_id]
    MedicalDocument.objects.filter(id=d.id).delete()
    Attachment.objects.filter(id__in=[a for a in anexos if a]).delete()
for p in pacientes_novos:
    Encounter.objects.filter(patient=p).delete()
    Attachment.objects.filter(patient=p).delete()
    Patient.objects.filter(id=p.id).delete()

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: prontuario numerado, documentos por paciente, trilha preservada.')
