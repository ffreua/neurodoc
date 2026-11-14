"""Tarefas da contratação. Abrir o checkout é do worker, que tem a chave (CLAUDE.md §2)."""

import logging

from celery import shared_task

from . import asaas, servicos

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, acks_late=True)
def preparar_checkout_task(self, pedido_id):
    """Abre o checkout. Rede caída ou 5xx tenta de novo; recusa da Asaas não.

    A repetição depois de um tempo esgotado pode abrir um segundo checkout
    para o mesmo pedido, se o primeiro chegou a ser criado do outro lado. É
    inofensivo: quem paga só recebe o link do que ficou gravado, e o outro
    vence em uma hora sem cobrar nada.
    """
    try:
        servicos.preparar_checkout(pedido_id)
    except asaas.AsaasIndisponivel as exc:
        if self.request.retries >= self.max_retries:
            servicos.marcar_falha(pedido_id, f'A Asaas não respondeu: {exc}')
            return
        raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))


@shared_task(acks_late=True)
def processar_evento_task(evento_id):
    servicos.processar_evento(evento_id)


@shared_task
def varrer_contratacao():
    return servicos.varrer()


@shared_task
def avisar_vigencias():
    from . import vigencias

    return vigencias.avisar()
