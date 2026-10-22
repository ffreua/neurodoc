from celery import shared_task
import logging

from .chat_models import ChatMessage
from .chat_services import fail_assistant_message, finalize_assistant_message
from .models import AIJob, AIJobStatus
from .context import AIAuthorizationDenied
from .providers import (
    ProviderUnavailable, descrever_falha, get_chat_model, installation_reserve_model,
    registrar_uso_da_reserva, reserva_utilizavel,
)
from .rendering import render_markdown
from .services import JobNotRunnable, run_job
from .streaming import publish_event

logger = logging.getLogger(__name__)


def _notify_job_completion(job):
    if job.status not in {
        AIJobStatus.SUCCEEDED, AIJobStatus.FAILED, AIJobStatus.STALE,
        AIJobStatus.BLOCKED_PRIVACY, AIJobStatus.CANCELLED,
    }:
        return
    from notifications.models import Notification
    from notifications.services import notify_user

    kind = 'ai_job_succeeded' if job.status == AIJobStatus.SUCCEEDED else 'ai_job_failed'
    if Notification.objects.filter(
        tenant_id=job.tenant_id, user_id=job.user_id, kind=kind,
        target_type='ai_job', target_id=job.id,
    ).exists():
        return
    if job.status == AIJobStatus.SUCCEEDED:
        title = 'Tarefa de IA concluída'
    else:
        title = 'A tarefa de IA não foi concluída'
    notify_user(
        job.tenant, job.user_id, kind=kind, sanitized_title=title,
        target_type='ai_job', target_id=job.id,
    )


@shared_task(name='ai.tasks.run_ai_job', expires=900)
def run_ai_job(job_id):
    try:
        artifact = run_job(job_id)
    except JobNotRunnable:
        return {'status': 'skipped'}
    except Exception:
        logger.exception('Unexpected AI job failure', extra={'job_id': str(job_id)})
        job = AIJob.objects.filter(id=job_id).first()
        if job is not None and job.status in (AIJobStatus.QUEUED, AIJobStatus.RUNNING):
            job.status = AIJobStatus.FAILED
            job.status_detail = 'A tarefa não foi concluída. Tente novamente.'
            job.save(update_fields=['status', 'status_detail'])
        if job is not None:
            _notify_job_completion(job)
        return {'status': 'failed'}

    job = AIJob.objects.filter(id=job_id).first()
    if job is not None:
        _notify_job_completion(job)

    if artifact is None:
        return {'status': job.status if job else 'unknown'}
    return {'status': AIJobStatus.SUCCEEDED, 'artifact_id': str(artifact.id)}


@shared_task(name='ai.tasks.prepare_document_and_run')
def prepare_document_and_run(job_id):
    """Esvazia a fila da leitura de laudo, que saiu na 1.18.

    A tarefa preparava o PDF (antivírus, OCR) e rodava a leitura. Ela fica
    registrada com o mesmo nome só para a mensagem antiga que ainda estiver
    no broker na hora da publicação: sem tarefa com esse nome, o worker a
    descartaria com "unregistered task" e o job ficaria "na fila" até a
    retomada desistir dele, um dia depois. Assim ele é encerrado na hora,
    com a explicação.
    """
    from .services import LEITURA_RETIRADA

    atualizados = AIJob.objects.filter(id=job_id, status=AIJobStatus.QUEUED).update(
        status=AIJobStatus.CANCELLED, status_detail=LEITURA_RETIRADA,
    )
    return {'status': 'cancelled' if atualizados else 'skipped'}


def _build_chat_messages(session, user_text):
    """Monta o que vai ao provedor nesta volta da conversa.

    Reconstroi a autorizacao a partir do dono da sessao e do paciente
    dela, revalidando contra o banco -- `build_ai_authorization` recusa
    vinculo inativo e paciente de outro inquilino.

    Sessao sem paciente segue sem autorizacao clinica: nao ha prontuario a
    consultar, e o prompt diz isso ao modelo em vez de deixa-lo supor.
    """
    from types import SimpleNamespace

    from .chat_prompt import build_chat_prompt
    from .context import build_ai_authorization

    autorizacao = None
    if session.patient_id:
        contexto = SimpleNamespace(
            tenant_id=session.tenant_id,
            user_id=session.owner_user_id,
            membership_id=_membership_id_of(session),
        )
        autorizacao = build_ai_authorization(contexto, patient_id=session.patient_id)

    mensagens, _ = build_chat_prompt(session, user_text, authorization=autorizacao)
    return mensagens


def _avaliar_privacidade(session, mensagens):
    """A politica de privacidade sobre tudo o que esta conversa mandaria.

    O texto avaliado e o das mensagens ja montadas -- instrucao, prontuario
    desidentificado, historico e a pergunta --, porque e exatamente isso
    que sairia da clinica.

    O atendimento passado a politica e o que **documenta consanguinidade**,
    quando existe: a regra do `ai/services.py` olha o atendimento do job, e
    a conversa nao tem um. Pegar o mais recente qualquer deixaria a porta
    aberta por sorte de ordenacao; pegar justamente o que dispara a regra e
    o unico jeito de a decisao ser a mesma nos dois caminhos.
    """
    from clinical.models import ConsanguinityState, Encounter

    from . import privacy_policy

    encounter = None
    if session.patient_id:
        encounter = (
            Encounter.objects
            .filter(tenant_id=session.tenant_id, patient_id=session.patient_id,
                    consanguinity_state=ConsanguinityState.CONFIRMED)
            .exclude(consanguinity_details='')
            .order_by('-occurred_at')
            .first()
        )
    texto = '\n'.join(
        m.content if hasattr(m, 'content') else str(m) for m in mensagens
    )
    return privacy_policy.evaluate_privacy_policy(encounter, texto)


def _membership_id_of(session):
    """O vinculo do dono da sessao nesta clinica, revalidado agora.

    Vinculo ativo nao basta, e era so isso que se conferia aqui: tirar o
    papel medico de alguem deixa o vinculo **ativo** -- ele continua sendo
    da secretaria, do gerente. Uma tarefa ja enfileirada seguia adiante e
    entregava prontuario a quem tinha acabado de perder o direito de le-lo.
    A capacidade conferida e a mesma da view que abriu o chat e a mesma que
    `ai/sse.py` reconfere a cada volta do stream.
    """
    from tenancy.models import Membership, MembershipStatus
    from tenancy.permissions import Capability, capabilities_for
    from tenancy.plans import has_clinical_ai

    vinculo = (
        Membership.objects
        .select_related('tenant')
        .filter(
            tenant_id=session.tenant_id, user_id=session.owner_user_id,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )
    if vinculo is None:
        raise AIAuthorizationDenied('Vínculo inativo nesta organização.')
    capacidades = capabilities_for(
        vinculo.roles, clinically_enabled=vinculo.can_practice_clinically(),
        ai_contracted=has_clinical_ai(vinculo.tenant.plan),
    )
    if Capability.CLINICAL_AI not in capacidades:
        raise AIAuthorizationDenied('Vinculo sem capacidade de apoio clinico por IA')
    return vinculo.id


@shared_task(name='ai.tasks.run_chat_turn', expires=600)
def run_chat_turn(message_id, user_message_id):
    """Streams the reply token-by-token into the Redis Stream keyed by
    this message's id (RF-11.04) while accumulating the full text, then
    persists the final, sanitized content to Postgres regardless of
    whether any SSE client was even connected to see the stream live --
    the result must survive a Redis restart/TTL expiry untouched.

    O que vai ao provedor e montado **aqui**, e nao na view: instrucao de
    sistema, dados do prontuario do paciente da sessao, historico da
    conversa e a pergunta -- tudo desidentificado (`ai/chat_prompt.py`).

    Ate a versao anterior, `prompt` era a mensagem digitada e nada mais. O
    modelo respondia de memoria sobre um paciente que nunca viu, sem
    historico e sem passar pela desidentificacao que o caminho de analise
    ja aplicava.

    A autorizacao e **reconstruida do banco aqui dentro**, e nao recebida
    pronta: entre enfileirar e executar cabe uma revogacao de vinculo, e
    e esta a ultima chance de recusar antes de o prontuario sair.
    """
    message = ChatMessage.objects.select_related('session', 'session__patient').get(id=message_id)
    session = message.session
    tenant_id, user_id, job_id = session.tenant_id, session.owner_user_id, str(message.id)
    # A pergunta vem do banco pelo id, e não pelo broker: ver o comentário
    # em `ai/chat_views.py`. O filtro por sessão é o de sempre -- um id de
    # mensagem de outra conversa não busca nada aqui.
    user_text = ChatMessage.objects.filter(
        tenant_id=tenant_id, session_id=session.id, id=user_message_id,
    ).values_list('content', flat=True).first()
    if user_text is None:
        aviso = 'A pergunta desta conversa nao foi encontrada.'
        publish_event(tenant_id, user_id, session.id, job_id, 'error', {'message': aviso})
        fail_assistant_message(message, aviso)
        return {'status': 'failed', 'reason': 'user message not found'}

    try:
        prompt = _build_chat_messages(session, user_text)
    except AIAuthorizationDenied as exc:
        aviso = f'Acesso revogado antes de a resposta comecar: {exc}'
        publish_event(tenant_id, user_id, session.id, job_id, 'error', {'message': aviso})
        fail_assistant_message(message, aviso)
        return {'status': 'denied', 'reason': str(exc)}

    # A mesma politica que decide se um job pode sair, aplicada aqui.
    # Ate esta correcao ela morava so em `ai/services.py`: o chat
    # desidentificava o texto mas nunca perguntava se aquele conteudo podia
    # deixar a clinica, e era o caminho **mais** largo dos dois -- leva o
    # prontuario inteiro do paciente em escopo. Uma politica que cobre uma
    # porta e ignora a outra nao e uma politica.
    decisao = _avaliar_privacidade(session, prompt)
    if not decisao.allowed:
        publish_event(tenant_id, user_id, session.id, job_id, 'error',
                      {'message': decisao.reason})
        fail_assistant_message(message, decisao.reason)
        return {'status': 'blocked_privacy', 'reason': decisao.reason}

    accumulated = []

    def transmitir(modelo):
        for chunk in modelo.stream(prompt):
            text = chunk.content if hasattr(chunk, 'content') else str(chunk)
            if not text:
                continue
            accumulated.append(text)
            publish_event(tenant_id, user_id, session.id, job_id, 'delta', {'text': text})

    def falhar(exc):
        publish_event(tenant_id, user_id, session.id, job_id, 'error', {'message': str(exc)})
        fail_assistant_message(message, str(exc))
        return {'status': 'failed', 'reason': str(exc)}

    try:
        # `tenant_id` para o chat usar o provedor **daquela** clínica: a
        # conversa carrega prontuário, e mandá-la ao provedor da instalação
        # quando a clínica contratou o próprio enviaria o dado para um
        # destino que ninguém escolheu.
        chat_model = get_chat_model(tenant_id=tenant_id)
    except ProviderUnavailable as exc:
        falha_principal = exc
    else:
        falha_principal = None
        try:
            transmitir(chat_model)
        except Exception as exc:
            falha_principal = exc

    if falha_principal is not None:
        # A reserva da instalação entra **só antes da primeira palavra**:
        # depois que o médico já está lendo uma resposta, recomeçá-la com
        # outro provedor emendaria dois textos que não conversam entre si.
        # Ver o comentário de `base.models.InstallationSettings`.
        if accumulated or not reserva_utilizavel(tenant_id):
            return falhar(falha_principal)
        try:
            transmitir(installation_reserve_model())
        except Exception as exc_reserva:
            if accumulated:
                return falhar(exc_reserva)
            return falhar(ProviderUnavailable(
                f'O provedor de IA principal e o reserva falharam: {exc_reserva}'
            ))
        registrar_uso_da_reserva(
            tenant_id=tenant_id, user_id=user_id, origem='chat_message',
            objeto_id=message.id, falha=descrever_falha(falha_principal),
        )

    full_text = ''.join(accumulated)
    rendered_html = render_markdown(full_text)
    finalize_assistant_message(message, full_text, source_refs=[])
    publish_event(tenant_id, user_id, session.id, job_id, 'complete', {'html': rendered_html})

    from notifications.services import notify_user, patient_context

    # O paciente da conversa entra no contexto quando existe: o chat de
    # apoio pode ser sobre um paciente ou uma dúvida geral, e "sua conversa
    # tem uma nova resposta" nao distingue as duas em quem tem cinco
    # abertas. O **conteudo** da resposta nao entra, aqui como em nenhum
    # aviso.
    contexto = patient_context(session.patient) if session.patient_id else {}
    notify_user(
        session.tenant, user_id, kind='chat_reply_ready',
        sanitized_title=(
            f'Resposta da IA sobre {session.patient.full_name}'
            if session.patient_id else 'Resposta da IA na sua conversa'
        ),
        target_type='chat_session', target_id=session.id,
        context=contexto,
    )
    return {'status': 'complete', 'message_id': str(message.id)}


@shared_task(name='ai.tasks.verificar_provedor_da_instalacao', expires=600)
def verificar_provedor_da_instalacao():
    """Pergunta ao provedor da instalação o que ele oferece, e guarda.

    **Roda no worker porque é lá que a chave existe** (§2): o processo
    `app`, que serve o console, não recebe nenhuma chave de provedor. A
    tela não pode perguntar; ela lê o que esta tarefa gravou.

    Existe por um defeito de quarenta dias. O modelo padrão da instalação
    era digitado à mão no `.env`, o provedor o aposentou em 2026-08-26 e
    passou a responder `410 Gone`, e **ninguém tinha como saber**: não
    havia tela que mostrasse o padrão da instalação, nem verificação que
    o conferisse contra o catálogo do provedor. O erro só aparecia como
    "a tarefa não foi concluída" para o médico, no meio do atendimento.

    Duas perguntas, porque são duas falhas diferentes e quem resolve cada
    uma é uma pessoa diferente (é o mesmo par que a tela da clínica já
    usava, e que faltava aqui):

    - `list_models` diz **o que existe** — é o que acusa modelo
      aposentado, e o que alimenta a lista escolhível da tela;
    - `probe_model` manda uma pergunta mínima ao modelo escolhido — é o
      que prova a **chave** e o acesso àquele modelo em particular.

    Nunca levanta: o resultado da verificação é o próprio registro.
    Estourar aqui transformaria "o provedor está fora" num alarme de
    worker, que é o lugar onde ninguém procura por isso.
    """
    from django.utils import timezone

    from base.models import InstallationSettings
    from .providers import installation_api_key
    from .providers.catalog import PROVIDERS

    config = InstallationSettings.carregar()
    provedor, modelo, base_url = config.ia_da_instalacao()

    def gravar(ok, detalhe, modelos=None):
        config.ai_checked_at = timezone.now()
        config.ai_check_ok = ok
        config.ai_check_detail = detalhe[:300]
        campos = ['ai_checked_at', 'ai_check_ok', 'ai_check_detail', 'updated_at']
        if modelos is not None:
            config.ai_available_models = modelos
            campos.append('ai_available_models')
        config.save(update_fields=campos)
        return {'ok': ok, 'detalhe': detalhe[:300]}

    if provedor not in PROVIDERS:
        return gravar(False, f'O provedor {provedor!r} não está no catálogo.')

    chave = installation_api_key(provedor)
    if not chave:
        from .providers import installation_secret_name

        return gravar(False, (
            f'Nenhuma chave da instalação para {provedor}. Grave o secret '
            f'{installation_secret_name(provedor)} e republique.'
        ))

    ok, detalhe, modelos = _conferir_provedor(provedor, modelo, base_url, chave)
    return gravar(ok, detalhe, modelos)


def _conferir_provedor(provedor, modelo, base_url, chave):
    """As duas perguntas ao provedor: o que existe, e se o escolhido responde.

    Uma função só para o principal e a reserva: são a mesma conferência
    sobre configurações diferentes, e duas cópias divergiriam na primeira
    correção. Devolve `(ok, detalhe, modelos)` — `modelos` é `None` quando
    nem a lista chegou.
    """
    from .providers.catalog import ProviderProbeFailed, list_models, probe_model

    try:
        modelos = sorted(list_models(provedor, chave, base_url))
    except ProviderProbeFailed as exc:
        return False, f'Não foi possível listar os modelos: {exc}', None
    except Exception as exc:  # pragma: no cover - rede
        return False, f'Falha ao falar com o provedor: {type(exc).__name__}.', None

    if not modelo:
        return False, 'Nenhum modelo escolhido.', modelos
    if modelo not in modelos:
        return False, (
            f'O modelo {modelo} não está entre os {len(modelos)} que {provedor} oferece. '
            'Escolha outro na lista — provedor aposenta modelo sem avisar.'
        ), modelos

    try:
        probe_model(provedor, chave, modelo, base_url)
    except ProviderProbeFailed as exc:
        return False, f'O modelo está na lista, mas a chamada falhou: {exc}', modelos
    except Exception as exc:  # pragma: no cover - rede
        return False, f'Falha ao testar o modelo: {type(exc).__name__}.', modelos

    return True, f'{provedor} respondeu, e {modelo} está ativo.', modelos


@shared_task(name='ai.tasks.verificar_reserva_da_instalacao', expires=600)
def verificar_reserva_da_instalacao():
    """A mesma conferência do principal, sobre a reserva. Nunca levanta.

    Existe porque uma reserva que ninguém confere é a mesma armadilha do
    principal em 2026 com outro nome: ligada, aparentemente pronta, e
    quebrada justamente no dia em que for chamada.
    """
    from django.utils import timezone

    from base.crypto import SecretUnavailable
    from base.models import InstallationSettings
    from .providers.catalog import PROVIDERS, ProviderProbeFailed, assert_endereco_permitido

    config = InstallationSettings.carregar()

    def gravar(ok, detalhe, modelos=None):
        config.ai_reserva_checked_at = timezone.now()
        config.ai_reserva_check_ok = ok
        config.ai_reserva_check_detail = detalhe[:300]
        campos = ['ai_reserva_checked_at', 'ai_reserva_check_ok', 'ai_reserva_check_detail',
                  'updated_at']
        if modelos is not None:
            config.ai_reserva_modelos = modelos
            campos.append('ai_reserva_modelos')
        config.save(update_fields=campos)
        return {'ok': ok, 'detalhe': detalhe[:300]}

    provedor = config.ai_reserva_provider
    if not provedor:
        return gravar(False, 'Nenhum provedor reserva escolhido.')
    if provedor not in PROVIDERS:
        return gravar(False, f'O provedor {provedor!r} não está no catálogo.')
    if not config.ai_reserva_chave_cifrada:
        return gravar(False, 'Nenhuma chave gravada para a reserva.')
    if config.ai_reserva_base_url:
        try:
            assert_endereco_permitido(config.ai_reserva_base_url)
        except ProviderProbeFailed as exc:
            return gravar(False, f'Endereço recusado: {exc}')
    try:
        chave = config.reserva_api_key()
    except SecretUnavailable as exc:
        return gravar(False, f'A chave gravada não abre: {exc}')

    ok, detalhe, modelos = _conferir_provedor(
        provedor, config.ai_reserva_model, config.ai_reserva_base_url, chave,
    )
    return gravar(ok, detalhe, modelos)


#: Intervalo mínimo entre dois e-mails sobre a mesma falha: a vigilância
#: roda de hora em hora, e repetir o aviso a cada hora ensina a ignorá-lo.
ALERTA_REPETE_A_CADA_HORAS = 24


@shared_task(name='ai.tasks.vigiar_ia_da_instalacao', expires=1800)
def vigiar_ia_da_instalacao():
    """De hora em hora: confere o principal e a reserva, e avisa quem opera.

    É a peça que faltava em 2026. A verificação existia no console, mas só
    rodava quando alguém clicava -- e ninguém clica num botão sobre um
    defeito que não sabe que existe. Foram quarenta dias assim.

    O aviso vai por e-mail a todo superadministrador ativo, na passagem de
    "funcionando" para "falhou" e depois uma vez por dia enquanto durar.
    Diz se a reserva está cobrindo, porque isso muda a urgência: com a
    reserva ligada e verificada, as clínicas seguem atendidas.
    """
    from datetime import timedelta

    from django.utils import timezone

    from base.models import InstallationSettings

    principal = verificar_provedor_da_instalacao()
    reserva = None
    config = InstallationSettings.carregar()
    if config.reserva_configurada:
        reserva = verificar_reserva_da_instalacao()
        config = InstallationSettings.carregar()

    if principal.get('ok'):
        if config.ai_alerta_enviado_em is not None:
            config.ai_alerta_enviado_em = None
            config.save(update_fields=['ai_alerta_enviado_em', 'updated_at'])
        return {'principal': principal, 'reserva': reserva, 'alerta': False}

    agora = timezone.now()
    ultimo = config.ai_alerta_enviado_em
    if ultimo is not None and agora - ultimo < timedelta(hours=ALERTA_REPETE_A_CADA_HORAS):
        return {'principal': principal, 'reserva': reserva, 'alerta': False}

    enviados = _avisar_falha_da_ia(config, principal, reserva)
    config.ai_alerta_enviado_em = agora
    config.save(update_fields=['ai_alerta_enviado_em', 'updated_at'])
    return {'principal': principal, 'reserva': reserva, 'alerta': True, 'destinatarios': enviados}


def _avisar_falha_da_ia(config, principal, reserva):
    """O e-mail ao superadministrador. Só configuração, nunca dado clínico."""
    import logging

    from django.conf import settings
    from django.core.mail import send_mail

    from accounts.models import User

    destinos = list(
        User.objects.filter(is_superuser=True, is_active=True)
        .exclude(email='').values_list('email', flat=True)
    )
    if not destinos:
        return 0
    provedor, modelo, _ = config.ia_da_instalacao()
    if config.reserva_pronta and reserva and reserva.get('ok'):
        cobertura = (
            f'A reserva ({config.ai_reserva_provider} / {config.ai_reserva_model}) está '
            'ligada e respondeu na verificação: as clínicas que usam o padrão da '
            'instalação seguem atendidas por ela.'
        )
    elif config.reserva_pronta:
        cobertura = (
            'A reserva está ligada, mas a verificação dela também falhou: '
            + ((reserva or {}).get('detalhe') or 'sem detalhe.')
            + ' As clínicas que usam o padrão da instalação estão SEM IA.'
        )
    else:
        cobertura = (
            'A reserva não está ligada: as clínicas que usam o padrão da instalação '
            'estão SEM IA até o provedor voltar ou a configuração ser trocada.'
        )
    corpo = (
        'A verificação automática do provedor de IA da instalação falhou.\n\n'
        f'Provedor: {provedor}\nModelo: {modelo}\n'
        f'Resultado: {principal.get("detalhe")}\n\n'
        f'{cobertura}\n\n'
        f'Para conferir ou trocar: {settings.PUBLIC_BASE_URL.rstrip("/")}/instalacao/operacao/\n\n'
        'Este aviso se repete uma vez por dia enquanto a falha durar, e para '
        'sozinho quando a verificação voltar a passar.'
    )
    try:
        send_mail(
            '[NeuroDoc] A IA da instalação está falhando', corpo,
            settings.DEFAULT_FROM_EMAIL, destinos, fail_silently=False,
        )
    except Exception:  # pragma: no cover - o aviso nunca derruba a vigilância
        logging.getLogger(__name__).exception('Falha ao enviar o aviso de IA da instalação')
        return 0
    return len(destinos)


#: Um job na fila há mais que isto se perdeu no caminho até o worker.
#:
#: Tem de passar do `expires=900` de `run_ai_job`: antes disso a mensagem
#: original pode estar viva na fila, e reenfileirar seria pedir duas
#: vezes (o que `run_job` recusa, com o lock e a conferência do estado,
#: mas não há por que contar com isso).
JOB_PARADO_DEPOIS_DE_MINUTOS = 20
#: Depois disto o resultado já não serve ao atendimento que o pediu, e o
#: certo é deixar o médico pedir de novo -- não rodar sozinho dias depois.
JOB_ABANDONADO_DEPOIS_DE_HORAS = 24


@shared_task(name='ai.tasks.retomar_jobs_parados')
def retomar_jobs_parados():
    """Acha o job que ficou "na fila" sem nunca chegar ao worker.

    Três caminhos levam a isso, e nenhum deixava rastro: a publicação na
    fila falhando depois do commit; a mensagem descartada pelo `expires`
    quando a fila de IA atrasa mais de quinze minutos; e, até a auditoria
    de 2026-10-09 (A3), o resumo automático publicado antes de o job
    existir para o worker. O job ficava `queued` para sempre, e
    `create_job` não reabre job `queued` -- o botão de pedir de novo não
    fazia nada.

    Entre vinte minutos e um dia, reenfileira pelo mesmo caminho do pedido.
    Depois de um dia, encerra como falha com a explicação, e o médico pede
    de novo se ainda quiser.
    """
    from django.utils import timezone

    from .models import TIPOS_APOSENTADOS
    from .services import LEITURA_RETIRADA

    agora = timezone.now()
    parados = AIJob.objects.filter(
        status=AIJobStatus.QUEUED,
        updated_at__lt=agora - timezone.timedelta(minutes=JOB_PARADO_DEPOIS_DE_MINUTOS),
    )
    retomados = abandonados = 0
    limite_retomada = agora - timezone.timedelta(minutes=JOB_PARADO_DEPOIS_DE_MINUTOS)
    for job in parados.order_by('updated_at')[:50]:
        # Leitura de laudo parada na fila (tipo aposentado na 1.18): não
        # volta para a fila, é encerrada com a explicação.
        if job.kind in TIPOS_APOSENTADOS:
            AIJob.objects.filter(id=job.id, status=AIJobStatus.QUEUED).update(
                status=AIJobStatus.CANCELLED, status_detail=LEITURA_RETIRADA,
            )
            abandonados += 1
            continue
        # O prazo de um dia conta do `updated_at`, que é quando o pedido
        # entrou na fila (ou foi reaberto), e esta rotina **não o toca**. A
        # primeira versão o renovava a cada retomada, e com a fila caída o
        # job nunca completava um dia de idade: ficava "na fila" para
        # sempre, que era o que ela existia para impedir (auditoria de
        # 2026-10-09, ND-1121-012). A última retomada mora à parte, em
        # `limits`, e só serve para não republicar a cada dez minutos.
        if job.updated_at < agora - timezone.timedelta(hours=JOB_ABANDONADO_DEPOIS_DE_HORAS):
            atualizados = AIJob.objects.filter(id=job.id, status=AIJobStatus.QUEUED).update(
                status=AIJobStatus.FAILED,
                status_detail='A tarefa ficou na fila e não chegou a rodar. Peça de novo.',
                updated_at=agora,
            )
            if atualizados:
                job.refresh_from_db()
                _notify_job_completion(job)
                abandonados += 1
            continue
        ultima = (job.limits or {}).get('retomado_em')
        if ultima and timezone.datetime.fromisoformat(ultima) > limite_retomada:
            continue
        # Anotada antes de publicar: a próxima rodada só volta a este job
        # se ele continuar parado por mais vinte minutos. `update`, e não
        # `save`, para o `auto_now` não mover o prazo do dia.
        AIJob.objects.filter(id=job.id, status=AIJobStatus.QUEUED).update(
            limits={**(job.limits or {}), 'retomado_em': agora.isoformat()},
        )
        try:
            run_ai_job.delay(str(job.id))
        except Exception as exc:
            # Fila fora do ar: o job continua parado e entra na próxima
            # rodada; os outros desta rodada não pagam por ele.
            logger.error(
                'ai: job parado nao voltou para a fila',
                extra={'job_id': str(job.id), 'error_class': exc.__class__.__name__},
            )
            continue
        retomados += 1
    if retomados or abandonados:
        logger.warning(
            'ai: jobs parados na fila', extra={'retomados': retomados, 'abandonados': abandonados},
        )
    return {'retomados': retomados, 'abandonados': abandonados}
