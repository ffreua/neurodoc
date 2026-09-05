import time
from pathlib import Path
from celery.beat import PersistentScheduler


class HeartbeatScheduler(PersistentScheduler):
    max_interval = 10

    def tick(self, *args, **kwargs):
        delay = super().tick(*args, **kwargs)
        Path('/tmp/beat-heartbeat').write_text(str(time.time()))
        return min(delay, 10)
