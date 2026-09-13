"""Espelho local da tabela TUSS, alimentado pela API pública da ANS.

## Por que espelho, e não consulta ao vivo

A primeira versão deste módulo consultava a ANS a cada busca. O argumento
era bom — a TUSS muda por resolução normativa, e uma cópia local vira
desatualizada sem avisar, com a glosa aparecendo na fatura — e mesmo assim
estava errado, por uma razão que só apareceu ao rodar:

**o processo web não tem saída para a internet.** Em produção o serviço
`app` está em `traefik_public` e `neurodoc_v1_internal`; quem está em
`neurodoc_v1_egress` é o `celery_worker`. Não é acidente de configuração,
é o desenho: o processo que atende requisição de navegador não conversa
com a internet. Uma chamada síncrona a partir de uma view não falharia em
desenvolvimento — falharia no primeiro dia de produção, por *timeout*, com
o médico esperando.

O espelho resolve os dois lados. A sincronização roda no **worker**, que
tem egresso; a busca lê o banco, responde em milissegundos e funciona com
a internet fora. A desatualização, que era o argumento contra, vira uma
data visível na tela e uma tarefa periódica — o que é melhor do que a
consulta ao vivo, porque a consulta ao vivo não tinha resposta para "e
quando a ANS estiver fora?".

São 5.964 procedimentos na `tuss-22`; o CID-10 local, que já funciona
assim, tem 14.233. A ordem de grandeza é a mesma.

## O serviço

`https://consulta-ocl.apps.sa-1a.mendixcloud.com/rest/oclservice`

- `GET /ANS/source` — as tabelas disponíveis
- `GET /ANS/concepts/{tabela}?page=N&q=termo` — 25 itens por página

Sem autenticação, conferido na especificação OpenAPI publicada
(`securityDefinitions` vazio) e por chamada real.
"""

import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

BASE_URL = 'https://consulta-ocl.apps.sa-1a.mendixcloud.com/rest/oclservice'

#: Generoso: isto roda no worker, numa tarefa periódica, sem ninguém
#: esperando na tela. O aperto é o da busca, e a busca não passa por aqui.
REQUEST_TIMEOUT_SECONDS = 30

#: Quantas vezes insistir na **mesma** pagina antes de desistir da tabela.
#:
#: Nao e zelo excessivo: a API da ANS falha no meio de um download longo.
#: Numa execucao real ela nao respondeu na pagina 187 de umas 600, e como o
#: download e tudo-ou-nada -- de proposito, para nao gravar meia tabela --,
#: as 186 paginas ja baixadas foram descartadas. Sem repetir a pagina, uma
#: tabela desse tamanho tem chance real de **nunca** terminar.
PAGE_ATTEMPTS = 4

#: Espera entre as tentativas da mesma pagina, em segundos, crescendo.
#: Crescente porque a falha costuma ser o servidor sob carga: insistir no
#: mesmo ritmo piora o que se quer que melhore.
RETRY_BACKOFF_SECONDS = (2, 5, 15)

#: A tabela de procedimentos e eventos em saúde — a que se consulta ao
#: escrever um pedido de exame. As outras atendem faturamento hospitalar
#: (OPME tem 1,3 milhão de linhas), fora do escopo desta versão.
DEFAULT_TABLE = 'tuss-22'

PAGE_SIZE = 25

#: Teto de páginas. A `tuss-22` tem ~240; o limite existe para um defeito
#: de paginação do serviço — página que nunca esvazia — não virar um laço
#: infinito segurando o worker.
MAX_PAGES = 600

#: Pausa entre páginas. Duzentas e quarenta requisições em rajada contra um
#: serviço público gratuito é abuso, e a sincronização não tem pressa.
PAGE_PAUSE_SECONDS = 0.2


class TussUnavailable(Exception):
    """A ANS não respondeu, ou respondeu o que não se esperava.

    Mensagem legível, nunca o corpo cru: serviço externo que ecoa a
    requisição devolveria o que enviamos, e isso iria para um log.
    """


@dataclass(frozen=True)
class TussEntry:
    code: str
    description: str
    starts_on: str = ''
    ends_on: str = ''

    @property
    def in_force(self):
        """A ANS devolve `-` para vigência aberta, e a data quando encerrou."""
        return not self.ends_on or self.ends_on.strip() in {'', '-'}


def _parse_page(payload):
    """Converte uma página em entradas. Item malformado é descartado.

    Descartar, e não estourar: uma linha com formato inesperado no meio de
    vinte e cinco não deve abortar uma sincronização de duzentas páginas.
    """
    entradas = []
    if not isinstance(payload, list):
        return entradas
    for item in payload:
        if not isinstance(item, dict):
            continue
        codigo = str(item.get('id') or '').strip()
        descricao = str(item.get('display_name') or '').strip()
        if not codigo or not descricao:
            continue
        extras = item.get('extras') if isinstance(item.get('extras'), dict) else {}
        entradas.append(TussEntry(
            code=codigo,
            description=descricao,
            starts_on=str(extras.get('inicio_vigencia') or ''),
            ends_on=str(extras.get('fim_vigencia') or ''),
        ))
    return entradas


def _fetch_page(http, table, pagina):
    """Uma página, insistindo antes de desistir da tabela inteira.

    A falha que se espera aqui é passageira — servidor sob carga, conexão
    que caiu — e ela custa caro: como o download só grava no fim, desistir
    na página 187 joga fora 186 páginas. Insistir três vezes com espera
    crescente é barato perto disso.

    O que **não** se repete é resposta em formato inesperado: isso não é
    instabilidade, é a API ter mudado, e repetir só adia a descoberta.
    """
    ultima = None
    for tentativa in range(PAGE_ATTEMPTS):
        try:
            resposta = http.get(
                f'{BASE_URL}/ANS/concepts/{table}',
                params={'page': str(pagina)},
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={'Accept': 'application/json'},
            )
            resposta.raise_for_status()
            return _parse_page(resposta.json())
        except ValueError as exc:
            raise TussUnavailable(
                f'A ANS respondeu num formato inesperado na página {pagina}.'
            ) from exc
        except (requests.Timeout, requests.RequestException) as exc:
            ultima = exc
            if tentativa < PAGE_ATTEMPTS - 1:
                espera = RETRY_BACKOFF_SECONDS[min(tentativa, len(RETRY_BACKOFF_SECONDS) - 1)]
                logger.warning(
                    'tuss: pagina %s da tabela %s falhou (%s); nova tentativa em %ss',
                    pagina, table, type(exc).__name__, espera,
                )
                time.sleep(espera)

    motivo = 'não respondeu a tempo' if isinstance(ultima, requests.Timeout) else 'falhou'
    raise TussUnavailable(
        f'A ANS {motivo} na página {pagina} da tabela {table}, '
        f'mesmo após {PAGE_ATTEMPTS} tentativas.'
    ) from ultima


def fetch_table(table=DEFAULT_TABLE, session=None):
    """Baixa a tabela inteira, página a página. Levanta `TussUnavailable`.

    Roda no worker. Devolve a lista completa antes de qualquer escrita no
    banco: a alternativa — gravar enquanto baixa — deixaria uma tabela pela
    metade se a rede caísse na página 150, e meia tabela de procedimentos é
    pior que nenhuma, porque parece inteira.
    """
    http = session or requests.Session()
    entradas = []
    vistos = set()
    pagina = 1
    while pagina <= MAX_PAGES:
        lote = _fetch_page(http, table, pagina)

        if not lote:
            break
        novos = [e for e in lote if e.code not in vistos]
        # Página que repete a anterior inteira significa paginação que não
        # avança: parar aqui evita rodar até `MAX_PAGES` sem ganhar nada.
        if not novos:
            break
        for entrada in novos:
            vistos.add(entrada.code)
        entradas.extend(novos)
        pagina += 1
        time.sleep(PAGE_PAUSE_SECONDS)

    if not entradas:
        raise TussUnavailable(f'A ANS devolveu a tabela {table} vazia.')
    return entradas


def sync(table=DEFAULT_TABLE, actor=None):
    """Baixa a tabela e publica uma release nova do catálogo local.

    Usa a mesma maquinaria do CID-10 (`CatalogRelease` + `ProcedureCode`),
    e por isso herda o comportamento que importa: a release anterior vira
    `superseded` em vez de sumir, e o registro clínico que apontou para ela
    continua legível. Um pedido emitido no ano passado guarda o código e a
    descrição daquele momento — é isso que o prontuário precisa provar.

    Devolve a release criada.
    """
    from django.db import transaction
    from django.utils import timezone

    from catalogs.models import (
        CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode,
    )
    from catalogs.importers import normalize_for_search

    entradas = fetch_table(table)
    versao = f'ANS-{table}-{timezone.now():%Y%m%d}'

    with transaction.atomic():
        anterior = CatalogRelease.objects.filter(
            system=CatalogSystem.TUSS, status=CatalogReleaseStatus.ACTIVE,
        )
        release, _ = CatalogRelease.objects.get_or_create(
            system=CatalogSystem.TUSS, version=versao,
            defaults={
                'status': CatalogReleaseStatus.DRAFT,
                'license_note': (
                    'Tabela TUSS da ANS, obtida do serviço público de consulta OCL '
                    f'({BASE_URL}). Sincronizada automaticamente.'
                ),
            },
        )
        # Idempotente: re-sincronizar no mesmo dia substitui o conteudo em
        # vez de duplicar. Sem isto, duas execucoes deixariam a release com
        # o dobro das linhas e a contagem da tela mentiria.
        ProcedureCode.objects.filter(release=release).delete()
        ProcedureCode.objects.bulk_create([
            ProcedureCode(
                release=release, code=e.code, description=e.description,
                search_text=normalize_for_search(f'{e.code} {e.description}'),
                active=e.in_force,
            )
            for e in entradas
        ], batch_size=1000)

        anterior.exclude(id=release.id).update(status=CatalogReleaseStatus.SUPERSEDED)
        release.status = CatalogReleaseStatus.ACTIVE
        release.imported_at = timezone.now()
        release.save(update_fields=['status', 'imported_at', 'updated_at'])

    return release
