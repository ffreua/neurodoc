"""O CID-10 que toda instalação recebe ao subir pela primeira vez.

Um prontuário de neurologia sem CID-10 não registra diagnóstico: a busca
devolve vazio, a hipótese não fecha, e o documento sai sem código. O
arquivo vem no repositório (`catalogs/data/cid10-2024.csv`) desde sempre,
e mesmo assim a instalação nova subia sem ele — porque importar era um
comando que alguém precisava lembrar de rodar.

É o mesmo defeito que o roteiro de exame tinha, pela mesma razão, e a
correção é a mesma: provisionar é do sistema, não do operador.

## Por que aqui, e não numa migração de dados

Migração de dados roda uma vez e fica registrada como aplicada. Se a
importação falhasse no meio — arquivo truncado, disco cheio —, a migração
constaria como feita e a instalação ficaria sem catálogo, sem nada
apontando isso. Aqui a verificação é do **estado**: existe release ativo
de CID-10? Se não, importa. Na próxima subida tenta de novo.

## TUSS não entra aqui

A TUSS vem de uma API externa (`integrations/tuss.py`), e trabalho que
fala com a internet é do worker — ele tenta de novo e não prende a subida.
Ela é sincronizada por `catalogs.tasks.sync_tuss`, semanalmente, e o primeiro
enchimento acontece na primeira execução. Ver `catalogs/tasks.py`.
"""
import logging
from pathlib import Path

from django.db import transaction

from .models import CatalogRelease, CatalogReleaseStatus

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / 'data'
CID10_FILE = DATA_DIR / 'cid10-2024.csv'
CID10_VERSION = '2024'


def has_active_catalog(system):
    return CatalogRelease.objects.filter(
        system=system, status=CatalogReleaseStatus.ACTIVE,
    ).exists()


def ensure_cid10(path=CID10_FILE, version=CID10_VERSION):
    """Importa e ativa o CID-10 se a instalação ainda não tiver um ativo.

    **Nunca sobrepõe.** A condição é "existe release ativo?", e não "existe
    esta versão?": uma instalação que já subiu um CID-10 mais novo à mão
    não pode ser rebaixada para o que vem no repositório. Foi exatamente
    assim que a semeadura de demonstração rebaixou o catálogo real de
    14.233 códigos para 10, numa versão anterior.

    Não levanta. Catálogo ausente é um problema sério e não é motivo para
    a aplicação não subir: sem ele o sistema atende, agenda e escreve
    evolução — só não fecha diagnóstico. Derrubar o processo web deixaria
    a clínica inteira fora do ar por causa de um arquivo.
    """
    if has_active_catalog('CID10'):
        return None
    if not path.is_file():
        logger.error('Arquivo do CID-10 nao encontrado: %s', path)
        return None
    from .importers import activate_release, import_catalog

    try:
        with transaction.atomic():
            _relatorio, release = import_catalog(
                'CID10', version, path.read_text(encoding='utf-8'),
                source_url='https://www.gov.br/saude/',
                license_note='CID-10, Organizacao Mundial da Saude, uso clinico.',
                dry_run=False,
            )
            activate_release(release)
    except Exception:
        logger.exception('Falha ao importar o CID-10 na subida da instalacao')
        return None
    logger.info('CID-10 %s importado e ativado', version)
    return release
