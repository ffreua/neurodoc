#!/bin/sh
# Avisa por e-mail que a trava da Cloudflare falhou. Chamado pelo systemd
# (`ops/neurodoc-cloudflare-fw-falhou.service`, via `OnFailure=` da trava).
#
# Mesmo desenho de `avisar_falha_backup.sh`: o comando roda no contêiner
# do WORKER, o unico com a credencial de e-mail (CLAUDE.md, secao 2).
set -eu
CONTEINER="$(docker ps -q --filter label=com.docker.swarm.service.name=neurodoc_v1_celery_worker | head -n 1)"
if [ -z "$CONTEINER" ]; then
    echo "A trava da Cloudflare falhou e o aviso nao saiu: nenhum contêiner do worker no ar." >&2
    exit 1
fi
exec docker exec "$CONTEINER" python manage.py avisar_falha_firewall
