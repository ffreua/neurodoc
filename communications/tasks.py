from celery import shared_task

from .reconciliation import reconcile_pending_sms


@shared_task(name='communications.tasks.reconcile_pending_sms')
def reconcile_pending_sms_task():
    return reconcile_pending_sms()
