#!/bin/sh
# Confere se houve backup completo nas ultimas 26 horas (ops/vigiar_backup.py).
# Chamado por `neurodoc-backup-vigia.timer`; saindo com erro, o `OnFailure=`
# da unidade manda o mesmo e-mail do backup que falhou.
#
# Mesmo Python do `scripts/backup.sh`, e pelo mesmo motivo: `ops.deploy`
# le YAML, e o Python do sistema na VPS nao tem PyYAML.
set -eu
cd "$(dirname "$0")/.."
if [ -x .venv-ops/bin/python ]; then
    PYTHON=.venv-ops/bin/python
else
    PYTHON=python3
fi
exec "$PYTHON" -m ops.vigiar_backup
