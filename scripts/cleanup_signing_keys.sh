#!/bin/sh
# Remove chaves de assinatura orfas do tmpfs. Com o Python certo, pelo
# mesmo motivo do `scripts/deploy.sh` e do `scripts/backup.sh`: o modulo
# alcanca `ops.deploy`, que le YAML, e o Python do sistema nao tem PyYAML.
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
if [ -x .venv-ops/bin/python ]; then
    PYTHON=.venv-ops/bin/python
else
    PYTHON=python3
fi
exec flock -n .runtime/signing-cleanup.lock "$PYTHON" -m ops.signing_cleanup
