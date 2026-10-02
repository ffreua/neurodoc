#!/bin/sh
# Copia de seguranca cifrada. Uma de cada vez, e com o Python certo.
#
# O `.venv-ops` existe porque `ops/backup.py` importa `ops.deploy`, que le
# YAML, e o Python do sistema na VPS nao tem PyYAML. Chamar `python3`
# direto -- como esta linha fazia -- quebrava com `ModuleNotFoundError:
# yaml` na primeira vez que o timer disparasse, de madrugada, sem ninguem
# olhando; e o alerta que faltaria seria justamente o de que nao ha backup.
# Mesma escolha do `scripts/deploy.sh`, pelo mesmo motivo.
#
# `flock` na mesma trava do deploy (`operation.lock`): publicar uma versao
# no meio de uma copia mistura os dois estados no arquivo resultante.
#
# ESPERA, E NAO DESISTE. Esta linha era `flock -n`, e `-n` quer dizer "se
# estiver ocupado, saia". Em 2026-10-02 o timer disparou as 03:10:29, no
# meio de um deploy que correu das 03:01 as 03:12: a trava estava tomada,
# `flock -n` saiu com codigo 1 **sem imprimir nada**, e o dia ficou sem
# backup. O journal registrou `status=1/FAILURE` e nenhuma linha dizendo
# por que.
#
# Desistir era a escolha errada para uma tarefa diaria: o deploy dura
# minutos, o backup tem o dia inteiro, e o conflito e justamente o momento
# em que a copia mais importa -- acabou de entrar versao nova. Esperar
# quarenta e cinco minutos cabe folgado no `TimeoutStartSec=4h` da unidade
# e cobre qualquer deploy que termine.
#
# E quando a espera estoura, isso vira **uma frase no journal**, nao um
# codigo de saida mudo. Backup que falha calado e o pior defeito possivel
# nesta caixa: so se descobre na noite de restaurar.
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
if [ -x .venv-ops/bin/python ]; then
    PYTHON=.venv-ops/bin/python
else
    PYTHON=python3
fi
ESPERA_PELA_TRAVA=2700
# `set +e` em volta porque o que interessa e o codigo REAL do `flock`. Com
# `if ! flock ...`, o `$?` de dentro do bloco ja e o status negado pelo `!`,
# e nao o do comando -- a mensagem sairia com o numero errado.
set +e
flock -w "$ESPERA_PELA_TRAVA" .runtime/operation.lock "$PYTHON" -m ops.backup
CODIGO=$?
set -e
if [ "$CODIGO" -ne 0 ]; then
    # `flock` devolve 1 quando o tempo acaba; qualquer outro codigo veio do
    # proprio `ops.backup`, que ja explica o que houve.
    if [ "$CODIGO" -eq 1 ]; then
        echo "NAO HOUVE BACKUP: a trava .runtime/operation.lock seguiu tomada por ${ESPERA_PELA_TRAVA}s." >&2
        echo "Deploy longo ou travado segurando operation.lock. Rode 'sh scripts/backup.sh' depois que ele terminar." >&2
    fi
    exit "$CODIGO"
fi
