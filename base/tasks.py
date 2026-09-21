from celery import shared_task
from django.conf import settings


@shared_task(name='base.tasks.operational_ping', expires=60, ignore_result=False)
def operational_ping():
    from .version import VERSION

    return {'ok': True, 'release': settings.RELEASE_ID, 'version': VERSION}
