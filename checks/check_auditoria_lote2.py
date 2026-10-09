"""Lote 2 da auditoria independente de 2026-10-09 (NeuroDoc 1.12.1).

Os nove achados de risco menor, cada um pelo caminho que o quebrava.
Detalhe em `docs/homologation/auditoria-1.12.1.md`.

1. ND-1121-004 -- a IA confere o papel clinico, e nao so o vinculo;
2. ND-1121-014 -- a copia velha de uma consulta nao desfaz o cancelamento;
3. ND-1121-006 -- a confirmacao do SMS pergunta com a chave de quem enviou;
4. ND-1121-007 -- "ERRO" com HTTP 200 nao vira entrega aceita;
5. ND-1121-009 -- exportacao vencida nao baixa, com ou sem limpeza;
6. ND-1121-011 -- a mesma exportacao duas vezes nao vira falha;
7. ND-1121-012 -- a retomada da IA nao adia o proprio prazo;
8. ND-1121-013 -- descartar evolucao em texto livre pede motivo;
9. ND-1121-015 -- falha de assinatura fica na trilha, e o documento
   continua pronto para assinar.
"""
import os
import secrets
import uuid
from datetime import timedelta

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from patients.models import Patient, RegistrationStage
from tenancy.context import AccessContext
from tenancy.models import Membership, Tenant

failures = []
SUFIXO = secrets.token_hex(3)


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


def contexto(membro):
    return AccessContext(user_id=membro.user_id, tenant_id=membro.tenant_id, membership_id=membro.id,
                         permissions=frozenset(), request_id=uuid.uuid4())


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.get(tenant=tenant, user__email='doctor-a@demo.neurodoc.local')
plano_antes, papeis_antes = tenant.plan, list(medico.roles)
criados = {'pacientes': [], 'consultas': [], 'exportacoes': [], 'jobs': [], 'documentos': [],
           'entregas': [], 'atendimentos': []}

try:
    paciente = Patient.objects.create(
        tenant=tenant, full_name=f'PACIENTE DO LOTE DOIS {SUFIXO}',
        registration_stage=RegistrationStage.COMPLETE,
    )
    criados['pacientes'].append(paciente.id)

    print('=== 1. ND-1121-004: a IA confere o papel clinico ===')
    from ai.context import AIAuthorizationDenied, build_ai_authorization

    Tenant.objects.filter(id=tenant.id).update(plan='complete')

    def autoriza(ctx):
        try:
            build_ai_authorization(ctx, paciente.id)
            return True
        except AIAuthorizationDenied:
            return False

    confere(autoriza(contexto(medico)), 'medica com papel e plano: autorizada -- controle positivo')
    Membership.objects.filter(id=medico.id).update(roles=['secretary'])
    confere(not autoriza(contexto(medico)),
            'o mesmo vinculo, agora so secretaria: recusado antes do provedor')
    Membership.objects.filter(id=medico.id).update(roles=papeis_antes)
    outro = contexto(medico)
    outro = AccessContext(user_id=uuid.uuid4(), tenant_id=outro.tenant_id,
                          membership_id=outro.membership_id, permissions=frozenset(),
                          request_id=uuid.uuid4())
    confere(not autoriza(outro), 'vinculo de outra pessoa no contexto: recusado')

    print('=== 2. ND-1121-014: a copia velha nao desfaz o cancelamento ===')
    from scheduling import services as agenda
    from scheduling.models import Appointment, AppointmentStatus

    inicio = timezone.now() + timedelta(days=3650, hours=secrets.randbelow(200))
    consulta = Appointment.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        starts_at=inicio, ends_at=inicio + timedelta(minutes=30),
        occupied_range=(inicio, inicio + timedelta(minutes=30)),
        status=AppointmentStatus.SCHEDULED, type='first_visit',
    )
    criados['consultas'].append(consulta.id)
    copia_velha = Appointment.objects.get(id=consulta.id)
    agenda.cancel_appointment(Appointment.objects.get(id=consulta.id), medico.user_id, reason='motivo do roteiro')
    try:
        agenda.reschedule_appointment(
            contexto(medico), copia_velha, inicio + timedelta(days=1),
            inicio + timedelta(days=1, minutes=30), medico.user_id,
        )
        recusou = False
    except agenda.SchedulingError:
        recusou = True
    consulta.refresh_from_db()
    confere(recusou, 'remarcar com a copia velha e recusado')
    confere(consulta.status == AppointmentStatus.CANCELLED, 'a consulta continua cancelada', consulta.status)
    confere(consulta.cancellation_reason == 'motivo do roteiro', 'e o motivo continua la')
    try:
        agenda.transition_appointment(copia_velha, AppointmentStatus.CONFIRMED, medico.user_id)
        confirmou = True
    except agenda.SchedulingError:
        confirmou = False
    consulta.refresh_from_db()
    confere(not confirmou and consulta.status == AppointmentStatus.CANCELLED,
            'confirmar pela copia velha tambem nao ressuscita a consulta')

    viva = Appointment.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        starts_at=inicio + timedelta(days=5), ends_at=inicio + timedelta(days=5, minutes=30),
        occupied_range=(inicio + timedelta(days=5), inicio + timedelta(days=5, minutes=30)),
        status=AppointmentStatus.SCHEDULED, type='first_visit',
    )
    criados['consultas'].append(viva.id)
    movida = agenda.reschedule_appointment(
        contexto(medico), viva, inicio + timedelta(days=6), inicio + timedelta(days=6, minutes=30),
        medico.user_id,
    )
    confere(movida.starts_at == inicio + timedelta(days=6), 'remarcar a consulta viva funciona -- controle')

    print('=== 3. ND-1121-006: confirmacao do SMS com a chave de quem enviou ===')
    from communications import reconciliation
    from communications.models import Delivery, DeliveryChannel, DeliveryStatus
    from patients.models import PatientContact

    contato = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name=paciente.full_name, phone='11988887777',
    )
    sms = Delivery.objects.create(
        tenant=tenant, contact=contato, appointment=viva, channel=DeliveryChannel.SMS, event_version=1,
        idempotency_key=f'roteiro-lote2:{SUFIXO}', status=DeliveryStatus.ACCEPTED,
        provider_id=f'rot{SUFIXO}', next_attempt_at=timezone.now() - timedelta(minutes=1),
    )
    criados['entregas'].append(sms.id)
    perguntado = {}
    original = reconciliation.check_delivery

    def espia(ids, tenant_id=None):
        if f'rot{SUFIXO}' in ids:
            perguntado['tenant'] = tenant_id
        return {}

    reconciliation.check_delivery = espia
    try:
        reconciliation.reconcile_pending_sms()
    finally:
        reconciliation.check_delivery = original
    confere(perguntado.get('tenant') == tenant.id,
            'a consulta do DLR leva a clinica que enviou', str(perguntado))

    print('=== 4. ND-1121-007: "ERRO" com HTTP 200 nao e aceito ===')
    from communications import smsdev

    class Resposta:
        status_code = 200

        def __init__(self, corpo):
            self._corpo = corpo

        def json(self):
            return self._corpo

    guardado = (dj_settings.SMS_ENABLED, smsdev.resolve_api_key, smsdev.requests.post)
    dj_settings.SMS_ENABLED = True
    smsdev.resolve_api_key = lambda tenant_id=None: 'chave-do-roteiro'
    try:
        smsdev.requests.post = lambda *a, **k: Resposta(
            {'situacao': 'ERRO', 'descricao': 'SALDO INSUFICIENTE'})
        try:
            smsdev.send_sms('11988887777', 'teste', refer='r')
            recusado = False
        except smsdev.SmsSendFailed:
            recusado = True
        confere(recusado, 'a recusa do provedor vira falha de envio')
        smsdev.requests.post = lambda *a, **k: Resposta(
            {'situacao': 'OK', 'codigo': '1', 'id': '123', 'descricao': 'MENSAGEM NA FILA'})
        confere(smsdev.send_sms('11988887777', 'teste', refer='r').get('id') == '123',
                'a resposta OK continua aceita -- controle')
    finally:
        dj_settings.SMS_ENABLED, smsdev.resolve_api_key, smsdev.requests.post = guardado

    print('=== 5. ND-1121-009: exportacao vencida nao baixa ===')
    from reporting.models import ReportExport, ReportExportKind, ReportExportStatus
    from reporting.services import _export_dir

    caminho = _export_dir(tenant.id) / f'roteiro-{SUFIXO}.csv'
    caminho.write_text('a,b\n1,2\n', encoding='utf-8')
    exportacao = ReportExport.objects.create(
        tenant=tenant, requested_by=medico, kind=ReportExportKind.CSV,
        report_name='patients_seen_detail', status=ReportExportStatus.READY,
        storage_key=str(caminho), row_count=1, expires_at=timezone.now() + timedelta(hours=1),
    )
    criados['exportacoes'].append(exportacao.id)
    navegador = Client()
    navegador.force_login(User.objects.get(id=medico.user_id))
    s = navegador.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    url = reverse('reporting:export-download', args=[exportacao.id])
    confere(navegador.get(url).status_code == 200, 'dentro do prazo, baixa -- controle')
    ReportExport.objects.filter(id=exportacao.id).update(expires_at=timezone.now() - timedelta(minutes=1))
    confere(navegador.get(url).status_code == 404,
            'vencida, nao baixa -- mesmo com a limpeza sem ter passado')
    caminho.unlink(missing_ok=True)

    print('=== 6. ND-1121-011: a mesma exportacao duas vezes ===')
    from reporting.tasks import run_export

    duplicada = ReportExport.objects.create(
        tenant=tenant, requested_by=medico, kind=ReportExportKind.JSON,
        report_name='acervo_pacientes', status=ReportExportStatus.QUEUED,
    )
    criados['exportacoes'].append(duplicada.id)
    primeira = run_export(str(duplicada.id))
    segunda = run_export(str(duplicada.id))
    duplicada.refresh_from_db()
    confere(primeira.get('status') == 'ready', 'a primeira execucao prepara o arquivo', str(primeira))
    confere(segunda.get('status') == 'skipped', 'a segunda nem comeca', str(segunda))
    confere(duplicada.status == ReportExportStatus.READY,
            'e a exportacao continua pronta, e nao falha', duplicada.status)

    print('=== 7. ND-1121-012: a retomada da IA nao adia o proprio prazo ===')
    from ai import tasks as ai_tasks
    from ai.models import AIJob, AIJobKind, AIJobStatus

    def job(idade, **extra):
        j = AIJob.objects.create(
            tenant=tenant, user_id=medico.user_id, membership=medico,
            kind=AIJobKind.ENCOUNTER_SUMMARY, source_version=0, purpose='roteiro do lote 2',
            idempotency_key=f'roteiro-lote2:{uuid.uuid4().hex[:10]}', status=AIJobStatus.QUEUED,
            **extra,
        )
        AIJob.objects.filter(id=j.id).update(updated_at=timezone.now() - idade)
        criados['jobs'].append(j.id)
        return AIJob.objects.get(id=j.id)

    quase = job(timedelta(hours=23))
    velho = job(timedelta(hours=25), limits={'retomado_em': timezone.now().isoformat()})
    original_delay = ai_tasks.run_ai_job.delay
    publicados = []

    def publica_e_falha(job_id):
        publicados.append(job_id)
        raise ConnectionError('fila fora do ar (roteiro)')

    ai_tasks.run_ai_job.delay = publica_e_falha
    try:
        ai_tasks.retomar_jobs_parados()
        derrubou = False
    except Exception:
        derrubou = True
    finally:
        ai_tasks.run_ai_job.delay = original_delay
    antes = quase.updated_at
    quase.refresh_from_db()
    velho.refresh_from_db()
    confere(not derrubou, 'fila fora do ar nao derruba a rodada')
    confere(str(quase.id) in publicados, 'o de 23 h foi tentado de novo')
    confere(quase.updated_at == antes, 'e a tentativa NAO renovou o prazo dele', str(quase.updated_at))
    confere(velho.status == AIJobStatus.FAILED,
            'o de 25 h vira falha, mesmo retomado ha pouco', velho.status)

    print('=== 8. ND-1121-013: descartar texto livre pede motivo ===')
    from clinical import finalization
    from clinical.models import Encounter, EncounterKind

    rascunho = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        kind=EncounterKind.FREE_TEXT, occurred_at=timezone.now(),
        free_text='Evolucao inteira escrita no roteiro.',
    )
    criados['atendimentos'].append(rascunho.id)
    confere(finalization.has_content(rascunho), 'o texto livre conta como conteudo')
    try:
        finalization.discard_encounter(contexto(medico), rascunho, medico, reason='')
        descartou = True
    except finalization.FinalizationError:
        descartou = False
    confere(not descartou and Encounter.objects.filter(id=rascunho.id).exists(),
            'sem motivo, o descarte e recusado e a evolucao fica')
    so_impressoes = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        kind=EncounterKind.FREE_TEXT, occurred_at=timezone.now(), impressions='Hipotese.',
    )
    criados['atendimentos'].append(so_impressoes.id)
    confere(finalization.has_content(so_impressoes), 'as impressoes tambem contam')
    vazio = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        kind=EncounterKind.FREE_TEXT, occurred_at=timezone.now(), free_text='   ',
    )
    criados['atendimentos'].append(vazio.id)
    confere(not finalization.has_content(vazio), 'rascunho so com espacos continua vazio -- controle')

    print('=== 9. ND-1121-015: falha de assinatura fica na trilha ===')
    from documents import issuance
    from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
    from documents.signing import InvalidPfxPassword, SigningFailed
    from documents.signing_sessions import SigningSessionKeyMissing

    documento = MedicalDocument.objects.create(
        tenant=tenant, patient=paciente, physician=medico, kind=MedicalDocumentKind.REPORT,
        status=MedicalDocumentStatus.READY_TO_SIGN,
        content_snapshot={'report_text': 'Relatorio do roteiro.'},
        validation_token=secrets.token_urlsafe(16),
    )
    criados['documentos'].append(documento.id)

    class Sessao:
        credential = object()

    trocas = {
        'get_active_session': lambda request, membro: Sessao(),
        'credential_is_usable': lambda credencial: True,
        'decrypt_pfx_bytes': lambda credencial: b'',
        'render_medical_document_pdf': lambda doc: b'%PDF-1.4 roteiro',
    }
    guardado = {nome: getattr(issuance, nome) for nome in list(trocas) + ['unlock_password', 'sign_pdf']}

    def tenta(unlock, assinar):
        for nome, valor in trocas.items():
            setattr(issuance, nome, valor)
        issuance.unlock_password = unlock
        issuance.sign_pdf = assinar
        try:
            issuance.sign_and_issue(documento, None, medico)
        except Exception as exc:
            return exc
        finally:
            for nome, valor in guardado.items():
                setattr(issuance, nome, valor)
        return None

    def falha_com(exc):
        def _f(*a, **k):
            raise exc
        return _f

    for motivo, unlock, assinar, esperado in (
        ('invalid_pfx_password', lambda s: 'senha', falha_com(InvalidPfxPassword('senha errada')),
         issuance.SigningNotAuthorized),
        ('signing_exception', lambda s: 'senha', falha_com(SigningFailed('biblioteca')), SigningFailed),
        ('signing_session_key_missing', falha_com(SigningSessionKeyMissing('sem chave')), None,
         issuance.SigningNotAuthorized),
    ):
        antes = AuditEvent.objects.filter(object_id=documento.id,
                                          action='documents.medicaldocument_sign_failed').count()
        erro = tenta(unlock, assinar)
        depois = list(AuditEvent.objects.filter(
            object_id=documento.id, action='documents.medicaldocument_sign_failed',
        ).order_by('-created_at').values_list('integrity_metadata', flat=True)[:1])
        documento.refresh_from_db()
        confere(isinstance(erro, esperado), f'{motivo}: a tela recebe o erro de sempre', repr(erro))
        confere(len(depois) == 1 and AuditEvent.objects.filter(
            object_id=documento.id, action='documents.medicaldocument_sign_failed').count() == antes + 1
            and (depois[0] or {}).get('reason') == motivo,
            f'{motivo}: a falha FICA na trilha de auditoria', str(depois))
        confere(documento.status == MedicalDocumentStatus.READY_TO_SIGN and not documento.document_number,
                f'{motivo}: o documento continua pronto para assinar, sem numero gasto', documento.status)

finally:
    Membership.objects.filter(id=medico.id).update(roles=papeis_antes)
    Tenant.objects.filter(id=tenant.id).update(plan=plano_antes)
    from ai.models import AIJob
    from clinical.models import Encounter
    from communications.models import Delivery, DeliveryAttempt
    from patients.models import PatientContact
    from documents.models import MedicalDocument
    from events.models import OutboxEvent
    from notifications.models import Notification
    from reporting.models import ReportExport
    from scheduling.models import Appointment

    Notification.objects.filter(target_id__in=criados['jobs'] + criados['exportacoes']).delete()
    AIJob.objects.filter(id__in=criados['jobs']).delete()
    for exp in ReportExport.objects.filter(id__in=criados['exportacoes']):
        if exp.storage_key:
            try:
                os.unlink(exp.storage_key)
            except OSError:
                pass
    ReportExport.objects.filter(id__in=criados['exportacoes']).delete()
    # O worker local despacha a outbox a cada cinco segundos: os eventos
    # da consulta de teste podem ter virado marcador e entrega enquanto o
    # roteiro rodava.
    from events.models import ProcessedEvent

    entregas = Delivery.objects.filter(id__in=criados['entregas']) | Delivery.objects.filter(
        appointment_id__in=criados['consultas'])
    DeliveryAttempt.objects.filter(delivery__in=entregas).delete()
    entregas.delete()
    ProcessedEvent.objects.filter(event__aggregate_id__in=criados['consultas']).delete()
    OutboxEvent.objects.filter(aggregate_id__in=criados['consultas']).delete()
    Appointment.objects.filter(id__in=criados['consultas']).delete()
    Encounter.objects.filter(id__in=criados['atendimentos']).delete()
    MedicalDocument.objects.filter(id__in=criados['documentos']).delete()
    PatientContact.objects.filter(patient_id__in=criados['pacientes']).delete()
    Patient.objects.filter(id__in=criados['pacientes']).delete()

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - o lote 2 da auditoria se sustenta.')
