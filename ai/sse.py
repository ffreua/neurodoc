import asyncio
import time

from asgiref.sync import sync_to_async
from django.http import Http404, HttpResponseForbidden, StreamingHttpResponse

from tenancy.models import Membership, MembershipStatus

from . import streaming
from .chat_models import ChatSession

HEARTBEAT_SECONDS = 15
POLL_INTERVAL_SECONDS = 0.5
MAX_ITERATIONS_SAFETY = 7200  # ~1h at the poll interval above; a real connection is closed by the client


@sync_to_async
def _session_or_none(tenant_id, user_id, session_id):
    return ChatSession.objects.filter(tenant_id=tenant_id, owner_user_id=user_id, id=session_id).first()


@sync_to_async
def _membership_still_active(membership_id, tenant_id):
    return Membership.objects.filter(
        id=membership_id, tenant_id=tenant_id, status=MembershipStatus.ACTIVE,
    ).exists()


async def chat_stream_view(request, session_id, job_id):
    """Async view (uvicorn/ASGI, already the deployment target since S01):
    the generator below never holds a database connection open across the
    whole SSE lifetime -- each authorization recheck is its own short-lived
    `sync_to_async` call, exactly like any other request would use one.
    """
    if request.access_context is None:
        raise Http404
    tenant_id = request.access_context.tenant_id
    user_id = request.access_context.user_id
    membership_id = request.access_context.membership_id

    session = await _session_or_none(tenant_id, user_id, session_id)
    if session is None:
        raise Http404

    last_id = request.headers.get('Last-Event-ID') or request.GET.get('last_event_id') or '0'

    async def event_generator():
        current_last_id = last_id
        last_heartbeat = time.monotonic()
        for _ in range(MAX_ITERATIONS_SAFETY):
            if not await _membership_still_active(membership_id, tenant_id):
                yield 'event: revoked\ndata: {}\n\n'
                return
            entries = await sync_to_async(streaming.read_after)(tenant_id, user_id, session_id, job_id, current_last_id)
            for entry_id, fields in entries:
                current_last_id = entry_id
                yield f'id: {entry_id}\nevent: {fields["type"]}\ndata: {fields["data"]}\n\n'
                if fields['type'] in streaming.TERMINAL_EVENT_TYPES:
                    return
            if time.monotonic() - last_heartbeat > HEARTBEAT_SECONDS:
                yield ': heartbeat\n\n'
                last_heartbeat = time.monotonic()
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    response = StreamingHttpResponse(event_generator(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
