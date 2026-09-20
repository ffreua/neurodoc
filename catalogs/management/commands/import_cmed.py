"""Importa a lista de medicamentos da CMED/Anvisa.

Rode no **worker**, que é quem alcança a internet nesta topologia:

    docker exec $(docker ps -q -f name=neurodoc_v1_celery_worker | head -1) \
      python manage.py import_cmed

Com o arquivo já baixado (o caminho é dentro do contêiner):

    python manage.py import_cmed --arquivo /tmp/cmed.xlsx

`--dry-run` lê e conta sem gravar nada — é o que se roda primeiro quando a
CMED publica um arquivo novo, para ver se o formato continua o mesmo.
"""

import tempfile
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalogs import cmed
from catalogs.models import CatalogRelease, CatalogSystem


class Command(BaseCommand):
    help = 'Importa a lista de preços de medicamentos da CMED/Anvisa (catálogo de prescrição).'

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', default='', help='XLSX já baixado. Sem isto, baixa da Anvisa.')
        parser.add_argument('--url', default=cmed.URL_PADRAO, help='Endereço do XLSX na Anvisa.')
        parser.add_argument('--versao', default='', help='Nome da release. Padrão: a data de hoje.')
        parser.add_argument('--dry-run', action='store_true', help='Lê e conta, sem gravar.')
        parser.add_argument(
            '--nao-ativar', action='store_true',
            help='Importa como rascunho, sem trocar a release em vigor.',
        )

    def handle(self, *args, **opcoes):
        caminho = opcoes['arquivo']
        temporario = None
        try:
            if not caminho:
                self.stdout.write('Baixando a lista da CMED...')
                temporario = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
                temporario.close()
                try:
                    urllib.request.urlretrieve(opcoes['url'], temporario.name)
                except OSError as erro:
                    raise CommandError(
                        f'Não consegui baixar {opcoes["url"]}: {erro}. '
                        'Este comando roda no worker — o processo web não tem saída para a internet.'
                    )
                caminho = temporario.name
            tamanho = Path(caminho).stat().st_size
            self.stdout.write(f'Arquivo: {caminho} ({tamanho / 1_048_576:.1f} MB)')

            if opcoes['dry_run']:
                registros, descartadas = cmed.ler_planilha(caminho)
                self.stdout.write(self.style.SUCCESS(
                    f'{len(registros)} apresentações lidas, {descartadas} linhas descartadas. '
                    'Nada foi gravado (--dry-run).'
                ))
                self._resumo_de_tarjas(registros)
                return

            release, total, descartadas = cmed.importar(
                caminho, versao=opcoes['versao'] or None, url=opcoes['url'],
                ativar=not opcoes['nao_ativar'],
            )
            self.stdout.write(self.style.SUCCESS(
                f'Release {release.version} ({release.status}): {total} apresentações, '
                f'{descartadas} linhas descartadas.'
            ))
            anteriores = CatalogRelease.objects.filter(
                system=CatalogSystem.CMED,
            ).exclude(pk=release.pk).count()
            if anteriores:
                self.stdout.write(
                    f'{anteriores} release(s) anterior(es) mantida(s): uma receita antiga '
                    'continua legível com o texto que o medicamento tinha quando foi prescrita.'
                )
        except cmed.ImportacaoCmedErro as erro:
            raise CommandError(str(erro))
        finally:
            if temporario is not None:
                Path(temporario.name).unlink(missing_ok=True)

    def _resumo_de_tarjas(self, registros):
        contagem = {}
        for r in registros:
            contagem[r['tarja']] = contagem.get(r['tarja'], 0) + 1
        self.stdout.write('Tarjas encontradas:')
        for tarja, quantas in sorted(contagem.items(), key=lambda p: -p[1]):
            self.stdout.write(f'  {quantas:>7}  {tarja}')
