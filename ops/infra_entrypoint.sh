#!/bin/sh
set -eu
umask 077
case "$1" in
  rabbitmq)
    export RABBITMQ_DEFAULT_PASS="$(cat /run/secrets/NEURODOC_RABBITMQ_PASSWORD)"
    mkdir -p /etc/rabbitmq/conf.d
    {
      printf 'deprecated_features.permit.transient_nonexcl_queues = true\n'
      printf 'deprecated_features.permit.global_qos = true\n'
    } > /etc/rabbitmq/conf.d/99-neurodoc.conf
    chmod 0644 /etc/rabbitmq/conf.d/99-neurodoc.conf
    exec docker-entrypoint.sh rabbitmq-server
    ;;
  redis)
    password_hash="$(sha256sum /run/secrets/NEURODOC_REDIS_PASSWORD | cut -d ' ' -f 1)"
    # Apagar antes de escrever. Reinicio de conteiner (docker compose
    # stop/start, Docker Desktop reaberto, maquina reiniciada) reaproveita a
    # camada de escrita, e o arquivo volta com dono `redis` e modo 0600 -- o
    # `umask 077` acima mais o `chown` abaixo. Recria-lo entao depende de
    # CAP_DAC_OVERRIDE, que o root do conteiner nem sempre tem: com o
    # isolamento reforcado do Docker Desktop a redirecao falha com
    # "Permission denied", e o Redis nao sobe mais ate alguem recriar o
    # conteiner -- que e um estado que se le como "o Redis quebrou", sem
    # nada dizendo que basta recriar. `rm` so precisa de permissao no
    # diretorio, e /tmp e 1777. No Swarm cada tentativa e um conteiner novo
    # e isto nunca aparece; localmente aparece no primeiro stop/start.
    rm -f /tmp/neurodoc-redis.conf
    cat > /tmp/neurodoc-redis.conf <<EOF
bind 0.0.0.0
protected-mode yes
port 6379
dir /data
appendonly yes
appendfsync everysec
maxmemory 384mb
maxmemory-policy noeviction
user default on #${password_hash} ~* &* +@all
EOF
    chown redis:redis /tmp/neurodoc-redis.conf
    exec docker-entrypoint.sh redis-server /tmp/neurodoc-redis.conf
    ;;
  redis-health)
    export REDISCLI_AUTH="$(cat /run/secrets/NEURODOC_REDIS_PASSWORD)"
    exec redis-cli --no-auth-warning ping
    ;;
  *) exit 2 ;;
esac
