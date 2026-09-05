import fcntl
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from kombu import Connection
from redis import Redis


MIGRATION_LOCK = 72654001


def wait_until(check, label, seconds=900):
    deadline = time.monotonic() + seconds
    delay = 1
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(delay)
        delay = min(delay * 1.5, 10)
    raise RuntimeError(f'Dependency timeout: {label}')


def database_ready():
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT 1')
        return cursor.fetchone()[0] == 1


def schema_ready():
    executor = MigrationExecutor(connections['default'])
    targets = executor.loader.graph.leaf_nodes()
    return not executor.migration_plan(targets)


def broker_ready():
    with Connection(settings.CELERY_BROKER_URL, connect_timeout=5) as broker:
        broker.ensure_connection(max_retries=0)
    return True


def redis_ready():
    client = Redis.from_url(settings.CELERY_RESULT_BACKEND,
                            socket_connect_timeout=5, socket_timeout=5)
    try:
        return client.ping()
    finally:
        client.close()


def wait_dependencies():
    wait_until(database_ready, 'database')
    wait_until(schema_ready, 'schema')
    wait_until(broker_ready, 'broker')
    wait_until(redis_ready, 'redis')


def prepare_release():
    if 'migrations' not in settings.DATABASES:
        raise RuntimeError('Migration credential is unavailable')
    connection = connections['migrations']

    def lock_available():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(%s)', [MIGRATION_LOCK])
            return cursor.fetchone()[0]

    wait_until(lock_available, 'migration lock')
    try:
        # call_command uses the same Django connection alias holding the lock.
        call_command('migrate', database='migrations', interactive=False,
                     verbosity=0)
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [MIGRATION_LOCK])
        connection.close()
    prepare_staticfiles()


def prepare_staticfiles():
    root = Path('/data/staticfiles')
    root.mkdir(parents=True, exist_ok=True)
    target = Path(settings.STATIC_ROOT)
    if root not in target.parents:
        raise RuntimeError('Invalid static root')
    with (root / '.collectstatic.lock').open('a') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if target.exists():
            marker = target / '.ready'
            if marker.is_file() and marker.read_text() == settings.RELEASE_ID:
                return
            raise RuntimeError('Existing static release is incomplete')
        stage = root / f'.staging-{uuid.uuid4().hex}'
        stage.mkdir(mode=0o750)
        try:
            environment = dict(os.environ, STATIC_PREPARATION_ROOT=str(stage))
            subprocess.run([sys.executable, 'manage.py', 'collectstatic',
                            '--clear', '--noinput', '--verbosity=0'],
                           cwd=settings.BASE_DIR, env=environment, check=True)
            (stage / '.ready').write_text(settings.RELEASE_ID)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def app_ready():
    return (database_ready() and schema_ready()
            and (Path(settings.STATIC_ROOT) / '.ready').is_file())
