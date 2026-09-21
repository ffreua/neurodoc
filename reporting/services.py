import os
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from audit.services import record_audit_event

from .exporters import export_csv, export_json, export_markdown_table
from .models import ReportExport, ReportExportKind, ReportExportStatus

#: Acima disto a exportação vai para o worker. Conferido por `COUNT` antes
#: de qualquer leitura — medir depois de montar não é limite, é relatório.
SYNC_ROW_LIMIT = 1000
EXPORT_TTL_HOURS = 24


class ReportNotFound(Exception):
    pass


class ReportNotAllowed(Exception):
    """Quem pediu não tem a capacidade que o relatório exige."""


#: Extensão e tipo MIME por formato. `text/markdown` é o tipo registrado
#: (RFC 7763); `charset=utf-8` porque nome de paciente tem acento e o
#: navegador que adivinha erra para latin-1 na primeira exportação.
FORMATOS = {
    ReportExportKind.CSV: ('csv', 'text/csv; charset=utf-8'),
    ReportExportKind.MD: ('md', 'text/markdown; charset=utf-8'),
    ReportExportKind.JSON: ('json', 'application/json; charset=utf-8'),
}


# Registry of exportable reports: name -> (rows_fn(tenant, **params) -> list[dict], fieldnames).
# Deliberately small: this sprint wires the mechanism (sync/async threshold,
# CSV sanitization, private storage, expiry, notification), not every
# indicator in the dictionary -- new reports register here without
# touching the export machinery itself.
_REGISTRY = {}


def register_report(name, rows_fn, fieldnames, count_fn=None,
                    markdown_fn=None, capability=None, kinds=None):
    """Registra um relatório exportável.

    `count_fn(tenant, **params) -> int` é opcional e conta **sem montar as
    linhas** — um `COUNT` no banco. É ela que decide se a exportação cabe
    na requisição. Um relatório que não a fornece vai direto para a fila:
    é a resposta segura para "não sei quanto isto pesa", e a errada seria
    descobrir montando.

    `capability` é a capacidade exigida para pedir **este** relatório, e
    não é opcional por conveniência. `ExportRequestView` recebe o nome do
    relatório pelo POST: sem uma capacidade por relatório, bastaria a
    capacidade da tela — o painel gerencial — para pedir qualquer coisa
    registrada, incluindo o acervo clínico inteiro. A verificação mora
    aqui, e não na view, justamente porque views novas aparecem e esta é
    a porta por onde todas passam.

    Aceita **várias**, e então exige todas. O acervo clínico precisa
    disso: `MANAGE_ORGANIZATION` diz quem tem direito de levar os dados
    embora — a CONTRATANTE do contrato, que é o dono —, e `READ_CLINICAL`
    diz quem pode ler prontuário. Uma só das duas abriria uma porta que a
    tela não abre: o dono não médico baixaria todas as notas clínicas, ou
    qualquer médico baixaria o acervo inteiro da clínica.

    `markdown_fn(rows, **params) -> str` desenha o Markdown quando tabela
    não serve. Sem ela, Markdown sai como tabela — que é o certo para
    indicador e o errado para prontuário.

    `kinds` restringe os formatos. `None` libera os três que o motor
    escreve; um relatório de texto longo declara só `MD` e `JSON`, porque
    oferecer CSV de nota clínica é oferecer um arquivo que ninguém
    consegue ler.
    """
    if capability is None:
        raise ValueError(f'Relatório {name} registrado sem capacidade exigida')
    exigidas = (capability,) if isinstance(capability, str) else tuple(capability)
    _REGISTRY[name] = {
        'rows_fn': rows_fn, 'fieldnames': fieldnames, 'count_fn': count_fn,
        'markdown_fn': markdown_fn, 'capabilities': exigidas,
        'kinds': frozenset(kinds or FORMATOS),
    }


def _export_dir(tenant_id):
    path = Path(settings.MEDIA_ROOT) / str(tenant_id) / 'reports'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _conteudo(export, rows, fieldnames, markdown_fn):
    """O arquivo, no formato pedido. Um lugar só decide isto.

    Estava espalhado: a requisição escrevia CSV e o worker escrevia CSV,
    cada um com a própria linha. Com três formatos, duas cópias viram
    duas oportunidades de o worker gerar um arquivo diferente do que a
    tela gerou para o mesmo relatório.
    """
    if export.kind == ReportExportKind.JSON:
        return export_json(rows)
    if export.kind == ReportExportKind.MD:
        if markdown_fn is not None:
            return markdown_fn(rows, **(export.parameters or {}))
        return export_markdown_table(rows, fieldnames, titulo=export.report_name)
    return export_csv(rows, fieldnames)


def _write_export_file(export, rows, fieldnames, markdown_fn=None):
    extensao = FORMATOS.get(export.kind, ('txt', 'text/plain'))[0]
    content = _conteudo(export, rows, fieldnames, markdown_fn).encode('utf-8')
    path = _export_dir(export.tenant_id) / f'{export.id}.{extensao}'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(content)
    export.storage_key = str(path)
    export.row_count = len(rows)
    export.status = ReportExportStatus.READY
    export.expires_at = timezone.now() + timezone.timedelta(hours=EXPORT_TTL_HOURS)
    export.save(update_fields=['storage_key', 'row_count', 'status', 'expires_at'])


def request_export(access_context, membership, report_name, parameters,
                   kind=ReportExportKind.CSV):
    """Pede uma exportação. A autorização é conferida **aqui**.

    Não na view: o nome do relatório vem do POST, e a view sabe apenas que
    quem chegou tem a capacidade *dela*. Conferir no registro é o que
    impede que a capacidade de abrir o painel gerencial valha como
    capacidade de baixar o acervo clínico da clínica inteira.
    """
    if report_name not in _REGISTRY:
        raise ReportNotFound(report_name)
    registro = _REGISTRY[report_name]
    faltando = [c for c in registro['capabilities'] if not access_context.can(c)]
    if faltando:
        # A recusa entra na trilha. Pedido de exportação negado é sinal de
        # tela desalinhada com a matriz -- ou de alguém tentando pela
        # porta do POST --, e nos dois casos alguém precisa ver.
        record_audit_event(
            access_context.user_id, access_context.tenant_id, 'reporting.export_denied',
            object_type='report_export', object_id=None, outcome='denied',
            integrity_metadata={'report': report_name, 'faltando': faltando},
        )
        raise ReportNotAllowed(report_name)
    if kind not in registro['kinds']:
        raise ReportNotAllowed(f'{report_name}:{kind}')
    rows_fn = registro['rows_fn']
    fieldnames = registro['fieldnames']
    count_fn = registro['count_fn']

    export = ReportExport.objects.create(
        tenant_id=access_context.tenant_id, requested_by=membership, kind=kind,
        report_name=report_name, parameters=parameters, status=ReportExportStatus.RUNNING,
    )

    # A decisão vem **antes** da leitura. Até esta correção o relatório
    # inteiro era montado na requisição e só então se perguntava se ele era
    # grande demais para ser montado na requisição — a resposta chegava
    # depois de o estrago estar feito, e o limite não protegia de nada.
    # Agora um `COUNT` decide, e o relatório grande nunca chega a ser lido
    # aqui: quem o monta é o worker.
    cabe_na_requisicao = False
    if count_fn is not None:
        cabe_na_requisicao = count_fn(access_context.tenant_id, **parameters) <= SYNC_ROW_LIMIT

    if cabe_na_requisicao:
        started = time.monotonic()
        rows = rows_fn(access_context.tenant_id, **parameters)
        elapsed = time.monotonic() - started
        _write_export_file(export, rows, fieldnames, registro['markdown_fn'])
        record_audit_event(
            access_context.user_id, access_context.tenant_id, 'reporting.export_completed_sync',
            object_type='report_export', object_id=export.id, outcome='success',
            integrity_metadata={
            'rows': len(rows), 'seconds': round(elapsed, 3),
            'report': report_name, 'kind': kind,
        },
        )
        return export

    # Grande, ou de tamanho desconhecido: vai para o Celery sem ser lido.
    export.status = ReportExportStatus.QUEUED
    export.save(update_fields=['status'])
    from .tasks import run_export

    run_export.delay(str(export.id))
    record_audit_event(
        access_context.user_id, access_context.tenant_id, 'reporting.export_queued',
        object_type='report_export', object_id=export.id, outcome='success',
        integrity_metadata={'report': report_name, 'kind': kind},
    )
    return export


def expire_due_exports():
    due = ReportExport.objects.filter(status=ReportExportStatus.READY, expires_at__lte=timezone.now())
    count = 0
    for export in due:
        if export.storage_key:
            Path(export.storage_key).unlink(missing_ok=True)
        export.storage_key = ''
        export.status = ReportExportStatus.EXPIRED
        export.save(update_fields=['storage_key', 'status'])
        count += 1
    return count
