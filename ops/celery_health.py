import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
if sys.argv[1] == 'beat':
    try:
        age = time.time() - float(Path('/tmp/beat-heartbeat').read_text())
        raise SystemExit(0 if 0 <= age < 60 else 1)
    except (ValueError, FileNotFoundError):
        raise SystemExit(1)
else:
    from core.celery import app
    name = f'worker@{socket.gethostname()}'
    replies = app.control.inspect(destination=[name], timeout=5).ping() or {}
    raise SystemExit(0 if replies.get(name, {}).get('ok') == 'pong' else 1)
