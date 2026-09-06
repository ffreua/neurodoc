import os
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from audit.services import record_audit_event

from .exporters import export_csv
from .models import ReportExport, ReportExportKind, ReportExportStatus

SYNC_ROW_LIMIT = 1000
SYNC_TIME_LIMIT_SECONDS = 5
EXPORT_TTL_HOURS = 24


class ReportNotFound(Exception):
    pass


# Registry of exportable reports: name -> (rows_fn(tenant, **params) -> list[dict], fieldnames).
# Deliberately small: this sprint wires the mechanism (sync/async threshold,
# CSV sanitization, private storage, expiry, notification), not every
# indicator in the dictionary -- new reports register here without
# touching the export machinery itself.
_REGISTRY = {}


def register_report(name, rows_fn, fieldnames):
    _REGISTRY[name] = (rows_fn, fieldnames)


def _export_dir(tenant_id):
    path = Path(settings.MEDIA_ROOT) / str(tenant_id) / 'reports'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_csv_file(export, rows, fieldnames):
    content = export_csv(rows, fieldnames).encode('utf-8')
    path = _export_dir(export.tenant_id) / f'{export.id}.csv'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(content)
    export.storage_key = str(path)
    export.row_count = len(rows)
    export.status = ReportExportStatus.READY
    export.expires_at = timezone.now() + timezone.timedelta(hours=EXPORT_TTL_HOURS)
    export.save(update_fields=['storage_key', 'row_count', 'status', 'expires_at'])


def request_export(access_context, membership, report_name, parameters, kind=ReportExportKind.CSV):
    if report_name not in _REGISTRY:
        raise ReportNotFound(report_name)
    rows_fn, fieldnames = _REGISTRY[report_name]

    export = ReportExport.objects.create(
        tenant_id=access_context.tenant_id, requested_by=membership, kind=kind,
        report_name=report_name, parameters=parameters, status=ReportExportStatus.RUNNING,
    )
    started = time.monotonic()
    rows = rows_fn(access_context.tenant_id, **parameters)
    elapsed = time.monotonic() - started

    if len(rows) <= SYNC_ROW_LIMIT and elapsed <= SYNC_TIME_LIMIT_SECONDS:
        _write_csv_file(export, rows, fieldnames)
        record_audit_event(
            access_context.user_id, access_context.tenant_id, 'reporting.export_completed_sync',
            object_type='report_export', object_id=export.id, outcome='success',
        )
        return export

    # Large/slow: hand off to Celery, never block the request.
    export.status = ReportExportStatus.QUEUED
    export.save(update_fields=['status'])
    from .tasks import run_export

    run_export.delay(str(export.id))
    record_audit_event(
        access_context.user_id, access_context.tenant_id, 'reporting.export_queued',
        object_type='report_export', object_id=export.id, outcome='success',
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
