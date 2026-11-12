from django.core.management.base import BaseCommand
from ops.runtime import prepare_release


class Command(BaseCommand):
    help = 'Espera o banco migrado (serviço migrate) e publica os estáticos da versão.'

    def handle(self, *args, **options):
        prepare_release()
