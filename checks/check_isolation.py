"""O documento de um paciente aparece so no prontuario dele?

A pergunta e sobre isolamento real, nao sobre a tela. Testa por consulta e
por rota HTTP, entre pacientes da MESMA clinica — que e o caso dificil, ja
que o escopo por inquilino nao ajuda.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django.utils import timezone

from accounts.models import User
from clinical.models import Encounter, EncounterStatus
from documents import issuance
from documents.models import MedicalDocument, MedicalDocumentKind
from patients.models import Patient
from tenancy.models import Membership, Tenant

failures = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
doctor_a = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=tenant_a)
doctor_b = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=tenant_b)

pacientes = list(Patient.objects.filter(tenant=tenant_a)[:2])
p1, p2 = pacientes[0], pacientes[1]
pb = Patient.objects.filter(tenant=tenant_b).first()

criados = []


def encontro(tenant, paciente, medico):
    e = Encounter.objects.filter(tenant=tenant, patient=paciente).first()
    if e is None:
        e = Encounter.objects.create(
            tenant=tenant, patient=paciente, physician_membership=medico,
            occurred_at=timezone.now(), status=EncounterStatus.DRAFT, chief_complaint='iso')
    return e


e1, e2 = encontro(tenant_a, p1, doctor_a), encontro(tenant_a, p2, doctor_a)
eb = encontro(tenant_b, pb, doctor_b)

print('=== documentos criados ===')
d1 = issuance.create_draft(tenant_a, p1, e1, doctor_a, doctor_a.user_id,
                           MedicalDocumentKind.REPORT, {'report_text': 'SEGREDO DO PACIENTE 1'})
d2 = issuance.create_draft(tenant_a, p2, e2, doctor_a, doctor_a.user_id,
                           MedicalDocumentKind.REPORT, {'report_text': 'SEGREDO DO PACIENTE 2'})
db = issuance.create_draft(tenant_b, pb, eb, doctor_b, doctor_b.user_id,
                           MedicalDocumentKind.REPORT, {'report_text': 'SEGREDO DA CLINICA B'})
criados += [d1, d2, db]
print(f'  {p1.full_name[:28]:30} -> {d1.id}')
print(f'  {p2.full_name[:28]:30} -> {d2.id}')
print(f'  {pb.full_name[:28]:30} (clinica B) -> {db.id}')

print('=== 1. vinculo no banco ===')
for doc, dono in [(d1, p1), (d2, p2), (db, pb)]:
    ok = doc.patient_id == dono.id and doc.encounter.patient_id == dono.id
    print(f'  {doc.id} paciente correto: {ok}')
    if not ok:
        failures.append(f'documento {doc.id} nao esta ligado ao paciente certo')

print('=== 2. a consulta por paciente nao mistura ===')
do_p1 = set(MedicalDocument.objects.filter(patient=p1).values_list('id', flat=True))
print('  documentos do paciente 1 incluem o do paciente 2:', d2.id in do_p1)
if d2.id in do_p1:
    failures.append('a consulta por paciente trouxe documento de outro paciente')

print('=== 3. a lista por atendimento nao mistura ===')
c = Client()
c.force_login(User.objects.get(email='doctor-a@demo.neurodoc.local'))
s = c.session
s['tenant_id'] = str(tenant_a.id)
s.save()

body1 = c.get(f'/app/documents/encounters/{e1.id}/medical/').content.decode()
print('  atendimento do paciente 1 mostra segredo do 2:', 'SEGREDO DO PACIENTE 2' in body1)
print('  mostra o nome do paciente 2:', p2.full_name in body1)
if 'SEGREDO DO PACIENTE 2' in body1:
    failures.append('a lista do atendimento vazou documento de outro paciente')

print('=== 4. rota direta ao documento de outro paciente ===')
r = c.get(f'/app/documents/medical/{d2.id}/')
print('  documento do paciente 2, mesma clinica -> HTTP', r.status_code, '(esperado 200: mesma clinica)')

r = c.get(f'/app/documents/medical/{db.id}/')
print('  documento da CLINICA B -> HTTP', r.status_code, '(esperado 404)')
if r.status_code != 404:
    failures.append(f'documento de outra clinica acessivel (HTTP {r.status_code})')

print('=== 5. o PDF do documento traz o paciente certo ===')
from documents.pdf import render_medical_document_pdf
import io
from pypdf import PdfReader

for doc, dono, outro in [(d1, p1, p2), (d2, p2, p1)]:
    texto = '\n'.join(pg.extract_text() or '' for pg in
                      PdfReader(io.BytesIO(render_medical_document_pdf(doc))).pages)
    tem_dono = dono.full_name.split()[0] in texto
    tem_outro = outro.full_name.split()[0] in texto and outro.full_name != dono.full_name
    print(f'  PDF de {dono.full_name[:24]:26} dono={tem_dono} outro={tem_outro}')
    if not tem_dono:
        failures.append(f'o PDF de {dono.full_name} nao traz o nome dele')

print('=== 6. a busca rapida do topo (Ctrl+K) nao atravessa a clinica ===')
#
# A busca abre em qualquer tela e responde em JSON, o que a torna a porta
# mais larga do produto: um `q` digitado por quem atende, e uma lista de
# pacientes de volta. Se houver um caminho para ela devolver paciente de
# outra clinica, e por ele que um vazamento sairia -- e sairia sem deixar
# tela nenhuma como pista.
import json as _json

from patients.models import PatientStatus as _PS

# `c` ja esta na clinica A (secao 3). O segundo cliente entra na B com a
# MESMA conta: doctor-a tem vinculo nas duas, e usar a mesma pessoa deixa
# claro que o que separa as duas buscas e o inquilino da sessao, nao o
# usuario.
_cb = Client()
_cb.force_login(User.objects.get(email='doctor-a@demo.neurodoc.local'))
_sb = _cb.session
_sb['tenant_id'] = str(tenant_b.id)
_sb.save()

def _buscar(cliente, termo):
    r = cliente.get(f'/app/patients/busca-rapida/?q={termo}')
    if r.status_code != 200:
        return None, r.status_code
    return [x['nome'] for x in _json.loads(r.content)['resultados']], 200

# O nome do paciente da clinica B, procurado por quem esta na clinica A.
_primeiro_nome = pb.full_name.split()[0]
_achados, _status = _buscar(c, _primeiro_nome)
print(f'  clinica A busca {_primeiro_nome!r} -> HTTP {_status} {_achados}')
if _achados is None or pb.full_name in _achados:
    failures.append('a busca rapida devolveu paciente de outra clinica pelo nome')

# E pelo CPF, que e busca exata: se o filtro por inquilino falhasse, este
# seria o caminho mais direto de todos.
if pb.cpf:
    _achados, _status = _buscar(c, pb.cpf)
    print(f'  clinica A busca o CPF do paciente da B -> HTTP {_status} {_achados}')
    if _achados is None or pb.full_name in _achados:
        failures.append('a busca rapida devolveu paciente de outra clinica pelo CPF')

# A mesma busca, na clinica dona, precisa achar -- senao o teste acima
# passaria por a busca simplesmente nao funcionar.
_achados, _status = _buscar(_cb, _primeiro_nome)
print(f'  clinica B busca o proprio paciente -> HTTP {_status} {_achados}')
if not _achados or pb.full_name not in _achados:
    failures.append('a busca rapida nao achou o paciente na propria clinica')

# CPF sai mascarado: a caixa abre por cima de qualquer tela, inclusive a do
# balcao com gente do outro lado.
_r = _cb.get(f'/app/patients/busca-rapida/?q={_primeiro_nome}')
_resultados = _json.loads(_r.content)['resultados']
if pb.cpf and _resultados:
    _mascara = _resultados[0]['cpf_mascarado']
    print(f'  CPF devolvido: {_mascara!r} (inteiro seria {pb.cpf!r})')
    if pb.cpf in _mascara or _mascara.count('*') < 5:
        failures.append('a busca rapida devolveu o CPF sem mascara')

# Paciente arquivado nao entra: a busca do topo serve ao atendimento do dia.
_arquivado = Patient.objects.filter(tenant=tenant_b, status=_PS.ACTIVE).exclude(id=pb.id).first()
if _arquivado is not None:
    _antes = _arquivado.status
    Patient.objects.filter(id=_arquivado.id).update(status=_PS.ARCHIVED)
    try:
        _achados, _ = _buscar(_cb, _arquivado.full_name.split()[0])
        print(f'  arquivado aparece na busca: {_arquivado.full_name in (_achados or [])}')
        if _arquivado.full_name in (_achados or []):
            failures.append('a busca rapida trouxe paciente arquivado')
    finally:
        Patient.objects.filter(id=_arquivado.id).update(status=_antes)

def _remover_anexos_dos_documentos(ids):
    """Tira do banco e do disco os PDFs dos documentos que o roteiro criou.

    Apagar so o `MedicalDocument` deixava o `Attachment` do rascunho (e o
    do assinado, quando havia) orfao no banco e o arquivo no volume de
    midia. Somados os cinco roteiros que emitem documento, eram vinte e
    dois anexos por rodada acumulando na clinica de demonstracao.

    A segunda varredura, por PDF **sem dono**, existe porque nem todo
    documento chega aqui pela lista: um que o proprio roteiro ja apagou,
    ou que foi substituido no meio do caminho, sai da lista e levaria o
    anexo junto para o esquecimento. O nome do arquivo de documento carrega
    o id dele (`<tipo>_<uuid>_draft.pdf`), e um desses que nenhum
    `MedicalDocument` reivindica nao e de ninguem.
    """
    import re
    from pathlib import Path

    from documents.models import Attachment, MedicalDocument

    anexos = []
    for atual in MedicalDocument.objects.filter(id__in=ids).values(
        'pdf_attachment_id', 'signed_pdf_attachment_id',
    ):
        anexos += [v for v in atual.values() if v]
    MedicalDocument.objects.filter(id__in=ids).delete()

    padrao = re.compile(r'^[a-z_]+_[0-9a-f-]{36}_(draft|signed|papel)\.pdf$')
    com_dono = set(
        MedicalDocument.objects.values_list('pdf_attachment_id', flat=True)
    ) | set(
        MedicalDocument.objects.values_list('signed_pdf_attachment_id', flat=True)
    )
    for att in Attachment.objects.exclude(id__in=[i for i in com_dono if i]):
        if padrao.match(att.original_name or ''):
            anexos.append(att.id)

    if not anexos:
        return 0
    for att in Attachment.objects.filter(id__in=anexos):
        if att.storage_key:
            Path(att.storage_key).unlink(missing_ok=True)
    apagados, _ = Attachment.objects.filter(id__in=anexos).delete()
    return apagados


print('anexos dos documentos do roteiro removidos:',
      _remover_anexos_dos_documentos([d.id for d in criados]))

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: cada documento fica no prontuario do seu paciente.')
