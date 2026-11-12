from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .chat_models import ChatMessage, ChatMessageRole, ChatMessageState, ChatSession


class SessionScopeError(Exception):
    pass


@transaction.atomic
def create_session(access_context, patient_id=None, title=''):
    """Every session is created explicitly for one owner/tenant/patient
    combination -- there is no "resume my last context" shortcut, and
    switching patient never happens on an existing row (see
    `switch_patient_creates_new_session` below): each combination starts
    with empty history, never inheriting another context's memory.
    """
    session = ChatSession.objects.create(
        tenant_id=access_context.tenant_id, owner_user_id=access_context.user_id,
        patient_id=patient_id, title=title[:255],
    )
    record_audit_event(
        access_context.user_id, access_context.tenant_id, 'ai.chat_session_created',
        object_type='chat_session', object_id=session.id, outcome='success',
    )
    return session


def switch_patient_creates_new_session(access_context, current_session, new_patient_id):
    """"Trocar paciente cria nova sessão" -- never mutate `current_session.
    patient`; always hand back a brand-new session with empty history.
    """
    return create_session(access_context, patient_id=new_patient_id, title=current_session.title)


def _next_sequence(session):
    last = session.messages.order_by('-sequence').first()
    return (last.sequence + 1) if last else 1


@transaction.atomic
def post_user_message(session, content):
    message = ChatMessage.objects.create(
        tenant_id=session.tenant_id, session=session, role=ChatMessageRole.USER,
        content=content, state=ChatMessageState.COMPLETE, sequence=_next_sequence(session),
    )
    session.last_message_at = timezone.now()
    session.save(update_fields=['last_message_at'])
    return message


@transaction.atomic
def start_assistant_message(session, ai_job=None):
    return ChatMessage.objects.create(
        tenant_id=session.tenant_id, session=session, role=ChatMessageRole.ASSISTANT,
        content='', state=ChatMessageState.STREAMING, sequence=_next_sequence(session), ai_job=ai_job,
    )


def finalize_assistant_message(message, final_text, source_refs=None):
    """Persisted independently of Redis: the final content lives in
    Postgres from the moment the stream completes, so losing the Redis
    stream afterward (TTL expiry, restart) never loses the result itself
    -- only live incremental replay to a still-open SSE connection.
    """
    # Só a que ainda está transmitindo (auditoria de 2026-11-11): a
    # cancelada pelo médico no meio voltava a "concluída" quando o worker
    # terminava, e a varrida por `encerrar_respostas_presas` também.
    gravou = type(message).objects.filter(pk=message.pk, state=ChatMessageState.STREAMING).update(
        content=final_text, source_refs=source_refs or [], state=ChatMessageState.COMPLETE,
    )
    message.refresh_from_db(fields=['content', 'source_refs', 'state'])
    if gravou:
        message.session.last_message_at = timezone.now()
        message.session.save(update_fields=['last_message_at'])
    return message


def fail_assistant_message(message, reason):
    type(message).objects.filter(pk=message.pk, state=ChatMessageState.STREAMING).update(
        content='', state=ChatMessageState.FAILED,
    )
    message.refresh_from_db(fields=['content', 'state'])
    return message
