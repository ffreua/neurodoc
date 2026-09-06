from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalogs.postal_codes import DATA_FILE, load_ranges


class Command(BaseCommand):
    help = (
        'Carrega as faixas de CEP por município a partir de um CSV '
        '(cep_start,cep_end,uf,city,city_ascii,region,ibge_code,by_street,scope). '
        'Sem --commit apenas valida o arquivo. Usa o arquivo versionado em '
        'catalogs/data/postal_ranges.csv quando --file não é informado.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--file', default=str(DATA_FILE))
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_file():
            raise CommandError(f'Arquivo não encontrado: {path}')
        report = load_ranges(path.read_text(encoding='utf-8'), dry_run=not options['commit'])
        self.stdout.write(f'Linhas lidas: {report["read"]}; gravadas: {report["written"]}')
        for error in report['errors']:
            self.stderr.write(error)
        if report['errors']:
            raise CommandError(f'{len(report["errors"])} linha(s) rejeitada(s); nada foi gravado')
        if not options['commit']:
            self.stdout.write('Somente validação; use --commit para gravar.')
