"""Espelho local da tabela TUSS, alimentado pela API pública da ANS.

## Por que espelho, e não consulta ao vivo

A primeira versão deste módulo consultava a ANS a cada busca. O argumento
era bom — a TUSS muda por resolução normativa, e uma cópia local vira
desatualizada sem avisar, com a glosa aparecendo na fatura — e mesmo assim
estava errado, por uma razão que só apareceu ao rodar:

**a ANS é lenta demais para caber numa requisição.** Leva ~80 segundos
por página de 25 itens e ignora pedido de página maior. Uma chamada
síncrona a partir de uma view não falharia em desenvolvimento, onde a
busca é uma só — prenderia a tela no tempo da ANS em produção, com o
médico esperando.

Trabalho que fala com serviço externo é do `celery_worker`, que está em
`neurodoc_v1_egress` e pode tentar de novo. O `app` **também** alcança a
internet, pela `traefik_public` — ver `CLAUDE.md` §2; o motivo de não
chamar daqui é o tempo e a retentativa, não a rede.

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
#: A ANS leva de 70 a 155 segundos para devolver **uma** página de 25
#: itens -- medido em outubro de 2026, com o serviço no ar. Trinta
#: segundos era o valor anterior, e era por isso que toda sincronização
#: falhava: o diagnóstico dizia "a ANS não respondeu" quando o que havia
#: acontecido era a nossa paciência ter acabado antes dela.
#:
#: Cento e oitenta dá folga sobre o pior caso medido. Isto roda no worker,
#: numa tarefa periódica, sem ninguém esperando na tela.
REQUEST_TIMEOUT_SECONDS = 180

#: Teto da sonda de diagnóstico (`_diagnostico`). Curto de propósito: ela
#: roda **depois** de a sincronização já ter falhado, e quem espera a
#: mensagem de erro não deve esperar mais meio minuto por ela.
SONDA_TIMEOUT_SECONDS = 10

#: Quantas vezes insistir na **mesma** pagina antes de desistir da tabela.
#:
#: Nao e zelo excessivo: a API da ANS falha no meio de um download longo.
#: Numa execucao real ela nao respondeu na pagina 187 de umas 600, e como o
#: download e tudo-ou-nada -- de proposito, para nao gravar meia tabela --,
#: as 186 paginas ja baixadas foram descartadas. Sem repetir a pagina, uma
#: tabela desse tamanho tem chance real de **nunca** terminar.
PAGE_ATTEMPTS = 4

#: Quanto tempo uma rodada da sincronização incremental usa buscando
#: páginas. Fica abaixo do limite da tarefa (`soft_time_limit` em
#: `catalogs/tasks.py`) com folga para a gravação e para a página em voo.
ORCAMENTO_PADRAO_SEGUNDOS = 40 * 60

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
        f'mesmo após {PAGE_ATTEMPTS} tentativas. {_diagnostico(http)}'
    ) from ultima


def _diagnostico(http):
    """Uma frase dizendo de quem é o problema.

    Timeout sozinho é ambíguo e manda procurar no lugar errado: parece
    rede do servidor, firewall, proxy, DNS. Quem recebe isso vai conferir
    o egresso do worker, e o egresso está bom.

    `/ANS/source` é o **outro** endpoint da mesma API (o catálogo de
    tabelas). Ele é barato, devolve poucos KB e não pagina. Se ele responde
    e o de conceitos não, a aplicação da ANS está no ar e é o endpoint de
    dados que está quebrado -- o que encerra a investigação do nosso lado e
    é exatamente a evidência que um chamado à ANS precisa.

    Isto foi descoberto à mão, em 26/09/2026, quando a sincronização falhou
    três vezes em dois dias: `/ANS/source` respondia em 0,3s enquanto
    `/ANS/concepts/` travava até para a tabela de **dois** registros --
    inclusive no exemplo publicado pela própria ANS na documentação dela.
    Está codificado aqui para ninguém repetir o diagnóstico.

    Nunca levanta: é texto para uma mensagem de erro, e falhar ao explicar
    uma falha só troca a mensagem útil por outra pior.
    """
    try:
        resposta = http.get(
            f'{BASE_URL}/ANS/source', timeout=SONDA_TIMEOUT_SECONDS,
            headers={'Accept': 'application/json'},
        )
        if resposta.ok:
            return (
                'O catálogo de tabelas da ANS (/ANS/source) respondeu normalmente, '
                'então a aplicação deles está no ar e é o endpoint de conceitos que '
                'não responde — é do lado da ANS, e não desta instalação. '
                'A sincronização semanal tenta de novo no domingo.'
            )
        return (
            f'O catálogo de tabelas da ANS devolveu HTTP {resposta.status_code}: '
            'o serviço deles está com problema.'
        )
    except requests.RequestException:
        return (
            'O catálogo de tabelas da ANS também não respondeu: ou a ANS está fora '
            'do ar, ou este servidor perdeu a saída para a internet. Confira o '
            'egresso do worker antes de abrir chamado.'
        )


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


def sync_incremental(table=DEFAULT_TABLE, orcamento_segundos=None):
    """Avança a sincronização o quanto couber no tempo, e retoma na próxima.

    **Por que não baixar tudo de uma vez.** A ANS leva ~80 segundos por
    página de 25 itens e ignora qualquer pedido de página maior. A `tuss-22`
    tem 5.964 procedimentos, ou seja ~240 páginas: mais de cinco horas numa
    única execução. O limite de tarefa do Celery é de minutos, e uma tarefa
    de cinco horas seria morta no meio — sempre, toda semana, sem nunca
    completar.

    **O progresso é a própria release em rascunho.** Não há tabela de
    estado nem contador em cache: o que já foi baixado está gravado como
    `ProcedureCode` de uma `CatalogRelease` com status `DRAFT`, e a próxima
    página é deduzida de quantos códigos ela já tem. Estado que vive em
    dois lugares divergiria; aqui ele vive num.

    E, enquanto está em rascunho, **a busca não a vê**: `active_release`
    devolve a release ativa, que continua sendo a anterior. Meia tabela de
    procedimentos é pior que nenhuma — ela parece inteira.

    Devolve `{'completo', 'paginas', 'total', 'versao'}`.
    """
    from django.db import transaction
    from django.utils import timezone

    from catalogs.importers import normalize_for_search
    from catalogs.models import (
        CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode,
    )

    orcamento = orcamento_segundos or ORCAMENTO_PADRAO_SEGUNDOS
    http = requests.Session()

    # A versão não carrega a data de hoje: uma sincronização que atravessa
    # a meia-noite começaria uma release nova e recomeçaria do zero.
    versao = f'ANS-{table}'
    release, _ = CatalogRelease.objects.get_or_create(
        system=CatalogSystem.TUSS, version=versao,
        defaults={
            'status': CatalogReleaseStatus.DRAFT,
            'license_note': (
                'Tabela TUSS da ANS, obtida do serviço público de consulta OCL '
                f'({BASE_URL}). Sincronizada automaticamente, em etapas.'
            ),
        },
    )
    if release.status == CatalogReleaseStatus.ACTIVE:
        # Já está completa e publicada. Uma nova rodada recomeça o rascunho
        # do zero, para que a tabela seja refeita e não remendada: código
        # que a ANS retirou precisa sair, e remendo não remove.
        release.status = CatalogReleaseStatus.DRAFT
        release.save(update_fields=['status', 'updated_at'])
        ProcedureCode.objects.filter(release=release).delete()

    ja_tem = ProcedureCode.objects.filter(release=release).count()
    vistos = set(
        ProcedureCode.objects.filter(release=release).values_list('code', flat=True)
    )
    pagina = ja_tem // PAGE_SIZE + 1

    inicio = time.monotonic()
    paginas_feitas = 0
    completo = False
    while pagina <= MAX_PAGES:
        if time.monotonic() - inicio > orcamento:
            break
        lote = _fetch_page(http, table, pagina)
        paginas_feitas += 1
        if not lote:
            completo = True
            break
        novos = [e for e in lote if e.code not in vistos]
        if not novos:
            # Página que repete a anterior inteira é paginação que não
            # avança: a tabela acabou.
            completo = True
            break
        ProcedureCode.objects.bulk_create([
            ProcedureCode(
                release=release, code=e.code, description=e.description,
                search_text=normalize_for_search(f'{e.code} {e.description}'),
                active=e.in_force,
            )
            for e in novos
        ], batch_size=1000)
        vistos.update(e.code for e in novos)
        pagina += 1
        time.sleep(PAGE_PAUSE_SECONDS)

    total = ProcedureCode.objects.filter(release=release).count()
    if completo and total:
        with transaction.atomic():
            CatalogRelease.objects.filter(
                system=CatalogSystem.TUSS, status=CatalogReleaseStatus.ACTIVE,
            ).exclude(id=release.id).update(status=CatalogReleaseStatus.SUPERSEDED)
            release.status = CatalogReleaseStatus.ACTIVE
            release.imported_at = timezone.now()
            release.save(update_fields=['status', 'imported_at', 'updated_at'])
    return {
        'completo': completo, 'paginas': paginas_feitas,
        'total': total, 'versao': versao,
    }


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
