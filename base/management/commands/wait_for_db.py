from django.core.management.base import BaseCommand
from ops.runtime import database_ready, wait_until


class Command(BaseCommand):
    help = 'Wait for the application database without exposing credentials.'

    def handle(self, *args, **options):
        wait_until(database_ready, 'database')
