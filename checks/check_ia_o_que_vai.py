"""O que vai à IA: sem consanguinidade, e num tamanho que cabe (2026-11-02).

Duas decisões do responsável depois da revisão de 2026-11-02:

1. **A consanguinidade não vai ao provedor, e não trava mais.** Ela é dado de
   saúde como todo o prontuário; o que a trava protegia era a
   reidentificação por combinação rara. Com o histórico do iClin ("nega
   consanguinidade" em 946 de 1.003 ocorrências), a IA ficou fechada para
   972 dos 2.217 pacientes migrados. Agora o trecho sai do texto e a IA
   trabalha sem ele; "doença rara", "genealogia" e "herança genética"
   continuam travando.
2. **O prontuário cabe.** Cada campo de texto vai encurtado
   (`MAX_CHARS_POR_CAMPO`), o relatório tem teto total declarado no recorte,
   e o chat põe medicação, diagnósticos e exames **antes** dos atendimentos —
   o corte, que é no fim, levava justamente esses.

    docker compose exec -T app python manage.py shell < checks/check_ia_o_que_vai.py
"""
import json
from datetime import timedelta
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from ai import privacy_policy, relatorio, services
from ai.chat_prompt import MAX_CONTEXT_CHARS, build_patient_context
from ai.context import AIAuthorization, build_ai_authorization
from ai.deidentification import MARCADOR_CONSANGUINIDADE, deidentify_text, omitir_consanguinidade
from ai.models import AIJob, AIJobKind, AIJobStatus
from ai.tools import clinical as clinical_tools
from clinical.models import ConsanguinityState, Encounter, EncounterKind, EncounterStatus, Medication
from patients.models import Patient, RegistrationStage
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(rotulo)


def sem_marca(texto):
    """O texto sem a marca de omissão, que também contém a palavra."""
    return texto.replace(MARCADOR_CONSANGUINIDADE, '').lower()


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.get(tenant=tenant, user__email='doctor-a@demo.neurodoc.local')
ctx = SimpleNamespace(tenant_id=tenant.id, user_id=vinculo.user_id, membership_id=vinculo.id)

try:
    with transaction.atomic():
        print('=== 1. O trecho de consanguinidade sai do texto ===')
        casos = {
            'AF: pais não consanguíneos, mãe com enxaqueca.': ('AF:', 'mãe com enxaqueca'),
            'NEGA CONSANGUINIDADE. Irmão com epilepsia.': ('Irmão com epilepsia',),
            'Consangüinidade entre os pais (primos); avó com Parkinson': ('avó com Parkinson',),
        }
        for entrada, preservado in casos.items():
            saida = omitir_consanguinidade(entrada)
            conferir(f'omitido: {entrada[:32]}…', 'consang' not in sem_marca(saida) and MARCADOR_CONSANGUINIDADE in saida
                     and all(p in saida for p in preservado), saida)
        conferir('texto sem o assunto fica igual', omitir_consanguinidade('Sem queixas.') == 'Sem queixas.')
        bruto = json.dumps({'texto': 'AF: nega consanguinidade, pai hipertenso.\nOutra linha'}, ensure_ascii=False)
        conferir('dentro de JSON, o JSON continua válido', 'pai hipertenso' in json.loads(omitir_consanguinidade(bruto))['texto'])
        conferir('a desidentificação já aplica', 'consang' not in sem_marca(deidentify_text('Nega consanguinidade.', None)))

        print('=== 2. A trava ===')
        conferir('consanguinidade não trava',
                 privacy_policy.evaluate_privacy_policy(None, 'pais consanguíneos, primos de primeiro grau').allowed)
        conferir('doença rara continua travando',
                 not privacy_policy.evaluate_privacy_policy(None, 'suspeita de doença rara').allowed)
        conferir('e a confirmação do médico continua atravessando',
                 privacy_policy.evaluate_privacy_policy(None, 'suspeita de doença rara', risco_confirmado=True).allowed)
        conferir('a marca de omissão não chega ao papel do relatório',
                 relatorio.marcadores_residuais(f'Pais {MARCADOR_CONSANGUINIDADE}.') == [MARCADOR_CONSANGUINIDADE])

        print('=== 3. O apoio diagnóstico não leva o campo estruturado ===')
        pac = Patient.objects.create(tenant=tenant, full_name='PACIENTE ROTEIRO IA CONTEXTO',
                                     registration_stage=RegistrationStage.COMPLETE,
                                     birth_date_unknown_reason='Roteiro de verificação.')
        agora = timezone.now()
        atual = Encounter.objects.create(
            tenant=tenant, patient=pac, physician_membership=vinculo, occurred_at=agora,
            status=EncounterStatus.IN_PROGRESS, kind=EncounterKind.STRUCTURED, chief_complaint='Ataxia progressiva.',
            consanguinity_state=ConsanguinityState.CONFIRMED, consanguinity_details='Pais primos em primeiro grau.',
        )
        autorizacao = AIAuthorization(tenant_id=tenant.id, user_id=vinculo.user_id, membership_id=vinculo.id,
                                      patient_id=pac.id, encounter_id=atual.id)
        contexto, _ = services._gather_diagnostic_context(autorizacao, atual)
        enviado = deidentify_text(json.dumps(contexto, ensure_ascii=False, default=str), pac)
        conferir('nem o estado nem o detalhe vão', 'consang' not in enviado.lower() and 'primos em primeiro' not in enviado)
        conferir('e o caso passa pela trava', privacy_policy.evaluate_privacy_policy(atual, enviado).allowed)

        print('=== 4. O bloqueio decidido pela política antiga é refeito ===')
        job = services.create_job(ctx, AIJobKind.DIAGNOSTIC_SUPPORT, 'roteiro', patient_id=pac.id,
                                  encounter_id=atual.id)
        AIJob.objects.filter(pk=job.pk).update(status=AIJobStatus.BLOCKED_PRIVACY, policy_version='v1',
                                               status_detail='Marcador de risco: "consanguinidade".')
        de_novo = services.create_job(ctx, AIJobKind.DIAGNOSTIC_SUPPORT, 'roteiro', patient_id=pac.id,
                                      encounter_id=atual.id)
        conferir('o pedido volta para a fila, com a política nova',
                 de_novo.id == job.id and de_novo.status in (AIJobStatus.QUEUED, AIJobStatus.DISABLED)
                 and de_novo.policy_version == privacy_policy.POLICY_VERSION, (de_novo.status, de_novo.policy_version))
        AIJob.objects.filter(pk=job.pk).update(status=AIJobStatus.BLOCKED_PRIVACY,
                                               policy_version=privacy_policy.POLICY_VERSION)
        mantido = services.create_job(ctx, AIJobKind.DIAGNOSTIC_SUPPORT, 'roteiro', patient_id=pac.id,
                                      encounter_id=atual.id)
        conferir('o bloqueio da política em vigor continua bloqueio', mantido.status == AIJobStatus.BLOCKED_PRIVACY)

        print('=== 5. Os textos longos cabem ===')
        Medication.objects.create(tenant=tenant, encounter=atual, name='LEVETIRACETAM ROTEIRO', dose='500 mg')
        longo = ('Queixa e evolução do roteiro. ' * 400)  # ~12 mil caracteres, como uma anotação do iClin
        for n in range(1, 21):
            Encounter.objects.create(
                tenant=tenant, patient=pac, physician_membership=vinculo, occurred_at=agora - timedelta(days=30 * n),
                status=EncounterStatus.FINALIZED, kind=EncounterKind.FREE_TEXT, free_text=longo,
                legacy_id=f'roteiro:{n}', finalized_at=agora, finalized_by=vinculo,
            )
        autorizacao_p = build_ai_authorization(ctx, patient_id=pac.id)
        linha = clinical_tools.get_patient_timeline(autorizacao_p, limit=5, max_chars_por_campo=2500)[1]
        conferir('cada campo vem encurtado, com a marca',
                 len(linha['free_text']) <= 2500 + len(clinical_tools.MARCA_DE_CORTE)
                 and linha['free_text'].endswith(clinical_tools.MARCA_DE_CORTE))
        inteiro = clinical_tools.get_patient_timeline(autorizacao_p, limit=5)[1]
        conferir('sem o teto, o texto inteiro (quem já chamava não muda)', inteiro['free_text'] == longo)

        resumo, _ = services._gather_context(autorizacao, atual)
        conferir('o resumo recebe os textos encurtados',
                 all(len(t['free_text'] or '') <= 2500 + 40 for t in resumo['timeline']))

        conteudo, _, recorte = relatorio.montar_contexto(autorizacao_p, pac)
        total = sum(len(a.get(c) or '') for a in conteudo['atendimentos'] for c in ('free_text', 'hpi', 'plan_text',
                                                                                    'impressions', 'chief_complaint'))
        conferir('o relatório cabe no teto total', total <= relatorio.TETO_DE_CARACTERES, total)
        conferir('e o recorte diz quantos entraram e que houve texto encurtado',
                 recorte['atendimentos_lidos'] == len(conteudo['atendimentos']) and not recorte['completo']
                 and recorte['textos_encurtados'] > 0, recorte)

        texto = build_patient_context(autorizacao_p)
        conferir('o chat cabe nos 12 mil caracteres', len(texto) <= MAX_CONTEXT_CHARS + 40, len(texto))
        conferir('a medicação de hoje chega ao chat', 'LEVETIRACETAM ROTEIRO' in texto)
        conferir('e vem antes dos atendimentos',
                 texto.find('Medicações em uso') < texto.find('Atendimentos (mais recentes primeiro)'))
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('O que vai à IA: tudo confere.')
