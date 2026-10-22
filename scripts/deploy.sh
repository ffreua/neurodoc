#!/bin/sh
# Publica uma versao. Uma de cada vez, e com o Python certo.
#
# `flock -n` e a trava: duas publicacoes simultaneas na mesma maquina se
# atropelariam no meio do `docker stack deploy`, e a segunda falharia com
# um erro que nao diz que havia uma primeira.
#
# O `.venv-ops` existe porque `ops/deploy.py` le YAML, e o Python do
# sistema na VPS nao tem PyYAML. Chamar `python3` direto, como esta linha
# fazia, quebrava com `ModuleNotFoundError: yaml` num servidor montado
# exatamente como `docs/operations/primeiro-deploy.md` manda — e aquele
# documento, no resumo do dia a dia, manda usar este script. Preferir o
# venv quando ele existe e o que faz as duas coisas concordarem; sem ele,
# `python3` continua valendo (e o ambiente local nao tem `.venv-ops`).
set -eu
cd "$(dirname "$0")/.."
mkdir -p .runtime
chmod 700 .runtime
if [ -x .venv-ops/bin/python ]; then
    PYTHON=.venv-ops/bin/python
else
    PYTHON=python3
fi
# Sem `exec`, para poder explicar a recusa. `flock -n` saia com codigo 1
# **calado** quando a trava estava tomada -- e quem a toma todo dia e o
# backup (`scripts/backup.sh`, mesma trava). Quem rodava o deploy as 03h
# via o prompt voltar sem nada e nao sabia se tinha publicado. `-E 75`
# separa "ocupado" de qualquer falha do proprio deploy, que ja se explica.
set +e
flock -n -E 75 .runtime/operation.lock "$PYTHON" -m ops.deploy "$@"
CODIGO=$?
set -e
if [ "$CODIGO" -eq 75 ]; then
    echo "Nada foi publicado: outra operacao segura .runtime/operation.lock" >&2
    echo "(o backup diario ou outro deploy). Confira com:" >&2
    echo "  systemctl status neurodoc-backup.service; pgrep -af 'ops\.(deploy|backup)'" >&2
    echo "e rode de novo quando ela terminar." >&2
fi
exit "$CODIGO"
