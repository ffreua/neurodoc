"""Tarefas do catalogo. Rodam no worker, que e quem tem egresso.

O processo web esta em `traefik_public` e `neurodoc_v1_internal`; quem
alcanca a internet e o `celery_worker`, em `neurodoc_v1_egress`. Nao e
acidente de configuracao: e o desenho. Por isso a sincronizacao da TUSS
vive aqui e nao numa view.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

#: Quanto tempo esta tarefa pode durar, sobrepondo o limite global de seis
#: minutos do `core/settings.py`.
#:
#: A ANS leva ~80 segundos por pagina de 25 itens e ignora pedido de pagina
#: maior; a `tuss-22` tem ~240 paginas. Com o limite global, a tarefa seria
#: morta depois de quatro paginas, toda semana, sem nunca completar -- e o
#: sintoma era uma tabela que nunca enchia.
#:
#: Quarenta e cinco minutos por rodada dao ~33 paginas. A sincronizacao e
#: retomavel (`tuss.sync_incremental`), entao sete ou oito rodadas
#: completam a tabela. O limite rigido fica acima do suave para o Celery
#: poder levantar `SoftTimeLimitExceeded` e a tarefa terminar limpa.
LIMITE_SUAVE_SEGUNDOS = 45 * 60
LIMITE_RIGIDO_SEGUNDOS = 50 * 60

#: Quanto esperar antes de retomar. Curto de proposito: enquanto a tabela
#: esta pela metade, a busca de procedimento ainda responde pela release
#: anterior, e o que interessa e terminar.
ESPERA_PARA_RETOMAR_SEGUNDOS = 60


@shared_task(
    name='catalogs.tasks.sync_tuss', expires=3600,
    soft_time_limit=LIMITE_SUAVE_SEGUNDOS, time_limit=LIMITE_RIGIDO_SEGUNDOS,
)
def sync_tuss_task(table=None):
    """Avanca o espelho da TUSS, e se agenda de novo se faltou pagina.

    Falha e registrada e engolida: a tabela anterior continua ativa e a
    busca continua respondendo. Uma sincronizacao que estoura derrubaria a
    tarefa periodica e, com ela, as proximas tentativas -- e o sintoma
    seria uma tabela que para de envelhecer sem ninguem perceber.

    **So se reagenda quando houve progresso.** Se a ANS nao respondeu
    nenhuma pagina, reagendar seria um laco batendo num servico fora do ar
    de minuto em minuto; o timer semanal tenta de novo no domingo. Progresso
    e a condicao de parada deste laco, e e ela que o torna finito.
    """
    from integrations import tuss

    alvo = table or tuss.DEFAULT_TABLE
    try:
        resultado = tuss.sync_incremental(alvo)
    except tuss.TussUnavailable as exc:
        logger.warning('sync_tuss: %s', exc)
        return {'ok': False, 'error': str(exc)}
    except Exception as exc:                                    # noqa: BLE001
        # Inclui `SoftTimeLimitExceeded`: a rodada foi cortada, mas o que
        # ela gravou ficou -- a proxima retoma dali. Engolir aqui e o que
        # impede o corte de virar tarefa com erro toda semana.
        logger.warning('sync_tuss interrompida: %s: %s', type(exc).__name__, exc)
        return {'ok': False, 'error': f'{type(exc).__name__}'}

    if resultado['completo']:
        logger.info(
            'sync_tuss: %s completa com %s procedimentos',
            resultado['versao'], resultado['total'],
        )
        return {'ok': True, **resultado}

    if resultado['paginas']:
        logger.info(
            'sync_tuss: %s paginas nesta rodada, %s procedimentos ate agora; retomando',
            resultado['paginas'], resultado['total'],
        )
        sync_tuss_task.apply_async(
            kwargs={'table': alvo}, countdown=ESPERA_PARA_RETOMAR_SEGUNDOS,
        )
    else:
        logger.warning(
            'sync_tuss: nenhuma pagina respondeu; nao reagenda (o timer semanal tenta)'
        )
    return {'ok': True, **resultado}
