"""Despachante da outbox: entrega cada evento a cada consumidor, ao menos uma vez.

Três decisões moram aqui, e as três vieram da auditoria de 2026-10-09
(`docs/homologation/despachante-da-outbox.md`):

**Quem segura o lease é quem escreve.** O lease era só um prazo: depois
de trinta segundos outro despachante reclamava o evento, e o primeiro
continuava autorizado a rodar o consumidor e a gravar o desfecho,
filtrando só pelo id. O prazo corria para o lote inteiro, e um evento
podia vencer esperando a vez atrás de uma entrega lenta. Agora
`locked_until` é também o **token de posse**: cada passo (antes de cada
consumidor, e o desfecho) é um `UPDATE` condicionado ao valor que este
despachante gravou. Quem perdeu a posse para de trabalhar no evento, em
vez de rodar em paralelo com o novo dono. Sem coluna nova: o instante
gravado no `claim`, em microssegundos, já distingue um dono do outro.

**O consumidor roda fora de uma transação externa.** Ele rodava dentro
de um `atomic` que incluía o marcador `ProcessedEvent`, e isso
transformava as transações *dos consumidores* em pontos de salvamento: o
token do documento ainda não existia para outra conexão quando o SMS com
o link saía, o job de IA ia para a fila antes de ser visível ao worker, e
uma falha depois do envio desfazia o registro de algo que já tinha saído
— o reenvio seguinte mandava uma segunda mensagem com outro link. Cada
consumidor é idempotente pela sua própria chave (a da entrega, a da
cobrança, a do job), e é ela que impede o efeito em dobro; a transação
externa não protegia nada que essas chaves não protejam, e escondia o
que já tinha acontecido.

**Falha deixa rastro com nome.** O `except` engolia a exceção e
devolvia uma contagem. Agora o log diz qual evento, qual consumidor, que
tentativa e que classe de erro — sem payload, que pode ter id de
paciente, e sem texto de provedor.
"""
import logging

from django.db.models import F
from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent, OutboxEventStatus, ProcessedEvent

logger = logging.getLogger(__name__)

#: Prazo da posse, renovado antes de cada consumidor.
#:
#: Era 30 s para o lote inteiro. Uma entrega pelo SMTP próprio da clínica
#: espera o `timeout` do servidor, e duas delas seguidas já passavam disso.
#: Dois minutos é o atraso que um evento de um worker morto sofre até ser
#: retomado — e em troca nenhum consumidor saudável perde a posse no meio.
LEASE_SECONDS = 120
BATCH_SIZE = 50
MAX_ATTEMPTS = 8
#: Quanto um evento sem consumidor espera antes de ser olhado de novo.
NO_HANDLER_DELAY_MINUTES = 5

_HANDLERS = {}


def register_handler(topic_prefix, consumer_name, handler):
    """Registers `handler(event)` for any topic starting with `topic_prefix`.
    `consumer_name` is the ProcessedEvent idempotency key. More than one
    independent consumer can register for the same topic (e.g. both
    `finance` and `ai` react to `clinical.encounter_finalized`) -- each
    gets its own ProcessedEvent row and its own at-least-once delivery;
    one consumer's failure never blocks or skips another's.

    O consumidor roda **sem** transação em volta (ver o topo do módulo):
    se precisa de atomicidade, ele mesmo a abre, e precisa ser idempotente
    por uma chave própria.
    """
    _HANDLERS.setdefault(topic_prefix, []).append((consumer_name, handler))


def _handlers_for(topic):
    matches = []
    for prefix, entries in _HANDLERS.items():
        if topic.startswith(prefix):
            matches.extend(entries)
    return matches


@transaction.atomic
def _claim_batch():
    now = timezone.now()
    claimable = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
        status=OutboxEventStatus.PENDING, available_at__lte=now,
    ).order_by('available_at')[:BATCH_SIZE]
    # Reclaim leases abandoned by a crashed/killed worker (locked_until passed).
    stale = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
        status=OutboxEventStatus.PROCESSING, locked_until__lt=now,
    ).order_by('available_at')[:BATCH_SIZE]
    ids = list(claimable.values_list('id', flat=True)) + list(stale.values_list('id', flat=True))
    if not ids:
        return []
    OutboxEvent.objects.filter(id__in=ids).update(
        status=OutboxEventStatus.PROCESSING, locked_until=now + timezone.timedelta(seconds=LEASE_SECONDS),
        attempts=F('attempts') + 1,
    )
    # Relido do banco de propósito: o `locked_until` que volta daqui é o
    # token de posse, e precisa ser o valor exato que está gravado.
    return list(OutboxEvent.objects.filter(id__in=ids))


def _owned(event):
    """O filtro que só casa enquanto este despachante é o dono do evento."""
    return OutboxEvent.objects.filter(
        id=event.id, status=OutboxEventStatus.PROCESSING, locked_until=event.locked_until,
    )


def _renew(event):
    """Renova a posse. `False` quando outro despachante já a tomou."""
    novo_prazo = timezone.now() + timezone.timedelta(seconds=LEASE_SECONDS)
    if _owned(event).update(locked_until=novo_prazo) != 1:
        return False
    event.locked_until = novo_prazo
    return True


def _lease_lost(event, consumer_name=''):
    logger.warning(
        'outbox: posse do evento perdida; o novo dono continua',
        extra={'event_id': str(event.id), 'topic': event.topic, 'consumer': consumer_name,
               'attempts': event.attempts},
    )
    return 'lease_lost'


def _process_one(event):
    if not _renew(event):
        return _lease_lost(event)

    handlers = _handlers_for(event.topic)
    if not handlers:
        # Unroutable topic: leave it PENDING with a pushed-back available_at
        # rather than silently dropping it -- a future deploy may register
        # the missing handler.
        #
        # A tentativa que o `claim` contou é devolvida: esperar consumidor
        # não é tentar e falhar. Sem isso o contador chegava aos milhares
        # (2.886 em `appointment_reserved`, visto em produção) e, no dia
        # em que o consumidor entrasse, o evento já nasceria acima de
        # `MAX_ATTEMPTS` — a primeira falha passageira seria a definitiva.
        #
        # Isto é seguro para integração de dados. **Mensagem a uma pessoa**
        # não pode contar com isto: o consumidor dela confere a idade pelo
        # `created_at` (ver `communications.handlers.JANELA_DO_AVISO`).
        _owned(event).update(
            status=OutboxEventStatus.PENDING,
            available_at=timezone.now() + timezone.timedelta(minutes=NO_HANDLER_DELAY_MINUTES),
            attempts=F('attempts') - 1,
        )
        return 'no_handler'

    any_failed = False
    all_already_processed = True
    for consumer_name, handler in handlers:
        if ProcessedEvent.objects.filter(event=event, consumer=consumer_name).exists():
            # This consumer already applied a previous (possibly
            # redelivered) attempt -- skip it, but still let any other
            # consumer for this same event run.
            continue
        all_already_processed = False
        # Renovada antes de cada consumidor, e não só uma vez no começo:
        # é o que garante que nenhum consumidor começa depois de a posse
        # ter passado a outro.
        if not _renew(event):
            return _lease_lost(event, consumer_name)
        try:
            handler(event)
            ProcessedEvent.objects.get_or_create(
                event=event, consumer=consumer_name, defaults={'processed_at': timezone.now()},
            )
        except Exception as exc:
            any_failed = True
            logger.exception(
                'outbox: consumidor falhou',
                extra={'event_id': str(event.id), 'topic': event.topic, 'consumer': consumer_name,
                       'attempts': event.attempts, 'error_class': exc.__class__.__name__},
            )

    if any_failed:
        attempts = event.attempts
        if attempts >= MAX_ATTEMPTS:
            if _owned(event).update(status=OutboxEventStatus.FAILED) != 1:
                return _lease_lost(event)
            logger.error(
                'outbox: evento abandonado depois de esgotar as tentativas',
                extra={'event_id': str(event.id), 'topic': event.topic, 'attempts': attempts},
            )
            return 'failed'
        backoff_seconds = min(2 ** attempts, 900)
        if _owned(event).update(
            status=OutboxEventStatus.PENDING,
            available_at=timezone.now() + timezone.timedelta(seconds=backoff_seconds),
        ) != 1:
            return _lease_lost(event)
        return 'retrying'

    if _owned(event).update(status=OutboxEventStatus.COMPLETED) != 1:
        return _lease_lost(event)
    return 'already_processed' if all_already_processed else 'completed'


def run_once():
    results = {}
    for event in _claim_batch():
        outcome = _process_one(event)
        results[outcome] = results.get(outcome, 0) + 1
    return results
