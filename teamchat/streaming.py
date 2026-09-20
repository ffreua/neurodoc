"""Entrega ao vivo: uma caixa de entrada por pessoa, em Redis Streams.

Mesma mecânica de `ai/streaming.py`, e de propósito — o SSE do chat de IA
já está homologado e a forma é conhecida. As duas diferenças são
deliberadas:

**Uma caixa por usuário, não uma por conversa.** O navegador abre um
`EventSource` só e recebe por ele o que chegar de qualquer colega. Uma
conexão por conversa multiplicaria as conexões pendentes por pessoa, e o
HTTP/1.1 do ambiente local limita seis por origem — a sétima aba ficaria
esperando sem erro nenhum na tela.

**A chave sai do contexto autenticado, nunca do cliente.** É a mesma
regra do chat de IA: um id de stream que vazasse não poderia ser usado
para ler a caixa de outra pessoa, porque a view monta a chave a partir de
`request.access_context`.

Nada aqui é a fonte da verdade. A mensagem está no PostgreSQL antes de
ser publicada; se o Redis engasgar, quem estava com a janela aberta não vê
a linha aparecer sozinha, e a vê assim que a janela for reaberta ou a
sondagem passar. Perder o aviso é aceitável; perder a mensagem não seria.
"""

import json
import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

#: Quanto tempo um evento fica disponível para reconexão. Passado isso, o
#: cliente busca o que faltou pelo banco (`?desde=`), que é o caminho
#: correto de qualquer forma.
TTL_SECONDS = 3600

#: Teto de eventos guardados por caixa. `XADD` com `maxlen` aproximado é
#: barato; sem ele, uma aba esquecida aberta o dia inteiro faria a caixa
#: crescer sem limite.
MAX_ENTRIES = 500


def inbox_key(tenant_id, user_id):
    return f'teamchat:inbox:{tenant_id}:{user_id}'


def publish(tenant_id, user_id, event_type, data):
    try:
        client = _client()
        key = inbox_key(tenant_id, user_id)
        entry_id = client.xadd(
            key, {'type': event_type, 'data': json.dumps(data, ensure_ascii=False)},
            maxlen=MAX_ENTRIES, approximate=True,
        )
        client.expire(key, TTL_SECONDS)
        return entry_id
    except redis.RedisError:
        # Engolido por decisão: a mensagem já está gravada, e derrubar o
        # envio porque o aviso não saiu transformaria uma indisponibilidade
        # do Redis em perda de mensagem.
        logger.warning('teamchat: evento nao publicado (redis indisponivel)')
        return None


def tail_id(tenant_id, user_id):
    """O id do último evento já na caixa, ou `'0'` se ela está vazia.

    É por onde uma conexão **nova** começa. Começar do zero reentregaria
    tudo o que o Redis ainda guarda (até uma hora de conversa), e o cliente
    acabou de carregar o estado verdadeiro do PostgreSQL: o efeito seria a
    janela somando não lidas que já estavam contadas, até a sondagem
    seguinte desfazer o engano.

    Reconexão é outro caso e continua como era: o navegador manda
    `Last-Event-ID`, e aí retomar exatamente dali é justamente o que se
    quer. A distinção entre "abri agora" e "caí e voltei" é o cabeçalho.
    """
    try:
        ultimo = _client().xrevrange(inbox_key(tenant_id, user_id), max='+', min='-', count=1)
        return ultimo[0][0] if ultimo else '0'
    except redis.RedisError:
        logger.warning('teamchat: fim da caixa nao consultado (redis indisponivel)')
        return '0'


def read_after(tenant_id, user_id, last_id='0'):
    """Eventos estritamente posteriores a `last_id`.

    O prefixo `(` é o intervalo exclusivo do Redis Streams: reconectar com
    o mesmo `Last-Event-ID` não reentrega o que o cliente já viu.
    """
    try:
        client = _client()
        range_min = f'({last_id}' if last_id and last_id != '0' else '-'
        return client.xrange(inbox_key(tenant_id, user_id), min=range_min, max='+')
    except redis.RedisError:
        logger.warning('teamchat: caixa nao lida (redis indisponivel)')
        return []


def _client():
    return redis.Redis.from_url(settings.TEAMCHAT_REDIS_URL, decode_responses=True)
