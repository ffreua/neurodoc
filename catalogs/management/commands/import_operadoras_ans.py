"""Carrega as operadoras de plano de saúde ativas da ANS (dados abertos).

Roda **no worker**, como `import_municipios`: baixa ~350 KB do portal de
dados abertos da ANS, e trabalho externo é do worker (§2).

    docker compose exec celery_worker python manage.py import_operadoras_ans
    docker compose exec celery_worker python manage.py import_operadoras_ans --dry-run

Serve ao cadastro de convênio (`catalogs.models.OperadoraAns`). Pode ser
repetida: atualiza quem está na lista e marca como inativa a operadora que
saiu dela — **nunca apaga**, porque um convênio de clínica pode apontar
para ela em guias antigas.
"""

import csv
import io
import re

import httpx
from django.core.management.base import BaseCommand
from django.db import transaction

URL = (
    'https://dadosabertos.ans.gov.br/FTP/PDA/operadoras_de_plano_de_saude_ativas/'
    'Relatorio_cadop.csv'
)

TIMEOUT_SECONDS = 60

#: Menos que isto é arquivo truncado ou formato novo, não a lista da ANS
#: (eram 1.105 ativas em 30/10/2026). Gravar uma lista curta marcaria
#: centenas de operadoras como inativas por engano.
MINIMO_ESPERADO = 500


def ler(conteudo):
    """CSV da ANS → lista de dicionários prontos. Linha torta é descartada."""
    from catalogs.importers import normalize_for_search

    texto = conteudo.decode('utf-8-sig')
    leitor = csv.DictReader(io.StringIO(texto), delimiter=';')
    obrigatorias = {'REGISTRO_OPERADORA', 'CNPJ', 'RAZAO_SOCIAL'}
    if not obrigatorias <= set(leitor.fieldnames or []):
        raise ValueError('O arquivo da ANS não tem as colunas esperadas.')
    linhas, descartadas = [], 0
    for linha in leitor:
        registro = (linha.get('REGISTRO_OPERADORA') or '').strip()
        # O CSV traz o registro como texto com zero à esquerda; o `zfill`
        # protege contra uma versão do arquivo que o perca.
        if registro.isdigit():
            registro = registro.zfill(6)
        razao = (linha.get('RAZAO_SOCIAL') or '').strip()
        if not re.fullmatch(r'\d{6}', registro) or not razao:
            descartadas += 1
            continue
        fantasia = (linha.get('NOME_FANTASIA') or '').strip()
        linhas.append({
            'registro_ans': registro,
            'cnpj': re.sub(r'\D', '', linha.get('CNPJ') or '')[:14],
            'razao_social': razao[:255],
            'nome_fantasia': fantasia[:255],
            'modalidade': (linha.get('MODALIDADE') or '').strip()[:80],
            'uf': (linha.get('UF') or '').strip()[:2],
            'cidade': (linha.get('CIDADE') or '').strip()[:120],
            'search_text': normalize_for_search(f'{registro} {razao} {fantasia}'),
        })
    return linhas, descartadas


def gravar(linhas):
    """Atualiza ou cria pelas linhas, e inativa quem saiu. Devolve contagens."""
    from catalogs.models import OperadoraAns

    if len(linhas) < MINIMO_ESPERADO:
        raise ValueError(
            f'A lista veio com {len(linhas)} operadoras; esperava pelo menos {MINIMO_ESPERADO}. '
            'Nada foi gravado.'
        )
    registros = {linha['registro_ans'] for linha in linhas}
    with transaction.atomic():
        OperadoraAns.objects.bulk_create(
            [OperadoraAns(ativa=True, **linha) for linha in linhas],
            batch_size=500, update_conflicts=True, unique_fields=['registro_ans'],
            update_fields=['cnpj', 'razao_social', 'nome_fantasia', 'modalidade', 'uf',
                           'cidade', 'search_text', 'ativa', 'updated_at'],
        )
        saiu = OperadoraAns.objects.filter(ativa=True).exclude(registro_ans__in=registros).update(ativa=False)
    return {'ativas': len(registros), 'inativadas': saiu}


class Command(BaseCommand):
    help = 'Importa as operadoras ativas da ANS para o cadastro de convênio.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Lê e conta, sem gravar.')

    def handle(self, *args, **options):
        self.stdout.write(f'Baixando {URL} ...')
        try:
            resposta = httpx.get(URL, timeout=TIMEOUT_SECONDS, follow_redirects=True)
            resposta.raise_for_status()
            linhas, descartadas = ler(resposta.content)
        except Exception as exc:
            self.stderr.write(f'Não foi possível ler a lista da ANS: {type(exc).__name__}: {exc}')
            return
        self.stdout.write(
            f'{len(linhas)} operadoras lidas' + (f'; {descartadas} linhas descartadas' if descartadas else '')
        )
        if options['dry_run']:
            self.stdout.write('Ensaio: nada gravado.')
            return
        try:
            resultado = gravar(linhas)
        except ValueError as exc:
            self.stderr.write(str(exc))
            return
        self.stdout.write(self.style.SUCCESS(
            f'Catálogo gravado: {resultado["ativas"]} ativas; {resultado["inativadas"]} marcadas inativas.'
        ))
