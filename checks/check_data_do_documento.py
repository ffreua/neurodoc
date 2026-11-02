"""A data do documento é a da emissão, não a da consulta (2026-11-02).

Até a revisão de 2026-11-02, o PDF imprimia como "Data do documento" a data
do atendimento a que o documento pende. O documento emitido dias depois —
pela Conduta de um atendimento já finalizado, ou o pedido do portal — saía
datado do dia da consulta; em produção havia 9 assim, de 3 a 15 dias antes.

    docker compose exec -T app python manage.py shell < checks/check_data_do_documento.py
"""
import io
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader

from clinical.models import Encounter, EncounterKind, EncounterStatus
from documents import issuance
from documents.models import MedicalDocumentKind
from documents.pdf import render_medical_document_pdf
from documents.pdf.prescription import SIMPLE
from patients.models import Patient, RegistrationStage
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(rotulo)


def texto(pdf):
    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages)


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.get(tenant=tenant, user__email='doctor-a@demo.neurodoc.local')
hoje = timezone.localdate().strftime('%d/%m/%Y')

try:
    with transaction.atomic():
        pac = Patient.objects.create(tenant=tenant, full_name='PACIENTE ROTEIRO DATA DO DOCUMENTO',
                                     registration_stage=RegistrationStage.COMPLETE,
                                     birth_date_unknown_reason='Roteiro de verificação.')
        consulta = timezone.now() - timedelta(days=10)
        enc = Encounter.objects.create(
            tenant=tenant, patient=pac, physician_membership=medico, occurred_at=consulta,
            status=EncounterStatus.IN_PROGRESS, kind=EncounterKind.FREE_TEXT, free_text='Consulta do roteiro.',
        )
        dia_da_consulta = timezone.localtime(consulta).strftime('%d/%m/%Y')
        doc = issuance.create_draft(
            tenant, pac, enc, medico, medico.user_id, MedicalDocumentKind.PRESCRIPTION,
            {'prescription_text': 'Dipirona 500mg, 1 comprimido de 6/6h se dor',
             'special_instructions': '', 'prescription_format': SIMPLE},
        )
        rascunho = texto(render_medical_document_pdf(doc))
        conferir('o rascunho sai com a data de hoje', f'Data do documento: {hoje}' in rascunho)
        issuance.issue_on_paper(doc, medico.user_id)
        doc.refresh_from_db()
        emitido = texto(render_medical_document_pdf(doc))
        conferir('o emitido sai com a data da emissão', f'Data do documento: {hoje}' in emitido)
        conferir('e não com a da consulta de dez dias atrás', f'Data do documento: {dia_da_consulta}' not in emitido)
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Data do documento: tudo confere.')
