"""G6: QR, assinatura no PDF, verificacao publica, receita simples e carbonada."""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter, EncounterStatus
from documents import issuance
from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from documents.pdf import render_medical_document_pdf
from documents.pdf.prescription import SIMPLE, SPECIAL_CONTROL
from patients.models import Patient
from tenancy.models import Membership, Tenant

TENANT = 'demo-clinica-a'
failures = []

tenant = Tenant.objects.get(slug=TENANT)
doctor = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=tenant)
patient = Patient.objects.filter(tenant=tenant, cpf__isnull=False).exclude(street='').first()
if patient is None:
    patient = Patient.objects.filter(tenant=tenant).first()
    patient.street, patient.number = 'Rua das Acácias', '250'
    patient.district, patient.city, patient.state = 'Centro', 'São Paulo', 'SP'
    patient.postal_code = '01310100'
    patient.save()

encounter = Encounter.objects.filter(tenant=tenant, patient=patient).first()
if encounter is None:
    encounter = Encounter.objects.create(
        tenant=tenant, patient=patient, physician_membership=doctor,
        occurred_at=timezone.now(), status=EncounterStatus.DRAFT,
        chief_complaint='teste G6',
    )

created = []


def pdf_text(data):
    """Texto extraido do PDF, para conferir o que foi realmente impresso."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return '\n'.join(page.extract_text() or '' for page in reader.pages), len(reader.pages)


print('=== 1. receita simples: uma via, QR e codigo ===')
doc = issuance.create_draft(
    tenant, patient, encounter, doctor, doctor.user_id,
    MedicalDocumentKind.PRESCRIPTION,
    {'prescription_text': 'Dipirona 500mg, 1 comprimido de 6/6h se dor',
     'special_instructions': '', 'prescription_format': SIMPLE},
)
created.append(doc)
print('  token:', doc.validation_token, '| tamanho:', len(doc.validation_token))
if not doc.validation_token or len(doc.validation_token) != 16:
    failures.append('token de validacao ausente ou com tamanho errado')

data = render_medical_document_pdf(doc)
texto, paginas = pdf_text(data)
print('  paginas:', paginas)
print('  tem URL de verificacao:', '/verificar/' in texto)
print('  tem codigo formatado:', doc.validation_token[:4] in texto)
if paginas != 1:
    failures.append(f'receita simples saiu com {paginas} paginas')
if '/verificar/' not in texto:
    failures.append('o PDF nao traz a URL de verificacao')

print('=== 2. rascunho diz que e rascunho ===')
print('  tarja de rascunho presente:', 'RASCUNHO' in texto)
if 'RASCUNHO' not in texto:
    failures.append('o rascunho nao esta marcado como tal')

print('=== 3. o PDF EMITIDO nao pode dizer que e rascunho ===')
# Simula o que a emissao faz: numero, data, estado, e so entao desenhar.
doc.document_number = 'REC-2026-000999'
doc.issued_at = timezone.now()
doc.status = MedicalDocumentStatus.ISSUED
doc.signature_metadata = {'content_sha256': 'a' * 64}
final = render_medical_document_pdf(doc)
texto_final, _ = pdf_text(final)
print('  tarja de rascunho:', 'RASCUNHO' in texto_final)
print('  numero impresso:', 'REC-2026-000999' in texto_final)
print('  assinatura declarada:', 'Assinado digitalmente' in texto_final)
if 'RASCUNHO' in texto_final:
    failures.append('o PDF emitido ainda traz a tarja de rascunho')
if 'REC-2026-000999' not in texto_final:
    failures.append('o numero do documento nao foi impresso')
if 'Assinado digitalmente' not in texto_final:
    failures.append('o PDF emitido nao declara a assinatura')
doc.status = MedicalDocumentStatus.DRAFT
doc.document_number = ''
doc.save(update_fields=['status', 'document_number'])

print('=== 4. receita de controle especial: duas vias ===')
doc2 = issuance.create_draft(
    tenant, patient, encounter, doctor, doctor.user_id,
    MedicalDocumentKind.PRESCRIPTION,
    {'prescription_text': 'Clonazepam 2mg, 1 comprimido a noite',
     'special_instructions': '', 'prescription_format': SPECIAL_CONTROL},
)
created.append(doc2)
data2 = render_medical_document_pdf(doc2)
texto2, paginas2 = pdf_text(data2)
print('  paginas:', paginas2)
print('  1a via rotulada:', 'RETEN' in texto2.upper())
print('  2a via rotulada:', 'ORIENTA' in texto2.upper())
print('  endereco do paciente:', 'Endere' in texto2)
print('  cita a Portaria 344:', '344' in texto2)
if paginas2 != 2:
    failures.append(f'controle especial saiu com {paginas2} pagina(s), esperava 2')
if 'RETEN' not in texto2.upper() or 'ORIENTA' not in texto2.upper():
    failures.append('as vias nao estao rotuladas')
if 'Endere' not in texto2:
    failures.append('o endereco do paciente nao saiu na receita de controle especial')

print('=== 5. controle especial sem endereco e recusado ===')
sem_endereco = Patient.objects.create(
    tenant=tenant, full_name='Paciente Sem Endereco G6',
    birth_date=patient.birth_date,
)
try:
    issuance.create_draft(
        tenant, sem_endereco, encounter, doctor, doctor.user_id,
        MedicalDocumentKind.PRESCRIPTION,
        {'prescription_text': 'x', 'special_instructions': '',
         'prescription_format': SPECIAL_CONTROL},
    )
    failures.append('aceitou controle especial sem endereco do paciente')
    print('  ACEITOU (nao deveria)')
except ValueError as exc:
    print('  ->', str(exc)[:90])

print('=== 6. outros tipos tambem levam QR ===')
for kind, campos in [
    (MedicalDocumentKind.REPORT, {'report_text': 'Relatorio de teste'}),
    (MedicalDocumentKind.REQUEST, {'requested_procedure': 'RM de cranio',
                                   'justification': 'Cefaleia'}),
    (MedicalDocumentKind.REFERRAL, {'referral_specialty': 'Neurocirurgia',
                                    'reason': 'Avaliacao'}),
]:
    d = issuance.create_draft(tenant, patient, encounter, doctor, doctor.user_id, kind, campos)
    created.append(d)
    t, _ = pdf_text(render_medical_document_pdf(d))
    tem_qr = '/verificar/' in t
    print(f'  {kind:14} token={bool(d.validation_token)} url_no_pdf={tem_qr}')
    if not d.validation_token or not tem_qr:
        failures.append(f'{kind} saiu sem codigo de verificacao')

print('=== 7. pagina publica de verificacao ===')
anon = Client()
r = anon.get(f'/verificar/{doc.validation_token}/')
body = r.content.decode()
print('  HTTP:', r.status_code)
print('  mostra que NAO foi emitido:', 'NÃO foi emitido' in body)
print('  nome mascarado:', patient.full_name not in body)
print('  conteudo clinico ausente:', 'Dipirona' not in body)
if r.status_code != 200:
    failures.append(f'a pagina de verificacao devolveu {r.status_code}')
if patient.full_name in body:
    failures.append('a pagina publica mostrou o nome completo do paciente')
if 'Dipirona' in body:
    failures.append('a pagina publica vazou conteudo clinico')
if 'NÃO foi emitido' not in body:
    failures.append('a pagina nao avisou que o documento e um rascunho')

print('=== 8. codigo inexistente ===')
r = anon.get('/verificar/FFFFFFFFFFFFFFFF/')
print('  HTTP:', r.status_code, '| avisa:', 'Nenhum documento' in r.content.decode())
if r.status_code != 404:
    failures.append(f'codigo inexistente devolveu {r.status_code}')

print('=== 9. verificacao por digitacao, com formatacao ===')
from documents.pdf.common import format_validation_code

formatado = format_validation_code(doc.validation_token)
r = anon.post('/verificar/', {'codigo': formatado})
print('  codigo digitado:', formatado, '| HTTP:', r.status_code)
if r.status_code != 200:
    failures.append('o codigo com hifens nao foi aceito na digitacao')

print('=== 10. documento emitido aparece como valido ===')
doc2.status = MedicalDocumentStatus.ISSUED
doc2.document_number = 'REC-2026-000998'
doc2.issued_at = timezone.now()
doc2.signature_metadata = {'content_sha256': 'b' * 64}
doc2.save()
r = anon.get(f'/verificar/{doc2.validation_token}/')
body = r.content.decode()
print('  localizado e emitido:', 'Documento localizado e emitido' in body)
print('  numero:', 'REC-2026-000998' in body)
print('  hash:', 'b' * 64 in body)
if 'Documento localizado e emitido' not in body:
    failures.append('documento emitido nao apareceu como valido')

# limpeza
for d in created:
    MedicalDocument.objects.filter(id=d.id).delete()
sem_endereco.delete()

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: G6 completo.')
