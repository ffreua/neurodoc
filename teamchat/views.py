"""Os endpoints da janela de mensagens. Tudo JSON, de propósito.

O resto do produto é SSR com Django Templates, e esta é a exceção
declarada: a janela flutua **sobre** a tela em que a pessoa está
trabalhando, e o ponto dela é justamente não fazer a pessoa sair do
prontuário, da agenda ou do formulário meio preenchido para responder uma
linha. Um formulário que envia e recarrega a página perderia o que estava
digitado na tela de baixo — que é o defeito que a janela existe para
evitar.

Sem JavaScript não há janela. É o mesmo patamar do resto do cabeçalho: o
menu de notificações, o seletor de tema e a confirmação de exclusão
também dependem de JavaScript, e um chat em tempo real não teria como não
depender.

Nenhuma view aqui monta HTML com texto escrito por usuário. O cliente
insere tudo por `textContent` (`static/teamchat/teamchat.js`) — é a mesma
regra do chat de IA, e aqui vale ainda mais: lá o texto vinha do modelo,
aqui vem de um colega que pode colar qualquer coisa.
"""

import json

from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.utils.dateparse import parse_datetime

from tenancy.permissions import CapabilityRequiredView

from . import presence, services


class TeamChatView(CapabilityRequiredView):
    """Base das views do chat.

    `required_capability = None` é decisão, e não esquecimento — a mesma
    de `notifications`: conversar com a equipe não é uma capacidade da
    matriz do PRD, é o que qualquer vínculo ativo faz. Médico, secretária,
    gestor e responsável falam uns com os outros; foi exatamente isso que
    se pediu.

    O que continua valendo é o isolamento: `TenantMiddleware` já recusou
    quem não tem vínculo ativo nesta clínica, e toda consulta abaixo filtra
    por `tenant_id` do contexto.
    """

    required_capability = None

    def corpo(self, request):
        """O JSON enviado pelo cliente, ou `{}`.

        Devolve dicionário vazio em vez de estourar: um corpo malformado é
        um erro de cliente, e cada view abaixo já recusa o que falta com
        uma mensagem que a janela sabe mostrar.
        """
        try:
            data = json.loads(request.body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def _recusa(mensagem, status=400):
    return JsonResponse({'erro': mensagem}, status=status)


class StateView(TeamChatView):
    """Colegas, quem está on-line e quantas mensagens esperam resposta.

    É também onde a presença é registrada. Registrar presença num `GET` é
    deliberado e é a única escrita de estado que um `GET` faz aqui: não é
    dado da clínica, não vai para o banco, e é uma chave no Redis que
    vence sozinha em pouco mais de um minuto. A alternativa — um `POST` só
    para dizer "estou aqui" — seria bloqueada pelo congelamento da clínica
    suspensa, e uma clínica suspensa continua tendo gente trabalhando.
    """

    def get(self, request):
        ctx = request.access_context
        presence.touch(ctx.tenant_id, ctx.user_id)
        return JsonResponse(services.state_for(ctx.tenant_id, ctx.user_id))


class OpenView(TeamChatView):
    """Abre (ou reabre) a conversa com um colega."""

    def post(self, request):
        ctx = request.access_context
        outro = self.corpo(request).get('user_id')
        if not outro:
            return _recusa('Informe com quem conversar.')
        try:
            conversa = services.open_direct(ctx.tenant_id, ctx.user_id, outro)
        except services.ChatError as erro:
            return _recusa(str(erro))
        except (ValidationError, ValueError, TypeError):
            # Id que não é UUID — o `UUIDField` recusa na consulta, com
            # `ValidationError`, e não com `ValueError`. A resposta é a
            # mesma de quem não existe: quem sonda não descobre a diferença
            # entre "malformado" e "não é daqui".
            return _recusa('Esta pessoa não tem vínculo ativo nesta organização.')
        return JsonResponse({'conversa': str(conversa.id)})


class ThreadView(TeamChatView):
    """As mensagens de uma conversa.

    Não marca como lida. Ler é `POST .../lida/`, chamado pelo cliente
    depois de desenhar — pelo mesmo motivo que a central de notificações:
    um `GET` que altera estado é disparado por qualquer coisa que
    pré-carregue endereços, inclusive o próprio navegador.
    """

    def get(self, request, conversation_id):
        ctx = request.access_context
        participacao = services.membership_in(ctx.tenant_id, conversation_id, ctx.user_id)
        if participacao is None:
            # 404, e não 403: quem não participa não precisa saber que a
            # conversa existe. É a mesma escolha de `CapabilityRequiredView`.
            raise Http404
        # `parse_datetime` devolve `None` para lixo, mas **estoura**
        # `ValueError` para uma data bem formatada e impossível
        # ("2026-13-01"). Sem isto, um parâmetro forjado viraria 500.
        try:
            desde = parse_datetime(request.GET.get('desde') or '')
        except ValueError:
            desde = None
        mensagens = services.messages_of(
            ctx.tenant_id, conversation_id, desde=desde, apagada_em=participacao.cleared_at,
        )
        return JsonResponse({
            'mensagens': [services.message_payload(m) for m in mensagens],
            'nao_lidas': participacao.unread_count,
        })


class SendView(TeamChatView):
    def post(self, request, conversation_id):
        ctx = request.access_context
        participacao = services.membership_in(ctx.tenant_id, conversation_id, ctx.user_id)
        if participacao is None:
            raise Http404
        presence.touch(ctx.tenant_id, ctx.user_id)
        try:
            mensagem = services.send(
                ctx.tenant_id, participacao.conversation, ctx.user_id,
                self.corpo(request).get('texto'),
            )
        except services.ChatError as erro:
            return _recusa(str(erro))
        return JsonResponse({'mensagem': services.message_payload(mensagem)})


class ClearView(TeamChatView):
    """Apaga a conversa para quem pediu (`services.apagar_conversa`)."""

    def post(self, request, conversation_id):
        ctx = request.access_context
        if services.membership_in(ctx.tenant_id, conversation_id, ctx.user_id) is None:
            raise Http404
        services.apagar_conversa(ctx.tenant_id, conversation_id, ctx.user_id)
        return JsonResponse({'total': services.unread_total(ctx.tenant_id, ctx.user_id)})


class ReadView(TeamChatView):
    def post(self, request, conversation_id):
        ctx = request.access_context
        if services.membership_in(ctx.tenant_id, conversation_id, ctx.user_id) is None:
            raise Http404
        services.mark_read(ctx.tenant_id, conversation_id, ctx.user_id)
        return JsonResponse({'total': services.unread_total(ctx.tenant_id, ctx.user_id)})
