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
