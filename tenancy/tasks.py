"""Tarefas da organização: hoje, só a degustação."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='tenancy.tasks.rodada_da_degustacao')
def rodada_da_degustacao():
    """Encerra as degustações vencidas e manda o aviso de véspera.

    A cada quinze minutos. O middleware já encerra a clínica que alguém
    abre; esta é a que encerra a que ninguém abriu — e que, sem ela, seguiria
    no Completo para o lembrete do worker e para a IA agendada
    (`tenancy/degustacao.py`).
    """
    from .degustacao import rodada

    resultado = rodada()
    if resultado['encerradas'] or resultado['avisadas']:
        logger.info('degustacao: %(encerradas)s encerrada(s), %(avisadas)s avisada(s)', resultado)
    return resultado
