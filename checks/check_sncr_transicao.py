"""Transição do SNCR: a RCE eletrônica sem numeração para de sair em 31/10/2026.

Regra transitória (documents/sncr_transicao.py), até a integração com o
SNCR entrar em produção. Tenta quebrar. As perguntas são:

- em 30/10 a RCE ainda pode ser assinada digitalmente, e em 31/10 não?
- a data é a do dia de Brasília? às 23h30 de 30/10 em Brasília o UTC já
  é 31/10, e a receita ainda precisa poder ser assinada;
- em 31/10 a assinatura é recusada **no servidor**, com a mensagem em
  português, sem gastar número, sem mudar o estado, e com a recusa na
  trilha?
- a receita simples continua assinável em 31/10 (ela só recebe aviso)?
- a emissão em papel da RCE continua funcionando em 31/10?
- a tela do documento esconde o "Assinar e emitir" da RCE em 31/10, mostra
  o aviso vermelho, e antes disso mostra o aviso amarelo?
- o formulário de nova receita mostra os dois avisos?
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
from documents import issuance, sncr_transicao
from documents.models import Attachment, MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.models import Patient
from tenancy.models import Membership, Tenant

falhas = []
SP = ZoneInfo('America/Sao_Paulo')


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + detalhe) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


def instante(ano, mes, dia, hora, minuto=0):
    """Um instante de Brasília, devolvido em UTC como `timezone.now()`."""
    return datetime(ano, mes, dia, hora, minuto, tzinfo=SP).astimezone(ZoneInfo('UTC'))


def no_dia(momento):
    return mock.patch('django.utils.timezone.now', return_value=momento)


def tela_no_dia(dia):
    """Só a data que a regra consulta, e não o relógio do processo.

    Fixar `timezone.now` numa requisição HTTP faz a sessão de login parecer
    vencida (ela expira pelo mesmo relógio), e a página volta para o login
    — a primeira versão deste roteiro media isso e reprovava a tela.
    """
    from types import SimpleNamespace

    return mock.patch('documents.sncr_transicao.timezone', SimpleNamespace(localdate=lambda: dia))


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


print('=== 1. a data da regra ===')
rce = receita('special_control')
simples = receita('simple')
conferir('30/10 às 12h: RCE ainda assinável',
         not sncr_transicao.assinatura_digital_bloqueada(rce, hoje=instante(2026, 10, 30, 12).astimezone(SP).date()))
with no_dia(instante(2026, 10, 30, 23, 30)):
    conferir('30/10 às 23h30 em Brasília (31/10 em UTC): ainda assinável',
             not sncr_transicao.assinatura_digital_bloqueada(rce))
with no_dia(instante(2026, 10, 31, 0, 1)):
    conferir('31/10 à 0h01: RCE barrada', sncr_transicao.assinatura_digital_bloqueada(rce))
    conferir('31/10: receita simples não é barrada', not sncr_transicao.assinatura_digital_bloqueada(simples))

print('=== 2. a recusa no servidor, em 31/10 ===')
eventos_antes = AuditEvent.objects.filter(
    action='documents.medicaldocument_sign_failed', object_id=rce.id,
).count()
with no_dia(instante(2026, 10, 31, 10)):
    try:
        issuance.sign_and_issue(rce, None, vinculo)
        conferir('a assinatura da RCE é recusada', False, 'assinou')
    except issuance.NotReadyToSign as exc:
        conferir('a assinatura da RCE é recusada com NotReadyToSign', True)
        conferir('a mensagem é a da transição, em português', 'SNCR' in str(exc) and 'carimbar' in str(exc))
rce.refresh_from_db()
conferir('o estado continua "pronto para assinar"', rce.status == MedicalDocumentStatus.READY_TO_SIGN, rce.status)
conferir('nenhum número foi gasto', rce.document_number == '', rce.document_number)
evento = AuditEvent.objects.filter(
    action='documents.medicaldocument_sign_failed', object_id=rce.id,
).order_by('-created_at').first()
conferir('a recusa entrou na trilha',
         AuditEvent.objects.filter(action='documents.medicaldocument_sign_failed', object_id=rce.id).count()
         == eventos_antes + 1)
conferir('com o motivo da transição',
         evento is not None and (evento.integrity_metadata or {}).get('reason') == sncr_transicao.MOTIVO_AUDITORIA)

print('=== 3. a tela do documento ===')
c = entrar()
with tela_no_dia(instante(2026, 10, 31, 10).astimezone(SP).date()):
    html = c.get(f'/app/documents/medical/{rce.id}/').content.decode()
    conferir('31/10: sem o botão "Assinar e emitir" na RCE', 'Assinar e emitir' not in html)
    conferir('31/10: sem o pedido de sessão de assinatura na RCE', 'Nenhuma sessão de assinatura ativa' not in html)
    conferir('31/10: o aviso vermelho da RCE', 'data-nd-aviso-sncr' in html and 'alert-danger' in html
             and 'emissão só em papel' in html)
    conferir('31/10: "Emitir para assinar e carimbar" continua lá', 'Emitir para assinar e carimbar' in html)
    html_s = c.get(f'/app/documents/medical/{simples.id}/').content.decode()
    conferir('31/10: a receita simples segue o caminho normal', 'Nenhuma sessão de assinatura ativa' in html_s)
    conferir('31/10: a receita simples recebe o aviso da retenção', 'agonistas de GLP-1' in html_s)
with tela_no_dia(instante(2026, 10, 25, 10).astimezone(SP).date()):
    html = c.get(f'/app/documents/medical/{rce.id}/').content.decode()
    conferir('25/10: a RCE segue o caminho normal', 'Nenhuma sessão de assinatura ativa' in html)
    conferir('25/10: o aviso amarelo anuncia a mudança', 'mudança em 31/10/2026' in html)

print('=== 4. o formulário de nova receita ===')
with tela_no_dia(instante(2026, 10, 25, 10).astimezone(SP).date()):
    html = c.get(f'/app/documents/patients/{paciente.id}/medical/new/').content.decode()
conferir('o formulário mostra o aviso da RCE', 'Receita de Controle Especial' in html and 'data-nd-aviso-sncr' in html)
conferir('o formulário mostra o aviso da retenção', 'agonistas de GLP-1' in html)

print('=== 5. o papel continua ===')
with no_dia(instante(2026, 10, 31, 10)):
    papel = issuance.issue_on_paper(rce, medico.id)
papel.refresh_from_db()
conferir('a RCE sai em papel em 31/10', papel.status == MedicalDocumentStatus.ISSUED_ON_PAPER, papel.status)
conferir('com número', bool(papel.document_number))

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
print('OK: a RCE eletrônica para em 31/10 (dia de Brasília), recusada no servidor e na tela,')
print('    sem gastar número; o papel continua; a receita simples só recebe o aviso.')
