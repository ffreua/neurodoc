"""Tarefas do chat da equipe."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='teamchat.tasks.apagar_vencidas')
def apagar_vencidas():
    """Apaga as mensagens com mais de 72 horas (`services.apagar_vencidas`).

    De hora em hora, e não uma vez por dia: o prazo prometido na janela é
    de 72 horas, e uma limpeza diária deixaria mensagem viva por até 95. A
    janela já esconde o vencido antes disso (`services.messages_of`); a
    tarefa é o que tira do banco.
    """
    from .services import apagar_vencidas as apagar

    resultado = apagar()
    if any(resultado.values()):
        logger.info('teamchat: mensagens vencidas apagadas', extra=resultado)
    return resultado
