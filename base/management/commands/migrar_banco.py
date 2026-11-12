from django.core.management.base import BaseCommand

from ops.runtime import migrate_release


class Command(BaseCommand):
    help = 'Aplica as migrações pela conexão do dono do banco, sob trava (serviço migrate).'

    def handle(self, *args, **options):
        migrate_release()
