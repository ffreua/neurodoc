from django.db import transaction

from audit.services import record_audit_event

from .chat_models import ChatMessage, ChatMessageState
from .services import cancel_job
from .streaming import publish_event

MAX_CONCURRENT_STREAMS_PER_USER = 3

#: Depois disto, "transmitindo" é resposta perdida, e não em andamento: a
#: tarefa do chat morre em seis minutos (`CELERY_TASK_TIME_LIMIT`).
#: `ai.tasks.encerrar_respostas_presas` a encerra; até lá, ela não conta
#: no limite acima — senão três respostas perdidas (fila atrasada, worker
#: reiniciado no deploy, Redis fora) deixavam o médico sem chat.
RESPOSTA_PERDIDA_MINUTOS = 15


class ConcurrencyLimitExceeded(Exception):
    pass


def check_concurrency_limit(tenant_id, user_id):
    from django.utils import timezone

    from .chat_models import ChatMessage

    active = ChatMessage.objects.filter(
        session__tenant_id=tenant_id, session__owner_user_id=user_id, state=ChatMessageState.STREAMING,
        created_at__gte=timezone.now() - timezone.timedelta(minutes=RESPOSTA_PERDIDA_MINUTOS),
    ).count()
    if active >= MAX_CONCURRENT_STREAMS_PER_USER:
        raise ConcurrencyLimitExceeded(
            f'Já há {active} resposta(s) em andamento. Espere terminar ou cancele uma.'
        )


@transaction.atomic
def cancel_message(message, actor_id):
    """Cancellation is a persisted state transition, nothing more -- it
    makes no claim about token/cost refund from the provider (a partially
    generated response may already have been billed upstream), and it does
    not retroactively delete whatever partial content was streamed.
    """
    # Um botão atrasado no navegador não pode desfazer uma resposta que o
    # worker já concluiu. A trava também resolve a corrida entre os dois.
    message = ChatMessage.objects.select_for_update().select_related('session').get(pk=message.pk)
    if message.state != ChatMessageState.STREAMING:
        return message

    message.state = ChatMessageState.CANCELLED
    message.save(update_fields=['state'])
    if message.ai_job_id:
        cancel_job(message.ai_job, actor_id)
    publish_event(
        message.tenant_id, message.session.owner_user_id, message.session_id,
        str(message.ai_job_id or message.id), 'cancelled', {},
    )
    record_audit_event(
        actor_id, message.tenant_id, 'ai.chat_message_cancelled',
        object_type='chat_message', object_id=message.id, outcome='success',
    )
    return message
