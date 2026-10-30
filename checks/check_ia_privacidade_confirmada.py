"""Apoio diagnóstico bloqueado pela privacidade: o médico lê o motivo e decide.

Relatado em 2026-10-29: a aba de hipóteses de um caso com consanguinidade
respondida mostrava "Bloqueado (privacidade) — marcador 'consanguinidade'"
e nada mais; analisar de novo devolvia o mesmo bloqueio, para sempre. A
porta que o relatório já tinha (`risco_confirmado`) foi aberta para o apoio
diagnóstico. Tenta quebrar. As perguntas são:

- a política continua **fechada por padrão** (o marcador bloqueia sem a
  confirmação) e abre só com ela?
- bloqueado, a tela mostra o motivo **e** o botão de prosseguir, com
  confirmação?
- "Analisar o caso" de novo, sem confirmar, não reabre o pedido bloqueado?
- confirmando, o mesmo pedido volta para a fila com `risco_confirmado`, e a
  confirmação entra na trilha com o nome de quem decidiu?
- a confirmação não reabre pedido que não estava bloqueado?
- a secretária não chega lá?
"""
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from ai import privacy_policy
from ai.models import AIJob, AIJobKind, AIJobStatus
from audit.models import AuditEvent
from clinical.models import Encounter, EncounterKind, EncounterStatus
from patients.models import Patient, RegistrationStage
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


tenant = Tenant.objects.get(slug='demo-clinica-a')
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant, user=user)
criados = {'pacientes': [], 'atendimentos': []}
MOTIVO = 'Marcador de risco de reidentificação detectado: "consanguinidade".'


def cliente(u=user):
    c = Client()
    c.force_login(u)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def postar(c, enc, confirmado):
    dados = {'risco_confirmado': '1'} if confirmado else {}
    with mock.patch('ai.tasks.run_ai_job.delay'):
        return c.post(url_pedido(enc), dados)


def url_pedido(enc):
    from django.urls import reverse

    return reverse('clinical:request-diagnostic-support', args=[enc.id])


try:
    print('=== 1. a política continua fechada por padrão ===')
    texto = '{"consanguinidade": "Não"}'
    conferir('o marcador bloqueia sem confirmação', not privacy_policy.evaluate_privacy_policy(None, texto).allowed)
    conferir('e passa com ela', privacy_policy.evaluate_privacy_policy(None, texto, risco_confirmado=True).allowed)

    pac = Patient.objects.create(
        tenant=tenant, full_name='PACIENTE IA PRIVACIDADE', registration_stage=RegistrationStage.COMPLETE,
        birth_date_unknown_reason='Roteiro de verificacao.',
    )
    criados['pacientes'].append(pac.id)
    enc = Encounter.objects.create(
        tenant=tenant, patient=pac, physician_membership=vinculo, occurred_at=timezone.now(),
        status=EncounterStatus.IN_PROGRESS, kind=EncounterKind.STRUCTURED, chief_complaint='Ataxia.',
    )
    criados['atendimentos'].append(enc.id)

    print('=== 2. o pedido bloqueado ===')
    c = cliente()
    postar(c, enc, confirmado=False)
    job = AIJob.objects.filter(encounter_id=enc.id, kind=AIJobKind.DIAGNOSTIC_SUPPORT).first()
    conferir('o pedido nasceu', job is not None)
    # O worker não roda aqui: o bloqueio é gravado como ele gravaria.
    AIJob.objects.filter(pk=job.pk).update(status=AIJobStatus.BLOCKED_PRIVACY, status_detail=MOTIVO)
    html = c.get(f'/app/clinical/{enc.id}/').content.decode()
    conferir('a tela mostra o motivo', 'consanguinidade' in html and 'data-nd-ia-privacidade' in html)
    conferir('e o botão de prosseguir, com confirmação',
             'Entendo o risco, analisar assim mesmo' in html and 'name="risco_confirmado"' in html
             and 'data-nd-confirm="Enviar o caso à IA' in html)

    print('=== 3. sem confirmar, nada reabre ===')
    postar(c, enc, confirmado=False)
    job.refresh_from_db()
    conferir('"Analisar o caso" de novo mantém o bloqueio', job.status == AIJobStatus.BLOCKED_PRIVACY, job.status)

    print('=== 4. a secretária não chega lá ===')
    r = postar(cliente(secretaria), enc, confirmado=True)
    job.refresh_from_db()
    conferir('a secretária é recusada e o pedido segue bloqueado',
             r.status_code in (403, 404) and job.status == AIJobStatus.BLOCKED_PRIVACY, (r.status_code, job.status))

    print('=== 5. confirmando ===')
    antes = AuditEvent.objects.filter(action='ai.privacy_risk_confirmed', object_id=enc.id).count()
    postar(c, enc, confirmado=True)
    job.refresh_from_db()
    esperado = AIJobStatus.QUEUED if dj_settings.AI_ENABLED else AIJobStatus.DISABLED
    conferir('o mesmo pedido volta para a fila', job.status == esperado, job.status)
    conferir('com a confirmação gravada nele', (job.target_ref or {}).get('risco_confirmado') is True)
    conferir('o motivo antigo sai da tela', job.status_detail == '')
    evento = AuditEvent.objects.filter(action='ai.privacy_risk_confirmed', object_id=enc.id).order_by('-created_at').first()
    conferir('a confirmação entra na trilha, com quem decidiu',
             AuditEvent.objects.filter(action='ai.privacy_risk_confirmed', object_id=enc.id).count() == antes + 1
             and evento is not None and str(evento.actor_id) == str(user.id))

    print('=== 6. a confirmação não reabre o que não estava bloqueado ===')
    AIJob.objects.filter(pk=job.pk).update(status=AIJobStatus.SUCCEEDED, target_ref={})
    postar(c, enc, confirmado=True)
    job.refresh_from_db()
    conferir('pedido concluído continua concluído, sem confirmação gravada',
             job.status == AIJobStatus.SUCCEEDED and not (job.target_ref or {}).get('risco_confirmado'), job.status)
finally:
    print('=== limpeza ===')
    AIJob.objects.filter(encounter_id__in=criados['atendimentos']).delete()
    Encounter.objects.filter(id__in=criados['atendimentos']).delete()
    Patient.objects.filter(id__in=criados['pacientes']).delete()
    print('  pedidos, atendimento e paciente do roteiro removidos')

if falhas:
    print('\nFALHAS:')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('\nOK: apoio diagnóstico bloqueado pela privacidade — fechado por padrão, motivo à vista, e o')
print('    médico que confirma reabre o mesmo pedido, com a decisão na trilha.')
