#!/bin/sh
set -eu
umask 027
case "${1:-app}" in
  app)
    python manage.py wait_for_db
    python manage.py bootstrap_release
    exec uvicorn core.asgi:application --host 0.0.0.0 --port 8000 \
      --workers 2 --no-access-log --timeout-keep-alive 30 \
      --no-proxy-headers
    ;;
  worker)
    python manage.py wait_for_dependencies
    ND_WORKER_QUEUES=communications,ai,documents,maintenance
    if [ "${NEURODOC_RECOVERY_MODE:-False}" = 'True' ]; then
      ND_WORKER_QUEUES=recovery
    fi
    exec celery -A core worker --hostname='worker@%h' \
      --loglevel=WARNING --concurrency=2 --prefetch-multiplier=1 \
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
