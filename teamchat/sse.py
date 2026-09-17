"""A caixa de entrada ao vivo, por Server-Sent Events.

Mesma forma de `ai/sse.py` — view assíncrona sob ASGI, um gerador que
nunca segura conexão de banco pelo tempo do stream, e a autorização
refeita a cada volta do laço. Vale repetir o porquê desta última: uma
conexão SSE vive muito mais tempo que a decisão que a autorizou, e revogar
o vínculo de alguém com um stream aberto continuaria entregando as
mensagens da equipe até o navegador desligar.

**O stream fica aberto enquanto a página existe, e não só enquanto a
janela do chat está aberta.** É ele que acende a badge do cabeçalho no
instante em que um colega escreve — e o caso que importa é justamente o da
janela fechada, porque é assim que ela passa o dia.

O orçamento de conexões continua de pé, e é resolvido do outro lado: o
navegador limita seis conexões por origem em HTTP/1.1 (o do ambiente
local), então as abas elegem **uma** líder que abre o stream e repassa o
que chega às demais por `BroadcastChannel`. Uma conexão por navegador, não
por aba — ver "liderança entre abas" em `static/teamchat/teamchat.js`.
Isso gasta menos conexões do que a versão anterior gastava com duas abas
de chat abertas.

O teto de `MAX_ITERATIONS_SAFETY` deixou de ser só uma salvaguarda: uma
aba esquecida aberta o dia inteiro agora alcança as duas horas. Chegar lá
encerra o gerador, o `EventSource` reconecta sozinho mandando o
`Last-Event-ID`, e nada se perde — é uma reciclagem, não uma falha.
"""

import asyncio
import time

from asgiref.sync import sync_to_async
from django.http import Http404, StreamingHttpResponse

from tenancy.models import Membership, MembershipStatus

from . import presence, streaming

HEARTBEAT_SECONDS = 15
PRESENCE_SECONDS = 30
POLL_INTERVAL_SECONDS = 1.0
#: De quanto em quanto tempo a autorização é refeita no banco.
#:
#: Era a cada volta do laço, copiado de `ai/sse.py`. Lá o stream dura o
#: tempo de uma resposta; aqui ele passou a ficar aberto o dia inteiro, e
#: refazer a consulta a cada segundo virou um `SELECT` por segundo **por
#: pessoa on-line** — carga permanente no banco para responder quase sempre
#: a mesma coisa.
#:
#: Dez segundos não afrouxam a regra que importa: nenhuma requisição HTTP
#: passa sem o `TenantMiddleware`, que confere o vínculo na hora. O que
#: esta janela permite é um stream **já aberto** seguir entregando por até
#: dez segundos depois da revogação — e quem revoga um vínculo não está
#: contando segundos, está tirando o acesso.
AUTORIZACAO_SEGUNDOS = 10
#: ~2 h no intervalo acima. Uma conexão real é fechada pelo cliente muito
#: antes; o teto existe para que uma aba esquecida num computador do
#: balcão não segure um worker para sempre.
MAX_ITERATIONS_SAFETY = 7200


@sync_to_async
def _membership_still_active(membership_id, tenant_id):
    return Membership.objects.filter(
        id=membership_id, tenant_id=tenant_id, status=MembershipStatus.ACTIVE,
    ).exists()


async def inbox_stream_view(request):
    if request.access_context is None:
        raise Http404
    tenant_id = request.access_context.tenant_id
    user_id = request.access_context.user_id
    membership_id = request.access_context.membership_id

    # A chave da caixa sai daqui, do contexto autenticado, e nunca de um
    # parâmetro — é o que impede que um id vazado sirva para ler a caixa
    # de outra pessoa.
    last_id = request.headers.get('Last-Event-ID') or request.GET.get('last_event_id')

    async def event_generator():
        # Sem `Last-Event-ID` esta é uma conexão nova, e ela começa do fim
        # da caixa — ver `streaming.tail_id`. Com o cabeçalho, retoma de
        # onde parou, que é o que o `EventSource` do navegador manda
        # sozinho ao reconectar.
        atual = last_id or await sync_to_async(streaming.tail_id)(tenant_id, user_id)
        ultimo_heartbeat = time.monotonic()
        ultima_presenca = 0.0
        ultima_autorizacao = 0.0
        for _ in range(MAX_ITERATIONS_SAFETY):
            agora = time.monotonic()
            if agora - ultima_autorizacao > AUTORIZACAO_SEGUNDOS:
                if not await _membership_still_active(membership_id, tenant_id):
                    yield 'event: revogado\ndata: {}\n\n'
                    return
                ultima_autorizacao = agora

            if agora - ultima_presenca > PRESENCE_SECONDS:
                # Quem está com a **página** aberta está on-line para os
                # colegas — é este laço que sustenta a bolinha verde, e ele
                # não depende de a janela do chat estar aberta.
                await sync_to_async(presence.touch)(tenant_id, user_id)
                ultima_presenca = agora

            entradas = await sync_to_async(streaming.read_after)(tenant_id, user_id, atual)
            for entry_id, campos in entradas:
                atual = entry_id
                yield f'id: {entry_id}\nevent: {campos["type"]}\ndata: {campos["data"]}\n\n'

            if time.monotonic() - ultimo_heartbeat > HEARTBEAT_SECONDS:
                # Comentário SSE: mantém a conexão viva através de proxy e
                # avisa o cliente de que o canal continua de pé.
                yield ': heartbeat\n\n'
                ultimo_heartbeat = time.monotonic()
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    response = StreamingHttpResponse(event_generator(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
