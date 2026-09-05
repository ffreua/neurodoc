from django.core.management.base import BaseCommand
from ops.runtime import wait_dependencies


class Command(BaseCommand):
    help = 'Wait for database schema, broker and result backend.'

    def handle(self, *args, **options):
        wait_dependencies()
