#!/bin/sh
set -eu
umask 027

# Quantos processos o `app` roda e quantas tarefas o worker faz ao mesmo
# tempo -- por instalacao, no `.env` (`APP_WORKERS`, `WORKER_CONCURRENCY`),
# para crescer sem republicar codigo. O padrao e o de antes (2 e 2), que cabe
# numa VPS pequena; quem tem folga sobe. Numero fora da faixa para a
# subida com a explicacao, em vez de virar argumento estranho no comando.
#
# Os dois andam junto com os limites de CPU e memoria do `docker-stack.yml`:
# cada processo do `app` atende **uma** requisicao por vez (a view sincrona
# do Django roda numa thread so por processo), e quatro processos presos a
# um nucleo dividiriam o mesmo nucleo.
numero_entre() {
  case "$1" in
    ''|*[!0-9]*) echo "$3 precisa ser um numero entre 1 e $2 (veio '$1')." >&2; exit 64 ;;
  esac
  if [ "$1" -lt 1 ] || [ "$1" -gt "$2" ]; then
    echo "$3 precisa ser um numero entre 1 e $2 (veio '$1')." >&2; exit 64
  fi
}

case "${1:-app}" in
  app)
    ND_APP_WORKERS="${APP_WORKERS:-2}"
    numero_entre "$ND_APP_WORKERS" 16 APP_WORKERS
    python manage.py wait_for_db
    python manage.py bootstrap_release
    exec uvicorn core.asgi:application --host 0.0.0.0 --port 8000 \
      --workers "$ND_APP_WORKERS" --no-access-log --timeout-keep-alive 30 \
      --no-proxy-headers
    ;;
  worker)
    ND_WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-2}"
    numero_entre "$ND_WORKER_CONCURRENCY" 32 WORKER_CONCURRENCY
    python manage.py wait_for_dependencies
    ND_WORKER_QUEUES=communications,ai,documents,maintenance
    if [ "${NEURODOC_RECOVERY_MODE:-False}" = 'True' ]; then
      ND_WORKER_QUEUES=recovery
    fi
    exec celery -A core worker --hostname='worker@%h' \
      --loglevel=WARNING --concurrency="$ND_WORKER_CONCURRENCY" --prefetch-multiplier=1 \
      --queues="$ND_WORKER_QUEUES"
    ;;
  beat)
    python manage.py wait_for_dependencies
    exec celery -A core beat --loglevel=WARNING \
      --scheduler=ops.scheduler.HeartbeatScheduler \
      --schedule=/data/beat/celerybeat-schedule --max-interval=10
    ;;
  *)
    exec "$@"
    ;;
esac
