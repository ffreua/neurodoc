"""Quem está com o sistema aberto agora.

O pedido era conversar com "os usuários logados naquele momento", e
sessão no banco não responde isso: uma sessão do Django continua válida
por dias depois que a pessoa fechou o navegador. Presença aqui é o que se
pode afirmar de verdade — **esta aba pediu alguma coisa nos últimos
`ONLINE_TTL_SECONDS`**, seja pelo laço do SSE (janela aberta) ou pela
sondagem leve do cabeçalho (janela fechada).

Um conjunto ordenado por inquilino, e não uma chave por usuário: ler
"quem está on-line" com uma chave por pessoa exigiria `SCAN` sobre o
espaço de chaves inteiro a cada abertura da janela. Aqui é um `ZADD` na
escrita e um `ZRANGEBYSCORE` na leitura, ambos sobre uma chave só.

Redis fora do ar não pode derrubar o chat: quem não sabe responde "não
sei" (ninguém on-line, marca cinza na tela) e a conversa continua
funcionando pelo PostgreSQL, que é onde a mensagem de fato está.
"""

import logging
import time

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

#: Janela de tolerância. Precisa ser maior que o intervalo da sondagem do
#: cabeçalho (`POLL_SECONDS` em `static/teamchat/teamchat.js`), senão a
#: pessoa pisca entre on-line e off-line entre duas sondagens.
ONLINE_TTL_SECONDS = 75


def _client():
    return redis.Redis.from_url(settings.TEAMCHAT_REDIS_URL, decode_responses=True)


def _key(tenant_id):
    return f'teamchat:online:{tenant_id}'


def touch(tenant_id, user_id):
    """Registra que esta pessoa está viva agora."""
    agora = time.time()
    try:
        client = _client()
        pipe = client.pipeline()
        pipe.zadd(_key(tenant_id), {str(user_id): agora})
        # Poda o que já venceu na mesma ida ao Redis. Sem isto o conjunto
        # cresce com todo usuário que já entrou uma vez na clínica.
        pipe.zremrangebyscore(_key(tenant_id), '-inf', agora - ONLINE_TTL_SECONDS)
        pipe.expire(_key(tenant_id), ONLINE_TTL_SECONDS * 4)
        pipe.execute()
    except redis.RedisError:
        logger.warning('teamchat: presenca nao registrada (redis indisponivel)')


def online_user_ids(tenant_id):
    """Ids de quem deu sinal dentro da janela. Conjunto de strings."""
    try:
        client = _client()
        return set(client.zrangebyscore(
            _key(tenant_id), time.time() - ONLINE_TTL_SECONDS, '+inf',
        ))
    except redis.RedisError:
        logger.warning('teamchat: presenca nao consultada (redis indisponivel)')
        return set()
