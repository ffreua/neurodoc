#!/bin/sh
# Avisa por e-mail que o backup falhou. Chamado pelo systemd
# (`ops/neurodoc-backup-falhou.service`, via `OnFailure=` do backup).
#
# Roda o comando no contêiner do WORKER, e nao do `app`: so o worker tem a
# credencial de e-mail (CLAUDE.md, secao 2). O contêiner e achado pelo
# rotulo do servico no Swarm, como em `ops/backup.py`.
#
# Sem worker no ar, nao ha como mandar e-mail daqui -- e isso tambem e
# falha que precisa aparecer: a mensagem vai para o journal, e a unidade
# termina com erro.
set -eu
CONTEINER="$(docker ps -q --filter label=com.docker.swarm.service.name=neurodoc_v1_celery_worker | head -n 1)"
if [ -z "$CONTEINER" ]; then
    echo "O backup falhou e o aviso nao saiu: nenhum contêiner do worker no ar." >&2
    exit 1
fi
exec docker exec "$CONTEINER" python manage.py avisar_falha_backup
