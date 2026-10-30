import hashlib
import json
import logging
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinical.models import ConsanguinityState, Encounter
from patients.models import Patient
from tenancy.context import AccessContext

from . import deidentification, privacy_policy
from .context import AIAuthorizationDenied, build_ai_authorization
from .graphs import PROMPT_VERSION, build_graph, build_prompt
from .models import (
    TIPOS_APOSENTADOS, PATIENT_SOURCED_KINDS, AIArtifact, AIJob, AIJobKind, AIJobStatus,
    AIReviewState,
)
from .providers import (
    ProviderUnavailable, descrever_falha, get_chat_model, installation_reserve_model,
    registrar_uso_da_reserva, reserva_utilizavel,
)
from .schemas import SCHEMA_VERSION
from .tools import clinical as clinical_tools

DEFAULT_LIMITS = {'timeout_seconds': 30, 'max_output_chars': 20000}

#: Escrever um relatorio sobre vinte atendimentos e mais lento que resumir
#: um, e a saida e prosa, nao campo estruturado: o teto do resumo cortaria
#: o relatorio no meio de uma secao, e um relatorio truncado e pior que
#: nenhum -- quem revisa nao tem como saber o que faltou.
REPORT_LIMITS = {'timeout_seconds': 240, 'max_output_chars': 30000}


logger = logging.getLogger(__name__)


#: O que o médico lê no job antigo de leitura de laudo que chegar ao worker.
LEITURA_RETIRADA = (
    'A leitura de laudo por IA foi retirada do sistema. O exame continua '
    'registrado; inclua os valores e o laudo à mão.'
)


class JobNotRunnable(Exception):
    pass


def _limits_for(kind):
    if kind == AIJobKind.PATIENT_REPORT:
        return dict(REPORT_LIMITS)
    return dict(DEFAULT_LIMITS)


@transaction.atomic
def create_job(access_context, kind, purpose, patient_id=None, encounter_id=None, target_ref=None):
    """Registra o pedido de uma tarefa de IA. Não executa nada.

    A chave de idempotência amarra o pedido à **fonte** dele, e isso muda
    com o tipo: para resumo e apoio diagnóstico a fonte é a versão do
    atendimento (mudou o prontuário, é outro pedido); para leitura de laudo
    a fonte é o documento, e a versão do atendimento fica de fora — se ela
    entrasse, corrigir uma vírgula na conduta faria a extração do PDF
    aparecer como desatualizada.
    """
    if kind in TIPOS_APOSENTADOS:
        # A leitura de laudo saiu na 1.18 (`ai/models.py::TIPOS_APOSENTADOS`).
        # Nenhuma tela pede mais, e um caminho esquecido que pedisse criaria
        # um job que o worker só cancelaria.
        raise ValueError(f'Tarefa de IA retirada do sistema: {kind}')
    authorization = build_ai_authorization(access_context, patient_id, encounter_id)

    encounter = Encounter.objects.filter(id=authorization.encounter_id).first() if authorization.encounter_id else None
    target_ref = target_ref or {}
    if kind in PATIENT_SOURCED_KINDS:
        # O paciente sozinho nao distingue um relatorio do outro. O que
        # distingue e a finalidade e o texto que o medico escreveu,
        # resumidos em `ref` por `relatorio.referencia_do_pedido`. Sem
        # isso o segundo relatorio do mesmo paciente cairia na chave do
        # primeiro e nao rodaria: a tela mostraria o relatorio antigo
        # como se fosse a resposta ao pedido novo.
        source_version = 0
        target = f"{authorization.patient_id}:{target_ref.get('ref', '')}"
    else:
        source_version = encounter.row_version if encounter else 0
        target = authorization.encounter_id or authorization.patient_id
    idempotency_key = f'{kind}:{target}:{source_version}'[:150]

    job, _ = AIJob.objects.get_or_create(
        tenant_id=access_context.tenant_id, idempotency_key=idempotency_key,
        defaults={
            'user_id': authorization.user_id, 'membership_id': authorization.membership_id,
            'patient_id': authorization.patient_id, 'encounter_id': authorization.encounter_id,
            'kind': kind, 'source_version': source_version, 'purpose': purpose[:255],
            'target_ref': target_ref,
            'policy_version': privacy_policy.POLICY_VERSION,
            'status': AIJobStatus.QUEUED if settings.AI_ENABLED else AIJobStatus.DISABLED,
            'limits': _limits_for(kind),
        },
    )
    # Pedido repetido sobre a mesma fonte reaproveita a linha, mas um job que
    # falhou tem de poder ser tentado de novo: sem isso o médico ficaria preso
    # a uma falha de rede com o botão inerte e sem explicação.
    if job.status in (AIJobStatus.FAILED, AIJobStatus.STALE, AIJobStatus.CANCELLED, AIJobStatus.DISABLED):
        job.status = AIJobStatus.QUEUED if settings.AI_ENABLED else AIJobStatus.DISABLED
        job.status_detail = ''
        job.cancel_requested_at = None
        # `updated_at` junto: é por ele que `retomar_jobs_parados` mede
        # há quanto tempo o job espera, e `auto_now` não anda quando o
        # campo fica de fora de `update_fields`.
        job.save(update_fields=['status', 'status_detail', 'cancel_requested_at', 'updated_at'])
    record_audit_event(
        authorization.user_id, access_context.tenant_id, 'ai.job_created',
        object_type='ai_job', object_id=job.id, outcome='success',
    )
    return job


def _gather_context(authorization, encounter):
    if encounter is None:
        return {}, []
    timeline = clinical_tools.get_patient_timeline(authorization, limit=5)
    findings = clinical_tools.get_examination_findings(authorization, encounter.id)
    diagnoses = clinical_tools.get_diagnoses(authorization, encounter.id)
    context = {'timeline': timeline, 'examination_findings': findings, 'diagnoses': diagnoses}
    source_refs = [{'type': 'encounter', 'id': str(encounter.id), 'version_or_hash': str(encounter.row_version)}]
    return context, source_refs


def _gather_diagnostic_context(authorization, encounter):
    """Caso completo para o apoio ao raciocínio.

    Mais largo que o do resumo de propósito: medicação em uso, resultado de
    exame e o exame neurológico com rótulo legível são exatamente o que
    diferencia uma lista de hipóteses defensável de um chute a partir da
    queixa. E o exame vem com rótulo, não com o caminho do nó no roteiro.
    """
    if encounter is None:
        return {}, []
    current = {
        'data': encounter.occurred_at.isoformat(),
        'queixa_principal': encounter.chief_complaint,
        'historia_da_doenca_atual': encounter.hpi,
        'antecedentes_pessoais': encounter.personal_history,
        'antecedentes_familiares': encounter.family_history,
        'exame_neurologico_texto_livre': encounter.neurological_exam_text,
        'conduta_registrada': encounter.plan_text,
    }
    # Atendimento de texto livre: o corpo da consulta e as impressões são
    # estes dois campos, e os estruturados acima vêm vazios. Ficavam de
    # fora — o apoio diagnóstico recebia um atendimento em branco e
    # respondia assim mesmo.
    if encounter.free_text.strip():
        current['consulta_texto_livre'] = encounter.free_text
    if encounter.impressions.strip():
        current['impressoes_do_medico'] = encounter.impressions
    # A consanguinidade entra só quando foi de fato informada. O rótulo do
    # campo é ele próprio um marcador de risco na política de privacidade
    # (fail-closed, P-06 em aberto): mandá-lo mesmo quando ninguém respondeu
    # bloquearia o apoio diagnóstico em todo atendimento, para sempre. Quando
    # há resposta, ela vai e o bloqueio acontece — que é o comportamento
    # desejado.
    # Hábitos e vícios só entram quando foram preenchidos. Sem resposta, o
    # rótulo sozinho não informa nada e ainda ocupa o contexto; com
    # resposta, ele muda conduta — álcool, sono e outras substâncias
    # explicam crise e interagem com anticonvulsivante.
    if encounter.habits_history:
        current['habitos_e_vicios'] = encounter.habits_history
    if encounter.consanguinity_state != ConsanguinityState.NOT_INFORMED:
        current['consanguinidade'] = encounter.get_consanguinity_state_display()
        if encounter.consanguinity_details:
            current['consanguinidade_detalhes'] = encounter.consanguinity_details
    context = {
        'atendimento_atual': current,
        'medicacoes_em_uso': clinical_tools.get_medications(authorization, encounter.id),
        'exame_neurologico': clinical_tools.get_examination_findings(authorization, encounter.id),
        'resultados_de_exames': clinical_tools.get_exam_results(authorization),
        'hipoteses_ja_registradas': clinical_tools.get_diagnoses(authorization, encounter.id),
        'consultas_anteriores': clinical_tools.get_patient_timeline(authorization, limit=5),
    }
    source_refs = [
        {'type': 'encounter', 'id': str(encounter.id), 'version_or_hash': str(encounter.row_version)},
    ]
    return context, source_refs


def _gather_patient_report_context(authorization, patient, job):
    """Prontuario do paciente, a finalidade e o pedido do medico.

    Devolve `(contexto, source_refs, extras, recorte)`. Os `extras` sao
    o que o prompt do relatorio precisa alem do contexto -- a unica
    tarefa que precisa de algo assim -- e o `recorte` e o que a tela
    mostra ao medico antes de ele assinar: quanto do prontuario coube.
    """
    from . import relatorio

    alvo = job.target_ref or {}
    escolhida = relatorio.finalidade(alvo.get('finalidade'))
    contexto, source_refs, recorte = relatorio.montar_contexto(authorization, patient)
    extras = {
        'destinatario': escolhida.destinatario,
        'orientacao': escolhida.orientacao,
        'pedido': (alvo.get('pedido') or '').strip() or 'Relatorio clinico geral.',
        'secoes': '; '.join(escolhida.secoes) or 'defina voce as secoes.',
    }
    return contexto, source_refs, extras, recorte


def _provenance_of(chat_model, tenant_id):
    """Provedor e modelo que produziram este artefato.

    A clínica tem prioridade porque foi ela que escolheu; a instalação
    responde por quem não configurou o próprio. O nome do modelo vem do
    cliente já montado, e não da configuração, para o registro não divergir
    do que a chamada usou de fato.
    """
    from .models import AIProviderSettings

    model_name = getattr(chat_model, 'model_name', None) or getattr(chat_model, 'model', None)
    row = AIProviderSettings.objects.filter(tenant_id=tenant_id).first()
    if row is not None and row.is_usable:
        return row.provider, str(model_name or row.model)
    # O padrão da instalação vem do console, não do `.env` — e registrar
    # `settings.AI_MODEL` aqui gravaria no artefato um modelo que pode não
    # ser o que respondeu, que é o oposto do que proveniência serve.
    from base.models import InstallationSettings

    provider, model, _ = InstallationSettings.carregar().ia_da_instalacao()
    return provider, str(model_name or model)


#: Acima disto o provedor esta instavel; daqui para baixo, mal
#: configurado. 408 e 429 sao a excecao dentro do 4xx: prazo e limite de
#: taxa passam sozinhos, e repetir e de fato o que se deve fazer.
_ESTADOS_QUE_PASSAM = {408, 429}

#: Quanto um job pode gastar falando com provedores, somando o principal e
#: a reserva. Abaixo do `CELERY_TASK_SOFT_TIME_LIMIT` (300 s) com folga: o
#: relatório tem 240 s de prazo próprio, e o principal que esgota esse
#: prazo deixa pouco tempo para a reserva -- passar do limite do Celery
#: mataria o job sem gravar falha nenhuma.
_ORCAMENTO_DO_JOB = 270
#: Menos que isto para a reserva e não vale tentar: ela começaria uma
#: chamada que não teria como terminar, e a falha chegaria igual.
_PRAZO_MINIMO_DA_RESERVA = 15


def _falha_do_provedor(exc, job):
    """Traduz a recusa do provedor numa frase útil e num diagnóstico.

    Útil quer dizer: que diga a quem lê se vale tentar de novo. "A tarefa
    não foi concluída. Tente novamente." dito sobre um modelo que o
    provedor aposentou é pior do que não dizer nada — manda a secretária
    repetir indefinidamente uma operação que não pode dar certo, e
    esconde de quem opera o servidor a única coisa que resolveria.

    O diagnóstico não carrega a chave: `status_code` e o nome do modelo
    são o que o provedor devolve de útil, e nenhum dos dois é segredo.
    """
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    if status is None:
        status = getattr(exc, 'status_code', None)
    configuracao = isinstance(status, int) and 400 <= status < 500 and status not in _ESTADOS_QUE_PASSAM

    try:
        from base.models import InstallationSettings

        provedor, modelo, _ = InstallationSettings.carregar().ia_da_instalacao()
    except Exception:  # pragma: no cover - diagnóstico nunca derruba o job
        provedor, modelo = '', ''

    diagnostico = {
        'etapa': 'chamada_ao_provedor',
        'status_http': status,
        'excecao': type(exc).__name__,
        'provedor_da_instalacao': provedor,
        'modelo_da_instalacao': modelo,
        'configuracao': configuracao,
    }
    if configuracao:
        detalhe = (
            'O provedor de IA recusou a chamada por configuração '
            f'(HTTP {status}). Repetir não resolve: quem administra a instalação '
            'precisa conferir o provedor e o modelo em Operação.'
        )
    else:
        detalhe = (
            'O provedor de IA não respondeu'
            + (f' (HTTP {status})' if status else '')
            + '. Tente novamente em alguns minutos.'
        )
    logger.warning(
        'Falha do provedor de IA', extra={
            'job_id': str(job.id), 'status': status, 'provider': provedor, 'model': modelo,
        },
    )
    return detalhe, diagnostico


def _previous_artifact(job):
    qs = AIArtifact.objects.filter(job__tenant_id=job.tenant_id, job__kind=job.kind)
    if job.encounter_id:
        qs = qs.filter(job__encounter_id=job.encounter_id)
    else:
        qs = qs.filter(job__patient_id=job.patient_id, job__encounter_id__isnull=True)
    return qs.exclude(job_id=job.id).order_by('-created_at').first()


def _fail(job, status, detail, action, diagnostics=None):
    """Encerra o job em falha, com o motivo legível e a forma recusada.

    `detail` é o que o médico lê na linha do exame; `diagnostics` é o que
    quem conserta precisa, e não contém valor do laudo (ver
    `AIJob.failure_diagnostics`). Os dois juntos porque separados não
    serviram: por três semanas a tela mostrou ao médico o texto cru de um
    `ValidationError` do Pydantic, em inglês, e nem assim deu para saber o
    que o modelo tinha devolvido.
    """
    job.status = status
    job.status_detail = detail[:255]
    job.failure_diagnostics = diagnostics or {}
    job.save(update_fields=['status', 'status_detail', 'failure_diagnostics'])
    record_audit_event(job.user_id, job.tenant_id, action, object_type='ai_job', object_id=job.id, outcome='denied')
    return None


@transaction.atomic
def run_job(job_id):
    """Called from the Celery task, never inline in the request. Every
    authorization/staleness check is redone here against the current
    database state -- the job row is a *request*, not a pre-approved
    ticket: a membership revoked or an encounter changed after `create_job`
    must still block the actual external call.
    """
    job = AIJob.objects.select_for_update().get(id=job_id)
    if job.status != AIJobStatus.QUEUED:
        raise JobNotRunnable(f'Job {job.id} is {job.status}, not queued')
    if job.kind in TIPOS_APOSENTADOS:
        return _fail(job, AIJobStatus.CANCELLED, LEITURA_RETIRADA, 'ai.job_cancelled')

    fake_context = AccessContext(
        user_id=job.user_id, tenant_id=job.tenant_id, membership_id=job.membership_id,
        permissions=frozenset(), request_id=uuid.uuid4(),
    )
    try:
        authorization = build_ai_authorization(fake_context, job.patient_id, job.encounter_id)
    except AIAuthorizationDenied as exc:
        return _fail(job, AIJobStatus.FAILED, str(exc), 'ai.job_authorization_denied')

    encounter = Encounter.objects.filter(id=job.encounter_id).first() if job.encounter_id else None
    if job.encounter_id and encounter is None:
        return _fail(job, AIJobStatus.FAILED, 'Atendimento não encontrado.', 'ai.job_failed')
    if job.encounter_id and encounter.row_version != job.source_version:
        return _fail(job, AIJobStatus.STALE, 'Source changed since the job was queued', 'ai.job_stale')

    patient = Patient.objects.filter(id=job.patient_id).first() if job.patient_id else None
    prompt_extras, recorte = {}, None

    if job.kind == AIJobKind.PATIENT_REPORT:
        if patient is None:
            return _fail(job, AIJobStatus.FAILED, 'Paciente nao encontrado.', 'ai.job_failed')
        context, source_refs, prompt_extras, recorte = _gather_patient_report_context(
            authorization, patient, job,
        )
        raw_context = json.dumps(context, ensure_ascii=False, indent=1)
    elif job.kind == AIJobKind.DIAGNOSTIC_SUPPORT:
        context, source_refs = _gather_diagnostic_context(authorization, encounter)
        raw_context = json.dumps(context, ensure_ascii=False, indent=1)
    else:
        context, source_refs = _gather_context(authorization, encounter)
        raw_context = json.dumps(context, ensure_ascii=False)

    deidentified_text = deidentification.deidentify_text(raw_context, patient)

    # A confirmacao do medico mora no proprio pedido, e so o relatorio e o
    # apoio diagnostico a escrevem: `request_patient_report` e
    # `request_diagnostic_support` so a gravam depois de a tela ter mostrado
    # qual marcador foi encontrado. O resumo automatico nao tem como chegar
    # aqui com ela.
    decision = privacy_policy.evaluate_privacy_policy(
        encounter, deidentified_text,
        risco_confirmado=bool((job.target_ref or {}).get('risco_confirmado')),
    )
    if not decision.allowed:
        return _fail(job, AIJobStatus.BLOCKED_PRIVACY, decision.reason, 'ai.job_blocked_privacy')

    job.source_hash = hashlib.sha256(deidentified_text.encode()).hexdigest()
    job.status = AIJobStatus.RUNNING
    job.save(update_fields=['source_hash', 'status'])

    prompt = build_prompt(job.kind, deidentified_text, extras=prompt_extras)
    max_output_chars = job.limits.get('max_output_chars', 20000)
    limite = job.limits.get('timeout_seconds', 30)
    inicio = time.monotonic()

    def executar(modelo, prazo):
        grafo = build_graph(modelo, job.kind, max_output_chars=max_output_chars)
        return grafo.invoke({
            'prompt': prompt, 'timeout_seconds': prazo,
            'raw_response': None, 'artifact': None, 'error': None, 'diagnostics': None,
        })

    # O provedor pode recusar a chamada inteira, e isso **não** é "tente
    # novamente". Em 2026-08-26 a NVIDIA aposentou o modelo que era o
    # padrão da instalação e passou a responder `410 Gone`; a exceção
    # subia até o `except Exception` de `run_ai_job`, que gravava "A
    # tarefa não foi concluída. Tente novamente." -- conselho que nunca
    # ia funcionar, sobre uma causa que ninguém na clínica podia
    # resolver. Quarenta dias assim, numa clínica que depende do padrão
    # da instalação por não ter chave própria.
    #
    # O código de estado é o que separa os dois mundos: 4xx é
    # configuração (modelo aposentado, chave recusada, crédito acabado) e
    # pedir para repetir é errado; o resto é instabilidade, e aí repetir
    # é o conselho certo.
    usou_reserva = False
    try:
        chat_model = get_chat_model(tenant_id=job.tenant_id)
    except ProviderUnavailable as exc:
        chat_model, falha_principal = None, exc
    else:
        falha_principal = None
        try:
            result_state = executar(chat_model, limite)
        except Exception as exc:
            falha_principal = exc
        else:
            if (result_state.get('diagnostics') or {}).get('tempo_esgotado'):
                falha_principal = TimeoutError(result_state.get('error') or 'tempo esgotado')

    if falha_principal is not None:
        # A reserva da instalação, quando ligada e quando esta clínica usa o
        # padrão. Só aqui, depois de o principal **falhar na chamada** --
        # nunca porque a resposta veio e não passou na validação.
        prazo_reserva = min(limite, int(_ORCAMENTO_DO_JOB - (time.monotonic() - inicio)))
        prazo_minimo = min(_PRAZO_MINIMO_DA_RESERVA, limite)
        if reserva_utilizavel(job.tenant_id) and prazo_reserva >= prazo_minimo:
            try:
                chat_model = installation_reserve_model()
                result_state = executar(chat_model, prazo_reserva)
            except Exception as exc_reserva:
                detalhe, diagnostico = _falha_do_provedor(exc_reserva, job)
                diagnostico['reserva'] = True
                diagnostico['principal'] = descrever_falha(falha_principal)
                return _fail(
                    job, AIJobStatus.FAILED,
                    'O provedor de IA principal e o reserva falharam. ' + detalhe,
                    'ai.job_provider_error', diagnostics=diagnostico,
                )
            usou_reserva = True
            registrar_uso_da_reserva(
                tenant_id=job.tenant_id, user_id=job.user_id, origem='ai_job',
                objeto_id=job.id, falha=descrever_falha(falha_principal),
            )
        elif chat_model is None:
            return _fail(job, AIJobStatus.FAILED, str(falha_principal),
                         'ai.job_provider_unavailable')
        elif isinstance(falha_principal, TimeoutError):
            return _fail(
                job, AIJobStatus.FAILED, result_state['error'], 'ai.job_failed',
                diagnostics=result_state.get('diagnostics'),
            )
        else:
            detalhe, diagnostico = _falha_do_provedor(falha_principal, job)
            return _fail(job, AIJobStatus.FAILED, detalhe, 'ai.job_provider_error',
                         diagnostics=diagnostico)

    if result_state.get('error'):
        return _fail(
            job, AIJobStatus.FAILED, result_state['error'], 'ai.job_failed',
            diagnostics=result_state.get('diagnostics'),
        )

    artifact_data = dict(result_state['artifact'])
    artifact_data['source_refs'] = source_refs or artifact_data.get('source_refs', [])
    if recorte is not None:
        # Quanto do prontuario coube no relatorio fica gravado junto com
        # ele, e nao so na tela de revisao: daqui a um ano, a pergunta
        # sobre um relatorio assinado vai ser exatamente esta.
        artifact_data['recorte_do_prontuario'] = recorte
    # Proveniência é o que foi de fato usado, não o que a instalação tem
    # configurado. Com provedor por clínica, gravar `settings.AI_PROVIDER`
    # registraria o provedor errado em toda clínica que informou o seu — e
    # a revisão do médico depende de saber de onde a sugestão veio.
    if usou_reserva:
        # Quem respondeu foi a reserva, e é ela que o médico precisa ver ao
        # revisar -- proveniência é o que foi de fato usado.
        from base.models import InstallationSettings

        reserva = InstallationSettings.carregar()
        used_provider = reserva.ai_reserva_provider
        used_model = str(getattr(chat_model, 'model_name', None)
                         or getattr(chat_model, 'model', None) or reserva.ai_reserva_model)
    else:
        used_provider, used_model = _provenance_of(chat_model, job.tenant_id)
    artifact = AIArtifact.objects.create(
        tenant_id=job.tenant_id, job=job, schema_version=SCHEMA_VERSION, provider=used_provider,
        model=used_model, prompt_version=PROMPT_VERSION, source_refs=artifact_data['source_refs'],
        result=artifact_data, supersedes=_previous_artifact(job),
    )
    job.status = AIJobStatus.SUCCEEDED
    job.save(update_fields=['status'])
    record_audit_event(
        job.user_id, job.tenant_id, 'ai.job_succeeded',
        object_type='ai_job', object_id=job.id, outcome='success',
    )
    return artifact


def request_diagnostic_support(access_context, encounter, purpose='Apoio ao raciocínio diagnóstico',
                               risco_confirmado=False):
    """Pede a análise do caso para apoio às hipóteses (RF-11.05).

    `risco_confirmado` é a mesma porta do relatório (`request_patient_report`),
    aberta em 2026-10-29: o apoio diagnóstico de um caso de neurogenética
    era bloqueado **sempre** — a consanguinidade respondida (inclusive "Não")
    vai ao contexto, e a palavra é marcador da política de privacidade. O
    médico que recusava a trava não tinha o que fazer; agora ele lê na tela
    qual marcador foi encontrado e decide, com a decisão na trilha. O padrão
    continua fechado: só a tela, depois do bloqueio, manda `True`.
    """
    job = create_job(
        access_context, AIJobKind.DIAGNOSTIC_SUPPORT, purpose,
        patient_id=encounter.patient_id, encounter_id=encounter.id,
    )
    if risco_confirmado and job.status == AIJobStatus.BLOCKED_PRIVACY:
        # O mesmo pedido (a chave é a versão do atendimento): reabre a linha
        # bloqueada em vez de criar outra, com a confirmação gravada nela.
        record_audit_event(
            access_context.user_id, access_context.tenant_id, 'ai.privacy_risk_confirmed',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'tarefa': AIJobKind.DIAGNOSTIC_SUPPORT, 'motivo': job.status_detail[:200]},
        )
        job.target_ref = dict(job.target_ref or {}, risco_confirmado=True)
        job.status = AIJobStatus.QUEUED if settings.AI_ENABLED else AIJobStatus.DISABLED
        job.status_detail = ''
        job.save(update_fields=['target_ref', 'status', 'status_detail', 'updated_at'])
    if job.status == AIJobStatus.QUEUED:
        from .tasks import run_ai_job

        transaction.on_commit(lambda: run_ai_job.delay(str(job.id)))
    return job


def latest_diagnostic_support(encounter):
    """Último artefato de apoio diagnóstico deste atendimento, ou None.

    Vem marcado com `is_stale` quando o prontuário mudou depois de gerado:
    hipótese calculada sobre um caso que já não é este não pode aparecer na
    tela como se ainda valesse.
    """
    job = AIJob.objects.filter(
        tenant_id=encounter.tenant_id, encounter_id=encounter.id,
        kind=AIJobKind.DIAGNOSTIC_SUPPORT,
    ).order_by('-created_at').first()
    if job is None:
        return None, None
    artifact = AIArtifact.objects.filter(job=job).order_by('-created_at').first()
    return job, artifact


def resumos_aprovados(encounter):
    """Resumos por IA deste atendimento que o médico aprovou, do mais novo.

    "Aceitar" é juízo editorial e nunca escreveu no prontuário — de
    propósito, a IA não escreve no registro clínico sozinha. Mas a única
    porta de volta ao texto aprovado era o aviso do sino, que a retenção
    apaga em 7 a 15 dias: depois disso o resumo continuava no banco sem
    nenhuma tela que levasse a ele. Ele aparece no atendimento, ao lado do
    registro e fora dele — não entra no texto clínico nem no `content_hash`.
    """
    return list(
        AIArtifact.objects.filter(
            tenant_id=encounter.tenant_id,
            job__encounter_id=encounter.id,
            job__kind=AIJobKind.ENCOUNTER_SUMMARY,
            review_state__in=(AIReviewState.ACCEPTED, AIReviewState.EDITED),
        ).select_related('job', 'reviewer__user').order_by('-reviewed_at')
    )


def cancel_job(job, actor_id):
    job.cancel_requested_at = timezone.now()
    if job.status in (AIJobStatus.QUEUED, AIJobStatus.RUNNING):
        job.status = AIJobStatus.CANCELLED
    job.save(update_fields=['cancel_requested_at', 'status'])
    record_audit_event(
        actor_id, job.tenant_id, 'ai.job_cancelled', object_type='ai_job', object_id=job.id, outcome='success',
    )
    return job


def request_patient_report(access_context, patient, codigo_finalidade, pedido,
                           risco_confirmado=False):
    """Pede o rascunho de um relatório sobre o paciente.

    `risco_confirmado` só chega aqui vindo da tela, depois de o médico ter
    lido qual marcador de privacidade foi encontrado e ter dito que quer
    prosseguir — e a confirmação entra na trilha de auditoria antes de o
    job ser enfileirado, não depois. Ver `ai/privacy_policy.py`.
    """
    from . import relatorio

    escolhida = relatorio.finalidade(codigo_finalidade)
    target_ref = {
        'finalidade': escolhida.codigo,
        'pedido': (pedido or '').strip()[:4000],
        'ref': relatorio.referencia_do_pedido(escolhida.codigo, pedido),
    }
    if risco_confirmado:
        target_ref['risco_confirmado'] = True
        # A chave muda junto: sem isso, confirmar o risco reaproveitaria a
        # linha do job que acabou de ser bloqueado -- que ja esta em
        # `blocked_privacy` e nao volta para a fila.
        target_ref['ref'] = relatorio.referencia_do_pedido(
            escolhida.codigo, f'{pedido}|confirmado',
        )
        record_audit_event(
            access_context.user_id, access_context.tenant_id, 'ai.privacy_risk_confirmed',
            object_type='patient', object_id=patient.id, outcome='success',
            integrity_metadata={'finalidade': escolhida.codigo},
        )
    job = create_job(
        access_context, AIJobKind.PATIENT_REPORT, escolhida.rotulo,
        patient_id=patient.id, target_ref=target_ref,
    )
    if job.status == AIJobStatus.QUEUED:
        from .tasks import run_ai_job

        transaction.on_commit(lambda: run_ai_job.delay(str(job.id)))
    return job
