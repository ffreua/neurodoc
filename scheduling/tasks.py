from celery import shared_task


@shared_task(name='scheduling.tasks.avisar_retornos')
def avisar_retornos_task():
    """Avisa, uma vez por dia, quem tem retorno previsto se aproximando.

    Roda no worker porque quem fala com o SMTP é ele -- o processo `app`
    não tem saída para a internet nesta topologia.

    **Falha de um paciente não derruba a rodada.** Um contato com endereço
    inválido, ou um SMTP que recusa uma mensagem específica, não pode
    impedir os outros cinquenta avisos do dia: a exceção é contida por
    registro, contada, e o resultado diz quantos falharam. Sem isto, o
    primeiro e-mail ruim de cada manhã cancelaria todos os seguintes -- e
    ninguém perceberia, porque a tarefa terminaria "com erro" e o erro
    seria o de um paciente só.
    """
    import logging

    from django.utils import timezone

    from communications.services import deliver_return_reminder

    from .returns import a_avisar

    logger = logging.getLogger(__name__)
    avisados = falhas = sem_contato = 0
    for registro in a_avisar():
        try:
            entregas = deliver_return_reminder(registro)
        except Exception:
            # Sem dado do paciente no log: o que interessa para depurar é
            # qual registro falhou, e o identificador basta.
            logger.exception('retorno %s: aviso falhou', registro.id)
            falhas += 1
            continue
        if not entregas:
            sem_contato += 1
            continue
        # `notified_at` é o que impede o mesmo paciente de receber um
        # e-mail por dia até a data chegar. Marcado **depois** do envio:
        # marcar antes perderia o aviso de vez se o envio estourasse.
        registro.notified_at = timezone.now()
        registro.save(update_fields=['notified_at'])
        avisados += 1
    return {'avisados': avisados, 'sem_contato': sem_contato, 'falhas': falhas}
