from celery import shared_task


@shared_task(name='notifications.tasks.purge_expired')
def purge_expired_notifications_task():
    from .retention import purge_expired_notifications

    return purge_expired_notifications()
