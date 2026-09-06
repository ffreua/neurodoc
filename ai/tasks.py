from celery import shared_task

from .chat_models import ChatMessage
from .chat_services import fail_assistant_message, finalize_assistant_message
from .models import AIJob, AIJobStatus
from .providers import ProviderUnavailable, get_chat_model
from .rendering import render_markdown
from .services import JobNotRunnable, run_job
from .streaming import publish_event


@shared_task(name='ai.tasks.run_ai_job', expires=600)
def run_ai_job(job_id):
    try:
        artifact = run_job(job_id)
    except JobNotRunnable:
        return {'status': 'skipped'}
    if artifact is None:
        job = AIJob.objects.filter(id=job_id).first()
        return {'status': job.status if job else 'unknown'}
    return {'status': AIJobStatus.SUCCEEDED, 'artifact_id': str(artifact.id)}


@shared_task(name='ai.tasks.run_chat_turn', expires=600)
def run_chat_turn(message_id, prompt):
    """Streams the reply token-by-token into the Redis Stream keyed by
    this message's id (RF-11.04) while accumulating the full text, then
    persists the final, sanitized content to Postgres regardless of
    whether any SSE client was even connected to see the stream live --
    the result must survive a Redis restart/TTL expiry untouched.
    """
    message = ChatMessage.objects.select_related('session').get(id=message_id)
    session = message.session
    tenant_id, user_id, job_id = session.tenant_id, session.owner_user_id, str(message.id)

    try:
        chat_model = get_chat_model()
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

    from notifications.services import notify_user
    notify_user(
        session.tenant, user_id, kind='chat_reply_ready',
        sanitized_title='Sua conversa com a IA tem uma nova resposta',
        target_type='chat_session', target_id=session.id,
    )
    return {'status': 'complete', 'message_id': str(message.id)}
