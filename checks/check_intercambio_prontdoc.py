"""Achados do ProntDoc avaliados aqui (intercâmbio de 2026-11-15/17).

O ProntDoc nasceu deste código e, na revisão da 1.2.0 dele, achou dezessete
defeitos (`docs/intercambio/`). A maioria estava aqui também. Este roteiro
tenta quebrar cada correção feita no NeuroDoc — e o defeito que só existia
aqui, o Ctrl+S da tela estruturada (ND-2026-11-15-01). As perguntas:

- trazer a conduta anterior **acrescenta** à de hoje em vez de apagá-la?
- recusar o rascunho da IA funciona com o prontuário alterado depois, e o
  erro vira aviso na tela em vez de página em branco? E aprovar continua
  exigindo o prontuário inalterado?
- o aviso do sino do apoio diagnóstico leva ao cartão de hipóteses?
- valor de exame com "%" passa, e probabilidade em número continua barrada?
- hipótese com id de CID inexistente entra pelo texto, sem erro 500?
- "Analisar de novo" depois de registrar hipótese pede análise **nova**, e
  sem mudança nenhuma devolve a mesma?
- atendimento finalizado: sem análise nova, campos só de leitura?
- todo formulário da tela que recarrega a página salva o texto antes, nos
  dois tipos, e o Ctrl+S nunca cai no "primeiro formulário"?
- a vitrine não promete atestado nem "quem viu o quê"?

Roda dentro de uma transação desfeita no fim: nada fica na base.
"""
import re
import uuid
from unittest import mock

from django.conf import settings as dj_settings
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from ai import schemas
from ai.models import AIArtifact, AIJob, AIJobKind, AIJobStatus, AIReviewState
from clinical.carry_forward import review_carry_forward_item
from clinical.models import (
    CarryForwardItem, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus,
)
from patients.models import Patient, RegistrationStage
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
user = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant, user=user)


def cliente():
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def atendimento(paciente, kind=EncounterKind.STRUCTURED, **campos):
    return Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=vinculo,
        occurred_at=timezone.now(), status=EncounterStatus.IN_PROGRESS, kind=kind, **campos,
    )


def tags_de_form(html):
    return re.findall(r'<form\b[^>]*>', html, flags=re.S)


try:
    with transaction.atomic():
        paciente = Patient.objects.create(
            tenant=tenant, full_name=f'PACIENTE INTERCAMBIO {uuid.uuid4().hex[:6].upper()}',
            registration_stage=RegistrationStage.COMPLETE,
            birth_date_unknown_reason='Roteiro de verificacao.',
        )
        c = cliente()

        print('=== 1. a conduta anterior acrescenta (PD-03) ===')
        anterior = atendimento(paciente, plan_text='Manter topiramato 50 mg.')
        hoje = atendimento(paciente, plan_text='[Pedido de exames · emitido hoje]')
        item = CarryForwardItem.objects.create(
            tenant=tenant, target_encounter=hoje, source_encounter=anterior,
            field_path='plan_text', source_version_hash='x',
            copied_value={'text': 'Manter topiramato 50 mg.'},
        )
        review_carry_forward_item(item, 'accepted', vinculo.id)
        hoje.refresh_from_db()
        conferir('o texto de hoje fica, e o trazido vem depois',
                 hoje.plan_text == '[Pedido de exames · emitido hoje]\n\nManter topiramato 50 mg.',
                 repr(hoje.plan_text))
        vazio = atendimento(paciente)
        item2 = CarryForwardItem.objects.create(
            tenant=tenant, target_encounter=vazio, source_encounter=anterior,
            field_path='plan_text', source_version_hash='x', copied_value={'text': 'Manter topiramato 50 mg.'},
        )
        review_carry_forward_item(item2, 'accepted', vinculo.id)
        vazio.refresh_from_db()
        conferir('campo vazio recebe o texto como antes', vazio.plan_text == 'Manter topiramato 50 mg.',
                 repr(vazio.plan_text))
        repetido = atendimento(paciente, plan_text='Manter topiramato 50 mg.')
        item3 = CarryForwardItem.objects.create(
            tenant=tenant, target_encounter=repetido, source_encounter=anterior,
            field_path='plan_text', source_version_hash='x', copied_value={'text': 'Manter topiramato 50 mg.'},
        )
        review_carry_forward_item(item3, 'accepted', vinculo.id)
        repetido.refresh_from_db()
        conferir('o mesmo texto não se repete', repetido.plan_text == 'Manter topiramato 50 mg.',
                 repr(repetido.plan_text))

        print('=== 2. recusar a IA com o prontuário alterado (PD-06) ===')
        enc = atendimento(paciente, chief_complaint='Cefaleia.')

        def apoio(status=AIJobStatus.SUCCEEDED, versao=None):
            job = AIJob.objects.create(
                tenant=tenant, user=user, membership=vinculo, patient=paciente, encounter=enc,
                kind=AIJobKind.DIAGNOSTIC_SUPPORT, purpose='Roteiro', status=status,
                source_version=enc.row_version if versao is None else versao,
                idempotency_key=f'roteiro:{uuid.uuid4().hex}',
            )
            artefato = AIArtifact.objects.create(
                tenant=tenant, job=job, schema_version='v1', provider='roteiro', model='roteiro',
                prompt_version='v1', result={'hypotheses': [], 'suggested_next_steps': []},
            )
            return job, artefato

        job, artefato = apoio(versao=enc.row_version - 1)  # prontuário mudou depois
        r = c.post(reverse('ai:artifact-reject', args=[artefato.id]), {'reason': 'nao ajuda'})
        artefato.refresh_from_db()
        conferir('a recusa passa mesmo com o prontuário alterado',
                 artefato.review_state == AIReviewState.REJECTED, artefato.review_state)
        conferir('e volta para uma tela, não para a página em branco', r.status_code == 302, r.status_code)
        r = c.post(reverse('ai:artifact-reject', args=[artefato.id]), {'reason': 'de novo'})
        conferir('a segunda recusa vira aviso, não 403', r.status_code == 302, r.status_code)
        job2, artefato2 = apoio(versao=enc.row_version - 1)
        r = c.post(reverse('ai:artifact-accept', args=[artefato2.id]))
        artefato2.refresh_from_db()
        conferir('aprovar continua exigindo o prontuário inalterado',
                 artefato2.review_state == AIReviewState.PENDING and r.status_code == 302,
                 (artefato2.review_state, r.status_code))

        print('=== 3. o aviso do sino abre o cartão de hipóteses (PD-07) ===')
        r = c.get(reverse('ai:job-detail', args=[job.id]))
        conferir('apoio pronto vai ao atendimento, na aba de hipóteses',
                 r.status_code == 302 and r['Location'].endswith(f'/app/clinical/{enc.id}/#tab-hipoteses'),
                 (r.status_code, r.get('Location')))
        rodando, _ = apoio(status=AIJobStatus.RUNNING)
        conferir('enquanto roda, fica na tela que se atualiza',
                 c.get(reverse('ai:job-detail', args=[rodando.id])).status_code == 200)

        print('=== 4. valor de exame com % (PD-08) ===')
        padrao = schemas._NUMERIC_PROBABILITY_PATTERN
        for texto, barrar in (
            ('HbA1c acima de 6,5%', False), ('saturação de 92% em ar ambiente', False),
            ('redução de 50% das crises', False), ('70% de chance', True),
            ('probabilidade de 80%', True), ('com 90% de probabilidade', True),
            ('85% de certeza diagnóstica', True), ('confiança de 75%', True),
            ('chance de 40', True), ('3 em 10 chance', True),
        ):
            conferir(f'"{texto}" {"barrado" if barrar else "passa"}',
                     bool(padrao.search(texto)) == barrar)

        print('=== 5. CID com id inexistente (PD-09) ===')
        antes = enc.diagnoses.count()
        r = c.post(reverse('clinical:add-diagnosis', args=[enc.id]), {
            'diagnosis_code_id': str(uuid.uuid4()), 'cid_sistema': 'CID10',
            'code_snapshot': 'G43', 'description_snapshot': 'Enxaqueca',
            'certainty': 'suspected', 'rank': 1,
        })
        nova = enc.diagnoses.order_by('-created_at').first()
        conferir('sem erro 500', r.status_code == 302, r.status_code)
        conferir('a hipótese entra pelo texto, sem o id',
                 enc.diagnoses.count() == antes + 1 and nova.diagnosis_code_id is None,
                 enc.diagnoses.count() - antes)

        print('=== 6. "Analisar de novo" depois de mudar o caso (PD-11) ===')
        caso = atendimento(paciente, chief_complaint='Tremor.')
        url = reverse('clinical:request-diagnostic-support', args=[caso.id])
        with mock.patch('ai.tasks.run_ai_job.delay'):
            c.post(url)
            c.post(url)
            conferir('sem mudança, o mesmo pedido',
                     AIJob.objects.filter(encounter=caso, kind=AIJobKind.DIAGNOSTIC_SUPPORT).count() == 1)
            EncounterDiagnosis.objects.create(
                tenant=tenant, encounter=caso, code_snapshot='', description_snapshot='Tremor essencial',
                certainty='suspected', rank=1,
            )
            c.post(url)
            conferir('hipótese nova pede análise nova',
                     AIJob.objects.filter(encounter=caso, kind=AIJobKind.DIAGNOSTIC_SUPPORT).count() == 2)

        print('=== 7. atendimento finalizado (PD-05, PD-12) ===')
        Encounter.objects.filter(id=caso.id).update(status=EncounterStatus.FINALIZED)
        with mock.patch('ai.tasks.run_ai_job.delay'):
            r = c.post(url)
        conferir('análise nova recusada', r.status_code == 302
                 and AIJob.objects.filter(encounter=caso, kind=AIJobKind.DIAGNOSTIC_SUPPORT).count() == 2)
        html = c.get(reverse('clinical:detail', args=[caso.id])).content.decode()
        conferir('sem o botão "Analisar de novo"', 'Analisar de novo' not in html)
        caixas = re.findall(r'<textarea\b[^>]*data-nd-encounter-draft[^>]*>', html)
        conferir('as caixas de texto saem só de leitura (estruturado)',
                 bool(caixas) and all('readonly' in t for t in caixas), len(caixas))
        livre_fin = atendimento(paciente, kind=EncounterKind.FREE_TEXT, free_text='Ok.')
        Encounter.objects.filter(id=livre_fin.id).update(status=EncounterStatus.FINALIZED)
        html = c.get(reverse('clinical:detail', args=[livre_fin.id])).content.decode()
        caixas = re.findall(r'<textarea\b[^>]*data-nd-encounter-draft[^>]*>', html)
        conferir('as caixas de texto saem só de leitura (texto livre)',
                 bool(caixas) and all('readonly' in t for t in caixas), len(caixas))

        print('=== 8. formulários que salvam o texto antes (PD-01, PD-04) ===')
        isentos = ('/autosave/', '/amendments/', '/descartar/')
        for rotulo, kind in (('estruturado', EncounterKind.STRUCTURED), ('texto livre', EncounterKind.FREE_TEXT)):
            aberto = atendimento(paciente, kind=kind, chief_complaint='X.', free_text='X.')
            html = c.get(reverse('clinical:detail', args=[aberto.id])).content.decode()
            sem = []
            for tag in tags_de_form(html):
                acao = re.search(r'action="([^"]*)"', tag)
                acao = acao.group(1) if acao else ''
                if '/app/clinical/' not in acao and 'remove-finding-form' not in tag:
                    continue
                if any(x in acao for x in isentos):
                    continue
                if 'data-nd-save-encounter-before-submit' not in tag:
                    sem.append(acao or tag[:50])
            conferir(f'{rotulo}: todo formulário do atendimento salva antes', not sem, sem)
            final = [t for t in tags_de_form(html) if '/finalize/' in t]
            conferir(f'{rotulo}: inclusive o de finalizar',
                     bool(final) and all('data-nd-save-encounter-before-submit' in t for t in final))

        print('=== 9. o atendimento.js (PD-01, PD-02, ND-01) ===')
        from django.contrib.staticfiles import finders

        js = open(finders.find('clinical/atendimento.js'), encoding='utf-8').read()
        conferir('o "salvar antes" ouve no document (o modal fica fora da raiz)',
                 "document.addEventListener('submit'" in js)
        conferir('o Ctrl+S nunca cai no primeiro formulário da página',
                 "raiz.querySelector('form')" not in js and "painel.querySelector('form')" not in js)
        conferir('na aba, só o formulário que carrega a versão do atendimento',
                 'form [name="row_version"]' in js)
        conferir('o botão ligado por form= é achado', 'botaoDe' in js)
        conferir('finalizado não oferece rascunho', 'editavel ? lerRascunhos() : []' in js)
        conferir('finalizar com texto pendente grava antes', "searchParams.set('finalizar', '1')" in js)

        print('=== 10. a vitrine (PD-16) ===')
        from base import content

        texto = repr(vars(content)).lower()
        conferir('não promete atestado', 'atestado' not in texto)
        conferir('não promete "quem viu o quê"', 'quem viu o quê' not in texto)
        conferir('não diz que a chave do backup é do responsável',
                 'chave de recuperação é do responsável' not in texto)
        raise Desfazer
except Desfazer:
    print('=== transação desfeita: nada ficou na base ===')

if falhas:
    print('\nFALHAS:')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('\nOK: os achados do ProntDoc que valiam aqui estão corrigidos, e o Ctrl+S da tela')
print('    estruturada não envia mais o primeiro formulário da aba.')
