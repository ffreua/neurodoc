from celery import shared_task

from .chat_models import ChatMessage
from .chat_services import fail_assistant_message, finalize_assistant_message
from .models import AIJob, AIJobStatus
from .context import AIAuthorizationDenied
from .providers import ProviderUnavailable, get_chat_model
from .rendering import render_markdown
from .services import JobNotRunnable, run_job
from .streaming import publish_event


@shared_task(name='ai.tasks.run_ai_job', expires=900)
def run_ai_job(job_id):
    try:
        artifact = run_job(job_id)
    except JobNotRunnable:
        return {'status': 'skipped'}

    job = AIJob.objects.filter(id=job_id).first()
    if job is not None:
        # A tela do prontuário lê o estado da leitura no próprio resultado de
        # exame, não na tabela de jobs; é aqui que os dois se reencontram,
        # tanto no sucesso quanto na falha.
        from .extraction import sync_exam_result_status

        sync_exam_result_status(job)

    if artifact is None:
        return {'status': job.status if job else 'unknown'}
    return {'status': AIJobStatus.SUCCEEDED, 'artifact_id': str(artifact.id)}


#: Um laudo recém-enviado ainda está na fila do antivírus. Esperar em vez de
#: falhar é o que faz o botão "ler o laudo" funcionar no mesmo gesto do envio.
SCAN_WAIT_SECONDS = 10
SCAN_MAX_ATTEMPTS = 30


@shared_task(name='ai.tasks.prepare_document_and_run', bind=True, max_retries=SCAN_MAX_ATTEMPTS, expires=1800)
def prepare_document_and_run(self, job_id):
    """Deixa o laudo legível e então roda a leitura.

    Três coisas acontecem antes da chamada ao modelo, e nenhuma delas pode
    ser pulada:

    1. **espera a verificação de malware.** Arquivo em quarentena não é
       aberto nem para ler texto.
    2. **roda o OCR local** quando o PDF não tem camada de texto — é o caso
       do laudo digitalizado, que é justamente o que se pede ao escanear. O
       OCR é o tesseract em pt-BR, na própria máquina; o arquivo não sai
       daqui.
    3. só então executa o job, que desidentifica o texto e faz a chamada.
    """
    from documents.models import AttachmentScanStatus
    from documents.ocr import OcrError, run_ocr

    from documents.storage import local_path

    from .documents import MIN_TEXT_LAYER_CHARS, _ocr_text, _pdf_text_layer

    def _text_layer_of(att):
        """Camada de texto do PDF, descomprimindo se preciso."""
        with local_path(att) as caminho:
            return _pdf_text_layer(caminho)

    from .extraction import sync_exam_result_status
    from .models import AIJobStatus

    job = AIJob.objects.filter(id=job_id).first()
    if job is None or job.status != AIJobStatus.QUEUED:
        return {'status': 'skipped'}

    from clinical.models import ExamResult

    exam_result = ExamResult.objects.filter(
        tenant_id=job.tenant_id, id=(job.target_ref or {}).get('exam_result_id'),
    ).select_related('attachment').first()
    attachment = exam_result.attachment if exam_result else None
    if attachment is None:
        job.status = AIJobStatus.FAILED
        job.status_detail = 'Laudo não encontrado para este exame.'
        job.save(update_fields=['status', 'status_detail'])
        sync_exam_result_status(job)
        return {'status': 'failed', 'reason': 'no attachment'}

    if attachment.scan_status == AttachmentScanStatus.REJECTED:
        job.status = AIJobStatus.FAILED
        job.status_detail = 'O laudo foi recusado na verificação de malware.'
        job.save(update_fields=['status', 'status_detail'])
        sync_exam_result_status(job)
        return {'status': 'failed', 'reason': 'rejected'}

    if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
        raise self.retry(countdown=SCAN_WAIT_SECONDS)

    # OCR só quando faz falta: laudo emitido por sistema tem camada de texto,
    # e rasterizar cem páginas à toa custa minutos de worker.
    needs_ocr = (
        attachment.original_name.lower().endswith('.pdf')
        and len(_text_layer_of(attachment).strip()) < MIN_TEXT_LAYER_CHARS
    ) or not attachment.original_name.lower().endswith('.pdf')
    if needs_ocr and len(_ocr_text(attachment).strip()) < MIN_TEXT_LAYER_CHARS:
        try:
            run_ocr(attachment)
        except OcrError as exc:
            job.status = AIJobStatus.FAILED
            job.status_detail = f'Não foi possível reconhecer o texto do laudo: {exc}'[:255]
            job.save(update_fields=['status', 'status_detail'])
            sync_exam_result_status(job)
            return {'status': 'failed', 'reason': 'ocr'}

    return run_ai_job(str(job.id))


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

    vinculo = Membership.objects.filter(
        tenant_id=session.tenant_id, user_id=session.owner_user_id,
        status=MembershipStatus.ACTIVE,
    ).first()
    if vinculo is None:
        raise AIAuthorizationDenied('Vinculo inativo nesta organizacao')
    capacidades = capabilities_for(
        vinculo.roles, clinically_enabled=vinculo.can_practice_clinically(),
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

    try:
        # `tenant_id` para o chat usar o provedor **daquela** clínica: a
        # conversa carrega prontuário, e mandá-la ao provedor da instalação
        # quando a clínica contratou o próprio enviaria o dado para um
        # destino que ninguém escolheu.
        chat_model = get_chat_model(tenant_id=tenant_id)
    except ProviderUnavailable as exc:
        publish_event(tenant_id, user_id, session.id, job_id, 'error', {'message': str(exc)})
        fail_assistant_message(message, str(exc))
        return {'status': 'failed', 'reason': str(exc)}

    accumulated = []
    try:
        for chunk in chat_model.stream(prompt):
            text = chunk.content if hasattr(chunk, 'content') else str(chunk)
            if not text:
                continue
            accumulated.append(text)
            publish_event(tenant_id, user_id, session.id, job_id, 'delta', {'text': text})
    except Exception as exc:
        publish_event(tenant_id, user_id, session.id, job_id, 'error', {'message': str(exc)})
        fail_assistant_message(message, str(exc))
        return {'status': 'failed', 'reason': str(exc)}

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
