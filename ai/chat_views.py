from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from tenancy.permissions import Capability, CapabilityRequiredView

from . import chat_services
from .cancellation import ConcurrencyLimitExceeded, cancel_message, check_concurrency_limit
from .chat_models import ChatMessageRole, ChatMessageState, ChatSession
from .rendering import render_markdown
from .tasks import run_chat_turn


class TenantScopedView(CapabilityRequiredView):
    """Chat clínico de IA — a mesma capacidade do prontuário.

    O chat consulta o prontuário para responder. A sessão ser do próprio
    usuário (`_own_session_or_404`) diz de quem é a conversa, não a que
    dados ela dá acesso: sem a capacidade clínica, uma secretária abriria
    uma sessão dela mesma e perguntaria o diagnóstico do paciente.
    """

    required_capability = Capability.CLINICAL_AI


def _own_session_or_404(request, session_id):
    return get_object_or_404(
        ChatSession, id=session_id, tenant_id=request.access_context.tenant_id,
        owner_user_id=request.access_context.user_id,
    )


def _sessions_of(request):
    """As conversas do proprio usuario, da mais recente para a mais antiga.

    Do **proprio**: a conversa carrega prontuario, e a lista de sessoes de
    um medico dita a outro ja seria informacao sobre quem ele atende.
    """
    from .chat_models import ChatSessionStatus

    return (
        ChatSession.objects
        .filter(tenant_id=request.access_context.tenant_id,
                owner_user_id=request.access_context.user_id,
                status=ChatSessionStatus.ACTIVE)
        .select_related('patient')
        .order_by('-last_message_at', '-created_at')
    )


def _shell(request, session=None, **overrides):
    """O contexto do layout de duas colunas.

    Lista e conversa compartilham a mesma tela -- como num aplicativo de
    mensagens. Antes eram duas paginas, e abrir uma conversa fazia a lista
    desaparecer: para trocar de assunto era preciso voltar.
    """
    contexto = {
        'sessions': _sessions_of(request),
        'session': session,
        'rendered_messages': [],
    }
    if session is not None and session.patient_id:
        # Só com paciente: os quatro pedidos falam do prontuário, e a
        # conversa sem paciente não tem prontuário a que se referir.
        from .acoes_rapidas import ACOES

        contexto['acoes_rapidas'] = ACOES
    if session is not None:
        contexto['rendered_messages'] = [
            {'message': m,
             'html': render_markdown(m.content) if m.role != ChatMessageRole.USER else None}
            for m in session.messages.order_by('sequence')
        ]
    contexto.update(overrides)
    return contexto


class ChatSessionListView(TenantScopedView):
    def get(self, request):
        return render(request, 'ai/chat/shell.html', _shell(request))

    def post(self, request):
        """Cria a conversa. Paciente vem do autocomplete, nao digitado.

        O campo pedia o UUID do paciente, escrito a mao. Ninguem sabe o
        UUID de um paciente -- na pratica o campo ficava vazio, e toda
        conversa nascia sem prontuario, que e justamente o caso em que a
        IA nao tem o que consultar.
        """
        patient_id = (request.POST.get('patient_id') or '').strip() or None
        if patient_id:
            # O paciente e resolvido no escopo do inquilino: um id de outra
            # clinica nao vira sessao, e `create_session` receberia None.
            from patients.models import Patient

            existe = Patient.objects.filter(
                tenant_id=request.access_context.tenant_id, id=patient_id,
            ).exists()
            if not existe:
                patient_id = None
        session = chat_services.create_session(
            request.access_context, patient_id=patient_id,
            title=(request.POST.get('title') or '').strip(),
        )
        return redirect('ai:chat-session-detail', session_id=session.id)


class ChatSessionDetailView(TenantScopedView):
    def get(self, request, session_id):
        session = _own_session_or_404(request, session_id)
        return render(request, 'ai/chat/shell.html', _shell(request, session=session))


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

        user_message = chat_services.post_user_message(session, content)
        # A primeira pergunta vira o titulo. O campo era opcional e ficava
        # vazio, e a lista virava uma coluna de "Sem titulo" -- que e uma
        # lista pela qual nao se navega.
        if not session.title:
            session.title = content[:80] + ('…' if len(content) > 80 else '')
            session.save(update_fields=['title', 'updated_at'])
        assistant_message = chat_services.start_assistant_message(session)
        # Só os dois identificadores vão para o RabbitMQ. O texto digitado
        # ia junto, como argumento da tarefa: a pergunta do médico sobre um
        # paciente ficava escrita na fila, que não é o prontuário, não é
        # cifrada como ele e sobrevive num arquivo de mensagens se a tarefa
        # falhar e for reenfileirada. O texto já está gravado na mensagem
        # do usuário; o worker o lê de lá.
        run_chat_turn.delay(str(assistant_message.id), str(user_message.id))
        return redirect('ai:chat-session-detail', session_id=session.id)


class ChatMessageCancelView(TenantScopedView):
    def post(self, request, session_id, message_id):
        session = _own_session_or_404(request, session_id)
        message = get_object_or_404(session.messages, id=message_id)
        cancel_message(message, request.user.id)
        return redirect('ai:chat-session-detail', session_id=session.id)


class ChatSessionArchiveView(TenantScopedView):
    """Arquiva a conversa. Nao apaga.

    A conversa carrega o que o medico perguntou e o que a IA respondeu, e
    isso e material de revisao -- o proprio produto registra que sugestao
    aceita, editada ou rejeitada e medida separadamente. Apagar levaria
    junto a evidencia de qual foi a sugestao.
    """

    def post(self, request, session_id):
        from .chat_models import ChatSessionStatus

        session = _own_session_or_404(request, session_id)
        session.status = ChatSessionStatus.ARCHIVED
        session.save(update_fields=['status', 'updated_at'])
        return redirect('ai:chat-list')


class ChatSessionDeleteView(TenantScopedView):
    """Apaga a conversa e as mensagens dela, de vez.

    Arquivar continua sendo o caminho normal -- a conversa e material de
    revisao, e o produto mede sugestao aceita, editada e rejeitada. Apagar
    existe para o outro caso, que tambem e real: a conversa aberta por
    engano, a pergunta escrita no lugar errado, o teste que ficou.

    **O conteudo some; o registro de que ela existiu, nao.** A trilha grava
    quem apagou, quando, quantas mensagens e qual paciente estava em
    escopo -- nunca o texto. E a mesma linha do resto do sistema: auditar e
    saber quem fez o que, nao guardar o que foi escrito.

    Isto nao e prontuario. Conversa de apoio nao entra no registro clinico
    do paciente: o que entra e o que o medico aceitou e escreveu no
    atendimento, e isso vive em `clinical`, intocado por esta tela.

    `ChatMessage.ai_job` e `PROTECT`: a mensagem que nasceu de um job de IA
    prende o job. O job e apagado junto, porque ele existe **para** aquela
    mensagem -- deixar o job orfao guardaria metadado de uma conversa que o
    usuario pediu para apagar.
    """

    def post(self, request, session_id):
        from django.db import transaction

        from audit.services import record_audit_event

        from .models import AIJob

        session = _own_session_or_404(request, session_id)
        rotulo = session.title or 'sem titulo'
        total = session.messages.count()
        paciente_id = session.patient_id

        with transaction.atomic():
            jobs = list(
                session.messages.filter(ai_job__isnull=False)
                .values_list('ai_job_id', flat=True)
            )
            session.messages.all().delete()
            if jobs:
                AIJob.objects.filter(id__in=jobs).delete()
            session.delete()

        record_audit_event(
            request.user, request.access_context.tenant_id, 'ai.chat_session_deleted',
            object_type='chat_session', object_id=session_id, outcome='success',
            # Quantidade e escopo, nunca o texto: a trilha nao guarda
            # conteudo de conversa, aqui como em nenhum outro lugar.
            integrity_metadata={'messages': total, 'patient_id': str(paciente_id) if paciente_id else None},
        )
        messages.success(request, f'Conversa "{rotulo}" apagada.')
        return redirect('ai:chat-list')
