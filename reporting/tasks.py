from celery import shared_task

from .models import ReportExport, ReportExportStatus


@shared_task(name='reporting.tasks.run_export', expires=3600)
def run_export(export_id):
    from .services import _REGISTRY, _write_csv_file

    export = ReportExport.objects.filter(id=export_id).first()
    if export is None:
        return {'status': 'skipped'}
    rows_fn, fieldnames, _count_fn = _REGISTRY[export.report_name]
    try:
        rows = rows_fn(export.tenant_id, **export.parameters)
        _write_csv_file(export, rows, fieldnames)
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
