import functools
import json

import redis
from django.conf import settings

TTL_SECONDS = 3600
TERMINAL_EVENT_TYPES = frozenset({'complete', 'error', 'cancelled'})


@functools.lru_cache(maxsize=1)
def _client():
    # Um cliente por processo, com o pool dele (auditoria de 2026-11-11).
    # `from_url` a cada chamada criava um pool novo por pedaço da resposta
    # e por volta do stream — centenas de conexões por resposta, fechadas
    # quando o coletor de lixo quisesse. O cliente do redis-py é seguro
    # entre threads.
    return redis.Redis.from_url(settings.AI_EVENTS_REDIS_URL, decode_responses=True)


def stream_key(tenant_id, user_id, session_id, job_id):
    """Key includes tenant/user/session/job so a leaked stream id from one
    context can never be replayed to read another's chat -- the SSE view
    (ai/sse.py) always derives this same key from the authenticated
    request, never from a client-supplied key.
    """
    return f'ai:stream:{tenant_id}:{user_id}:{session_id}:{job_id}'


def publish_event(tenant_id, user_id, session_id, job_id, event_type, data):
    client = _client()
    key = stream_key(tenant_id, user_id, session_id, job_id)
    entry_id = client.xadd(key, {'type': event_type, 'data': json.dumps(data, ensure_ascii=False)})
    client.expire(key, TTL_SECONDS)
    return entry_id


def read_after(tenant_id, user_id, session_id, job_id, last_id='0'):
    """Returns entries strictly after `last_id` (Redis Streams' exclusive
    range via the `(` prefix) -- reconnecting with the same Last-Event-ID
    never redelivers an event the client already saw.
    """
    client = _client()
    key = stream_key(tenant_id, user_id, session_id, job_id)
    range_min = f'({last_id}' if last_id and last_id != '0' else '-'
    return client.xrange(key, min=range_min, max='+')
