"""Tarefas do SNCR.

Só uma, e ela não fala com a Anvisa: marca como **incerto** o pedido que
ficou em "enviando" — o processo do `app` caiu no meio da chamada, e não
se sabe se o pedido saiu. Sem isso, ele ficaria "enviando" para sempre,
barrando pedidos novos sem dizer por quê (`fluxo.conferir`).
"""

from celery import shared_task

from . import fluxo


@shared_task(name='sncr.tasks.marcar_pedidos_parados')
def marcar_pedidos_parados():
    fluxo.pedidos_parados()
