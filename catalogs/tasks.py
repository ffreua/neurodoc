"""Tarefas do catalogo. Rodam no worker, que e quem tem egresso.

O processo web esta em `traefik_public` e `neurodoc_v1_internal`; quem
alcanca a internet e o `celery_worker`, em `neurodoc_v1_egress`. Nao e
acidente de configuracao: e o desenho. Por isso a sincronizacao da TUSS
vive aqui e nao numa view.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='catalogs.tasks.sync_tuss', expires=3600)
def sync_tuss_task(table=None):
    """Espelha a tabela TUSS da ANS no catalogo local.

    Falha e registrada e engolida: a tabela anterior continua ativa e a
    busca continua respondendo. Uma sincronizacao que estoura derrubaria a
    tarefa periodica e, com ela, as proximas tentativas -- e o sintoma
    seria uma tabela que para de envelhecer sem ninguem perceber.
    """
    from integrations import tuss

    alvo = table or tuss.DEFAULT_TABLE
    try:
        release = tuss.sync(alvo)
    except tuss.TussUnavailable as exc:
        logger.warning('sync_tuss: %s', exc)
        return {'ok': False, 'error': str(exc)}
    total = release.procedure_codes.count()
    logger.info('sync_tuss: %s com %s procedimentos', release.version, total)
    return {'ok': True, 'release': release.version, 'total': total}
