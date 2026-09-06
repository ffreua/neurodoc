from celery import shared_task

from .dispatcher import run_once


@shared_task(name='events.tasks.dispatch_outbox')
def dispatch_outbox():
    return run_once()
