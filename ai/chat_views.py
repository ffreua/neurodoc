from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from . import chat_services
from .cancellation import ConcurrencyLimitExceeded, cancel_message, check_concurrency_limit
from .chat_models import ChatMessageRole, ChatMessageState, ChatSession
from .rendering import render_markdown
from .tasks import run_chat_turn


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _own_session_or_404(request, session_id):
    return get_object_or_404(
        ChatSession, id=session_id, tenant_id=request.access_context.tenant_id,
        owner_user_id=request.access_context.user_id,
    )


class ChatSessionListView(TenantScopedView):
    def get(self, request):
        sessions = ChatSession.objects.filter(
            tenant_id=request.access_context.tenant_id, owner_user_id=request.access_context.user_id,
        ).order_by('-last_message_at', '-created_at')
        return render(request, 'ai/chat/list.html', {'sessions': sessions})

    def post(self, request):
        patient_id = request.POST.get('patient_id') or None
        session = chat_services.create_session(
            request.access_context, patient_id=patient_id, title=request.POST.get('title', ''),
        )
        return redirect('ai:chat-session-detail', session_id=session.id)


class ChatSessionDetailView(TenantScopedView):
    def get(self, request, session_id):
        session = _own_session_or_404(request, session_id)
        messages = session.messages.order_by('sequence')
        rendered = [
            {'message': m, 'html': render_markdown(m.content) if m.role != ChatMessageRole.USER else None}
            for m in messages
        ]
        return render(request, 'ai/chat/detail.html', {'session': session, 'rendered_messages': rendered})


class ChatMessageCreateView(TenantScopedView):
    def post(self, request, session_id):
        session = _own_session_or_404(request, session_id)
        content = request.POST.get('content', '').strip()
        if not content:
            return HttpResponseForbidden('Empty message')
        try:
            check_concurrency_limit(session.tenant_id, session.owner_user_id)
        except ConcurrencyLimitExceeded as exc:
            return HttpResponseForbidden(str(exc))

        chat_services.post_user_message(session, content)
        assistant_message = chat_services.start_assistant_message(session)
        run_chat_turn.delay(str(assistant_message.id), content)
        return redirect('ai:chat-session-detail', session_id=session.id)


class ChatMessageCancelView(TenantScopedView):
    def post(self, request, session_id, message_id):
        session = _own_session_or_404(request, session_id)
        message = get_object_or_404(session.messages, id=message_id)
        cancel_message(message, request.user.id)
        return redirect('ai:chat-session-detail', session_id=session.id)
