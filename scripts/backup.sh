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
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
if [ -x .venv-ops/bin/python ]; then
    PYTHON=.venv-ops/bin/python
else
    PYTHON=python3
fi
exec flock -n .runtime/operation.lock "$PYTHON" -m ops.backup
