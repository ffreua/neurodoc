"""Tarefas do TISS, no worker.

A geração do arquivo é a única: ela relê as três chaves e a permissão de
quem pediu antes de escrever (`lotes._ainda_autorizado`), e é idempotente
— a mensagem que chegar duas vezes encontra o lote pronto e não faz nada.
"""

import logging

from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)

#: Lote em "gerando" há mais que isto, sem a tarefa ter terminado: a
#: mensagem se perdeu (worker reiniciado no meio). A retomada a reenvia.
PARADO_MINUTOS = 10


@shared_task(name='tiss.tasks.gerar_lote')
def gerar_lote(lote_id):
    from .lotes import _falha, gerar_arquivo
    from .models import EstadoLote, Lote

    try:
        gerar_arquivo(lote_id)
    except Exception:                                              # noqa: BLE001
        # Falha inesperada não pode deixar o lote girando para sempre na
        # tela: vira falha registrada, que a pessoa pode tentar de novo.
        log.exception('tiss: falha inesperada gerando o lote %s', lote_id)
        lote = Lote.objects.filter(id=lote_id, estado=EstadoLote.GERANDO).first()
        if lote is not None:
            _falha(lote, ['Falha inesperada ao gerar o arquivo. Tente de novo; se persistir, avise o suporte.'])


@shared_task(name='tiss.tasks.retomar_lotes_parados')
def retomar_lotes_parados():
    from .models import EstadoLote, Lote

    limite = timezone.now() - timezone.timedelta(minutes=PARADO_MINUTOS)
    ids = list(Lote.objects.filter(estado=EstadoLote.GERANDO, updated_at__lt=limite).values_list('id', flat=True)[:50])
    for lote_id in ids:
        gerar_lote.delay(str(lote_id))
    return len(ids)
