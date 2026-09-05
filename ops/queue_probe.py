import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from core.celery import app
from django.conf import settings

queue = 'recovery' if settings.NEURODOC_RECOVERY_MODE else 'maintenance'
result = app.send_task('base.tasks.operational_ping', queue=queue, expires=60)
value = result.get(timeout=30)
if value.get('ok') is not True:
    raise SystemExit(1)
result.forget()
print('Queue and result backend responded to an operational probe.')
