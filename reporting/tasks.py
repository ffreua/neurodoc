from celery import shared_task

from .models import ReportExport, ReportExportStatus


@shared_task(name='reporting.tasks.run_export', expires=3600)
def run_export(export_id):
    from .services import _REGISTRY, _write_export_file

    export = ReportExport.objects.filter(id=export_id).first()
    if export is None:
        return {'status': 'skipped'}
    # Sem reconferir capacidade: quem podia pedir foi conferido em
    # `request_export`, e o worker roda sem requisicao e sem
    # `access_context`. Reconferir aqui exigiria carregar o vinculo de
    # novo -- e um vinculo revogado no meio do caminho cancelaria uma
    # exportacao que a pessoa tinha direito de pedir no momento do pedido.
    registro = _REGISTRY[export.report_name]
    try:
        rows = registro['rows_fn'](export.tenant_id, **export.parameters)
        _write_export_file(export, rows, registro['fieldnames'], registro['markdown_fn'])
    except Exception as exc:
        export.status = ReportExportStatus.FAILED
        export.save(update_fields=['status'])
        return {'status': 'failed', 'error': str(exc)}

    from notifications.services import notify_user

    notify_user(
        export.tenant, export.requested_by.user_id, kind='report_export_ready',
        sanitized_title=f'Exportação "{export.report_name}" pronta para download',
        target_type='report_export', target_id=export.id,
    )
    return {'status': 'ready', 'row_count': export.row_count}


@shared_task(name='reporting.tasks.expire_exports')
def expire_exports():
    from .services import expire_due_exports

    return {'expired': expire_due_exports()}
