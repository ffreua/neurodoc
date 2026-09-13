"""Sincroniza a tabela TUSS da ANS sob demanda.

A tarefa periodica cobre o dia a dia; este comando existe para a primeira
carga e para quando alguem precisa da tabela agora -- depois de uma
resolucao normativa, tipicamente.

Roda onde houver egresso. No Swarm, `docker exec` no container do worker.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Baixa a tabela TUSS da ANS e publica uma release do catalogo local.'

    def add_arguments(self, parser):
        from integrations import tuss

        parser.add_argument('--table', default=tuss.DEFAULT_TABLE,
                            help='Tabela da ANS, no formato tuss-NN.')

    def handle(self, *args, **options):
        from integrations import tuss

        self.stdout.write(f'Baixando {options["table"]} da ANS...')
        try:
            release = tuss.sync(options['table'])
        except tuss.TussUnavailable as exc:
            raise CommandError(str(exc))
        total = release.procedure_codes.count()
        self.stdout.write(self.style.SUCCESS(
            f'{release.version}: {total} procedimentos. Release ativa.'
        ))
