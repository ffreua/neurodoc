from django.core.management.base import BaseCommand
from ops.runtime import prepare_release


class Command(BaseCommand):
    help = 'Migrate under an advisory lock and publish release static files.'

    def handle(self, *args, **options):
        prepare_release()
