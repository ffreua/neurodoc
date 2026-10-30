"""A RCE impressa não é assinada digitalmente desde 31/10/2026 — e os avisos saíram.

Regra permanente em `documents/rce_impressa.py` (era a transitória
`sncr_transicao`, da 1.21.1, até a integração com o SNCR entrar em
produção em 2026-10-29). Tenta quebrar. As perguntas são:

- em 30/10 a RCE do leiaute da clínica ainda pode ser assinada
  digitalmente, e em 31/10 não? A data é a do dia de Brasília — às 23h30
  de 30/10 o UTC já é 31/10, e a receita ainda precisa poder ser assinada?
- em 31/10 a assinatura é recusada **no servidor**, em português, sem
  gastar número, sem mudar o estado, e com a recusa na trilha (com o mesmo
  motivo de antes, para a série não se partir)?
- a receita simples continua assinável?
- a tela do documento esconde o "Assinar e emitir" da RCE impressa e diz
  por quê numa frase, sem caixa de aviso?
- **os avisos transitórios sumiram**: nem o formulário nem a tela do
  documento trazem `data-nd-aviso-sncr`, "mudança em 31/10" ou o aviso do
  GLP-1 na receita simples?
- a emissão em papel da RCE continua funcionando?
"""
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from audit.models import AuditEvent
from documents import issuance, rce_impressa
from documents.models import Attachment, MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.models import Patient
from tenancy.models import Membership, Tenant

falhas = []
SP = ZoneInfo('America/Sao_Paulo')


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


def instante(ano, mes, dia, hora, minuto=0):
    """Um instante de Brasília, devolvido em UTC como `timezone.now()`."""
    return datetime(ano, mes, dia, hora, minuto, tzinfo=SP).astimezone(ZoneInfo('UTC'))


def no_dia(momento):
    return mock.patch('django.utils.timezone.now', return_value=momento)


def tela_no_dia(dia):
    """Só a data que a regra consulta, e não o relógio do processo: fixar
    `timezone.now` numa requisição faria a sessão de login parecer vencida."""
    from types import SimpleNamespace

    return mock.patch('documents.rce_impressa.timezone', SimpleNamespace(localdate=lambda: dia))


AVISOS_QUE_SAIRAM = ('data-nd-aviso-sncr', 'mudança em 31/10/2026', 'agonistas de GLP-1',
                     'emissão só em papel', 'integração do NeuroDoc com o SNCR')

tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant, user=medico)
paciente = Patient.objects.filter(tenant=tenant).exclude(street='').exclude(city='').first()
if paciente is None:
    paciente = Patient.objects.filter(tenant=tenant).first()
    paciente.street, paciente.city, paciente.state = 'Rua das Acácias, 100', 'São Paulo', 'SP'
    paciente.save(update_fields=['street', 'city', 'state'])
criados = []


def receita(formato):
    d = issuance.create_draft(
        tenant, paciente, None, vinculo, medico.id, MedicalDocumentKind.PRESCRIPTION,
        {'prescription_text': 'Clonazepam 2 mg — 1 comprimido à noite', 'prescription_format': formato},
    )
    criados.append(d)
    issuance.mark_reviewed(d, medico.id)
    d.refresh_from_db()
    return d


def entrar():
    c = Client()
    c.force_login(medico)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


try:
    print('=== 1. a data da regra ===')
    rce = receita('special_control')
    simples = receita('simple')
    conferir('30/10 às 12h: RCE ainda assinável',
             not rce_impressa.assinatura_digital_bloqueada(rce, hoje=instante(2026, 10, 30, 12).astimezone(SP).date()))
    with no_dia(instante(2026, 10, 30, 23, 30)):
        conferir('30/10 às 23h30 em Brasília (31/10 em UTC): ainda assinável',
                 not rce_impressa.assinatura_digital_bloqueada(rce))
    with no_dia(instante(2026, 10, 31, 0, 1)):
        conferir('31/10 à 0h01: RCE impressa barrada', rce_impressa.assinatura_digital_bloqueada(rce))
        conferir('31/10: receita simples não é barrada', not rce_impressa.assinatura_digital_bloqueada(simples))

    print('=== 2. a recusa no servidor ===')
    antes = AuditEvent.objects.filter(action='documents.medicaldocument_sign_failed', object_id=rce.id).count()
    with no_dia(instante(2026, 10, 31, 10)):
        try:
            issuance.sign_and_issue(rce, None, vinculo)
            conferir('a assinatura da RCE impressa é recusada', False, 'assinou')
        except issuance.NotReadyToSign as exc:
            conferir('a assinatura da RCE impressa é recusada com NotReadyToSign', True)
            conferir('a mensagem em português aponta o papel', 'SNCR' in str(exc) and 'carimbar' in str(exc))
    rce.refresh_from_db()
    conferir('o estado continua "pronto para assinar"', rce.status == MedicalDocumentStatus.READY_TO_SIGN, rce.status)
    conferir('nenhum número foi gasto', rce.document_number == '', rce.document_number)
    evento = AuditEvent.objects.filter(
        action='documents.medicaldocument_sign_failed', object_id=rce.id,
    ).order_by('-created_at').first()
    conferir('a recusa entrou na trilha',
             AuditEvent.objects.filter(action='documents.medicaldocument_sign_failed', object_id=rce.id).count()
             == antes + 1)
    conferir('com o motivo de sempre', evento is not None
             and (evento.integrity_metadata or {}).get('reason') == rce_impressa.MOTIVO_AUDITORIA)

    print('=== 3. a tela do documento ===')
    c = entrar()
    with tela_no_dia(instante(2026, 10, 31, 10).astimezone(SP).date()):
        html = c.get(f'/app/documents/medical/{rce.id}/').content.decode()
        conferir('sem o botão "Assinar e emitir" na RCE impressa', 'Assinar e emitir' not in html)
        conferir('uma frase diz por quê, sem caixa de aviso', 'data-nd-rce-impressa' in html)
        conferir('"Emitir para assinar e carimbar" continua lá', 'Emitir para assinar e carimbar' in html)
        sobra = [a for a in AVISOS_QUE_SAIRAM if a in html]
        conferir('nenhum aviso transitório na RCE', not sobra, sobra)
        html_s = c.get(f'/app/documents/medical/{simples.id}/').content.decode()
        conferir('a receita simples segue o caminho normal', 'Nenhuma sessão de assinatura ativa' in html_s)
        sobra = [a for a in AVISOS_QUE_SAIRAM if a in html_s]
        conferir('nenhum aviso transitório na receita simples', not sobra, sobra)

    print('=== 4. o formulário de nova receita ===')
    html = c.get(f'/app/documents/patients/{paciente.id}/medical/new/').content.decode()
    sobra = [a for a in AVISOS_QUE_SAIRAM if a in html]
    conferir('o formulário não traz os avisos transitórios', not sobra, sobra)

    print('=== 5. o papel continua ===')
    with no_dia(instante(2026, 10, 31, 10)):
        papel = issuance.issue_on_paper(rce, medico.id)
    papel.refresh_from_db()
    conferir('a RCE sai em papel em 31/10', papel.status == MedicalDocumentStatus.ISSUED_ON_PAPER, papel.status)
    conferir('com número', bool(papel.document_number))
finally:
    print('=== limpeza ===')
    anexos = []
    for d in MedicalDocument.objects.filter(id__in=[d.id for d in criados]).values(
        'pdf_attachment_id', 'signed_pdf_attachment_id',
    ):
        anexos += [v for v in d.values() if v]
    MedicalDocument.objects.filter(id__in=[d.id for d in criados]).delete()
    from pathlib import Path

    for att in Attachment.objects.filter(id__in=anexos):
        if att.storage_key:
            Path(att.storage_key).unlink(missing_ok=True)
    Attachment.objects.filter(id__in=anexos).delete()
    print(f'  {len(criados)} documento(s) removido(s)')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: a RCE impressa não é assinada digitalmente desde 31/10 (dia de Brasília), recusada no')
print('    servidor e na tela, sem gastar número; o papel continua; os avisos transitórios saíram.')
