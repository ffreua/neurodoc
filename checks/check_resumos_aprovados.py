"""O resumo por IA aprovado aparece no atendimento (1.20).

Relatado em uso real (2026-10-20): o médico gerou o resumo, aprovou — e
não achou mais. "Aceitar" é juízo editorial e nunca escreveu no
prontuário (de propósito); a única porta de volta era o aviso do sino, que
a retenção apaga em 7 a 15 dias.

As perguntas são:
  1. o aprovado e o editado aparecem; o pendente e o recusado não?
  2. só os resumos DESTE atendimento — nem os de outro atendimento, nem o
     apoio diagnóstico, nem os de outra clínica?
  3. a tela do atendimento (estruturado e texto livre) desenha o bloco, com
     o texto e quem aprovou, e não desenha nada quando não há aprovado?
  4. o bloco fica fora do registro: o texto clínico e o `content_hash` não
     mudam, e o bloco diz que não faz parte do registro?
  5. a fronteira: secretária não abre o atendimento, e o "Abrir" só aparece
     para quem tem a IA no plano?
"""
import uuid

from django.conf import settings
from django.test import Client
from django.utils import timezone

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
settings.SECURE_SSL_REDIRECT = False

from ai.models import AIArtifact, AIJob, AIJobKind, AIJobStatus, AIReviewState
from ai.services import resumos_aprovados
from clinical.models import Encounter, EncounterKind
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def conferir(condicao, rotulo):
    print(('ok    ' if condicao else 'FALHA ') + rotulo)
    if not condicao:
        falhas.append(rotulo)


def medico_de(tenant):
    return next((
        m for m in Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
        ).select_related('user') if m.can_practice_clinically()
    ), None)


tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.filter(slug='demo-clinica-b').first()
doctor = medico_de(tenant)
patient = Patient.objects.filter(tenant=tenant, registration_stage='complete').first()
if doctor is None or patient is None:
    print('PULADO: demonstração sem médico verificado ou paciente')
    raise SystemExit(0)

criados_enc, criados_job = [], []


def atendimento(kind=EncounterKind.STRUCTURED, t=tenant, medico=None, paciente=None):
    enc = Encounter.objects.create(
        tenant=t, patient=paciente or patient, physician_membership=medico or doctor,
        occurred_at=timezone.now(), kind=kind, plan_text='Conduta do roteiro.',
    )
    criados_enc.append(enc)
    return enc


def resumo(enc, estado, texto, kind=AIJobKind.ENCOUNTER_SUMMARY, medico=None):
    medico = medico or doctor
    job = AIJob.objects.create(
        tenant_id=enc.tenant_id, user=medico.user, membership=medico,
        patient=enc.patient, encounter=enc, kind=kind,
        source_version=enc.row_version, purpose='roteiro', status=AIJobStatus.SUCCEEDED,
        idempotency_key=f'roteiro-resumos-{uuid.uuid4()}',
    )
    criados_job.append(job)
    revisado = estado != AIReviewState.PENDING
    return AIArtifact.objects.create(
        tenant_id=enc.tenant_id, job=job, schema_version='v1', provider='roteiro',
        model='roteiro', prompt_version='v3',
        result={'summary': texto, 'limitations': 'Limitação do roteiro.',
                'qualitative_hypotheses': ['Hipótese qualitativa do roteiro']},
        review_state=estado, reviewer=medico if revisado else None,
        reviewed_at=timezone.now() if revisado else None,
    )


try:
    enc = atendimento()
    hash_antes, texto_antes = enc.content_hash, enc.plan_text
    resumo(enc, AIReviewState.ACCEPTED, 'RESUMO-APROVADO-XYZ')
    resumo(enc, AIReviewState.EDITED, 'RESUMO-EDITADO-XYZ')
    resumo(enc, AIReviewState.PENDING, 'RESUMO-PENDENTE-XYZ')
    resumo(enc, AIReviewState.REJECTED, 'RESUMO-RECUSADO-XYZ')
    resumo(enc, AIReviewState.ACCEPTED, 'APOIO-DIAGNOSTICO-XYZ', kind=AIJobKind.DIAGNOSTIC_SUPPORT)
    outro_enc = atendimento()
    resumo(outro_enc, AIReviewState.ACCEPTED, 'DE-OUTRO-ATENDIMENTO-XYZ')

    print('=== 1 e 2. quais entram ===')
    textos = [a.result['summary'] for a in resumos_aprovados(enc)]
    conferir('RESUMO-APROVADO-XYZ' in textos, 'o aprovado entra')
    conferir('RESUMO-EDITADO-XYZ' in textos, 'o editado entra')
    conferir('RESUMO-PENDENTE-XYZ' not in textos, 'o pendente não entra (ainda não foi revisado)')
    conferir('RESUMO-RECUSADO-XYZ' not in textos, 'o recusado não entra')
    conferir('APOIO-DIAGNOSTICO-XYZ' not in textos, 'o apoio diagnóstico não entra (tem bloco próprio)')
    conferir('DE-OUTRO-ATENDIMENTO-XYZ' not in textos, 'o de outro atendimento não entra')
    conferir(len(textos) == 2, f'exatamente dois (vieram {len(textos)})')

    if outra:
        medico_b = medico_de(outra)
        paciente_b = Patient.objects.filter(tenant=outra, registration_stage='complete').first()
        if medico_b and paciente_b:
            enc_b = atendimento(t=outra, medico=medico_b, paciente=paciente_b)
            resumo(enc_b, AIReviewState.ACCEPTED, 'DE-OUTRA-CLINICA-XYZ', medico=medico_b)
            conferir('DE-OUTRA-CLINICA-XYZ' not in [a.result['summary'] for a in resumos_aprovados(enc)],
                     'o de outra clínica não entra')

    print('=== 3. a tela desenha ===')
    cliente = Client()
    cliente.force_login(doctor.user)
    s = cliente.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    r = cliente.get(f'/app/clinical/{enc.id}/')
    html = r.content.decode()
    conferir(r.status_code == 200, f'o atendimento estruturado abre ({r.status_code})')
    conferir('Resumos por IA aprovados' in html, 'o bloco aparece')
    conferir('RESUMO-APROVADO-XYZ' in html and 'RESUMO-EDITADO-XYZ' in html, 'com os dois textos')
    conferir('RESUMO-PENDENTE-XYZ' not in html and 'RESUMO-RECUSADO-XYZ' not in html,
             'sem o pendente e o recusado')
    conferir('Editado' in html, 'o editado leva o selo')
    conferir(doctor.user.get_full_name() in html, 'diz quem aprovou')

    livre = atendimento(kind=EncounterKind.FREE_TEXT)
    resumo(livre, AIReviewState.ACCEPTED, 'RESUMO-LIVRE-XYZ')
    r = cliente.get(f'/app/clinical/{livre.id}/')
    conferir(r.status_code == 200 and 'RESUMO-LIVRE-XYZ' in r.content.decode(),
             'o atendimento de texto livre também mostra')

    vazio = atendimento()
    r = cliente.get(f'/app/clinical/{vazio.id}/')
    conferir('Resumos por IA aprovados' not in r.content.decode(),
             'sem aprovado, o bloco nem aparece')

    print('=== 4. fora do registro ===')
    enc.refresh_from_db()
    conferir(enc.content_hash == hash_antes and enc.plan_text == texto_antes,
             'o texto clínico e o content_hash não mudaram')
    conferir('não faz parte do registro clínico' in html, 'o bloco diz que não faz parte do registro')

    print('=== 5. fronteira ===')
    secretaria = Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.SECRETARY],
    ).exclude(roles__contains=[Role.DOCTOR]).select_related('user').first()
    if secretaria:
        c2 = Client()
        c2.force_login(secretaria.user)
        s2 = c2.session
        s2['tenant_id'] = str(tenant.id)
        s2.save()
        r = c2.get(f'/app/clinical/{enc.id}/')
        conferir(r.status_code == 404 and 'RESUMO-APROVADO-XYZ' not in r.content.decode(),
                 f'a secretária não abre o atendimento ({r.status_code})')
    conferir("{% if nd_can.clinical_ai %}" in open(
        settings.BASE_DIR / 'templates' / 'clinical' / '_resumos_ia.html', encoding='utf-8').read(),
        'o link "Abrir" só para quem tem a IA no plano')
finally:
    AIArtifact.objects.filter(job__in=criados_job).delete()
    AIJob.objects.filter(id__in=[j.id for j in criados_job]).delete()
    Encounter.objects.filter(id__in=[e.id for e in criados_enc]).delete()

if falhas:
    print(f'\nFALHA: {len(falhas)} item(ns): ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: o resumo aprovado aparece no atendimento, fora do registro clínico.')
