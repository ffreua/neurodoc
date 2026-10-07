"""Carrega os municípios brasileiros do IBGE.

Roda **no worker**, como `sync_tuss` e `import_cmed`: baixa ~2,4 MB da
API pública do IBGE, e trabalho externo é do worker (§2).

    docker compose exec celery_worker python manage.py import_municipios
    docker compose exec celery_worker python manage.py import_municipios --dry-run

Serve à naturalidade do paciente. O campo continua aceitando texto
livre — o catálogo sugere, não impede —, então uma instalação que nunca
rodar este comando continua funcionando: a tela simplesmente não
sugere nada.
"""

import unicodedata

import httpx
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogs.models import Municipality

URL = 'https://servicodados.ibge.gov.br/api/v1/localidades/municipios'

#: Trinta segundos. A resposta tem 5.571 linhas e alguns megabytes; o
#: padrão do httpx (5 s) corta no meio de um dia ruim do IBGE e deixa o
#: catálogo pela metade.
TIMEOUT_SECONDS = 30


def _ascii_upper(texto):
    """A mesma normalização de `catalogs.importers.normalize_for_search`.

    Importada de lá, e não reescrita: as duas pontas — o que se grava e o
    que se digita — têm de normalizar igual, senão a busca mente em
    silêncio.
    """
    from catalogs.importers import normalize_for_search

    return normalize_for_search(texto)


class Command(BaseCommand):
    help = 'Importa os municípios do IBGE para a naturalidade do paciente.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Lê e conta, sem gravar. É o que se roda quando o IBGE muda a API.',
        )

    def handle(self, *args, **options):
        self.stdout.write(f'Baixando {URL} ...')
        try:
            resposta = httpx.get(URL, timeout=TIMEOUT_SECONDS)
            resposta.raise_for_status()
            linhas = resposta.json()
        except Exception as exc:
            self.stderr.write(f'Não foi possível falar com o IBGE: {type(exc).__name__}: {exc}')
            return

        if not isinstance(linhas, list) or not linhas:
            self.stderr.write('O IBGE respondeu sem a lista de municípios.')
            return

        registros = []
        sem_uf = 0
        for linha in linhas:
            try:
                # O caminho da UF é fundo e o IBGE já o mudou antes. Um
                # município sem UF é contado e descartado, em vez de
                # derrubar a importação inteira por uma linha torta.
                uf = linha['microrregiao']['mesorregiao']['UF']['sigla']
            except (KeyError, TypeError):
                regiao = (linha.get('regiao-imediata') or {}).get('regiao-intermediaria') or {}
                uf = ((regiao.get('UF') or {}).get('sigla')) or ''
            nome = (linha.get('nome') or '').strip()
            codigo = str(linha.get('id') or '').strip()
            if not (nome and codigo and uf):
                sem_uf += 1
                continue
            registros.append(Municipality(
                ibge_code=codigo, name=nome, name_ascii=_ascii_upper(nome), uf=uf,
            ))

        self.stdout.write(
            f'{len(registros)} municípios lidos'
            + (f'; {sem_uf} descartados por falta de nome, código ou UF' if sem_uf else '')
        )
        if options['dry_run']:
            exemplo = ', '.join(f'{m.name}/{m.uf}' for m in registros[:3])
            self.stdout.write(f'Ensaio: nada gravado. Primeiros: {exemplo}')
            return

        # `bulk_create` com `update_conflicts`: a segunda execução é uma
        # atualização, não um erro de chave duplicada. Município muda de
        # nome (e já mudou), e a importação precisa poder ser repetida.
        with transaction.atomic():
            Municipality.objects.bulk_create(
                registros, batch_size=1000,
                update_conflicts=True,
                update_fields=['name', 'name_ascii', 'uf', 'updated_at'],
                unique_fields=['ibge_code'],
            )
        total = Municipality.objects.count()
        self.stdout.write(self.style.SUCCESS(f'Catálogo gravado: {total} municípios.'))
