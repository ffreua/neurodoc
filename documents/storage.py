import hashlib
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from .models import Attachment, AttachmentClassification, AttachmentScanStatus
from .validators import validate_upload

DEFAULT_TENANT_QUOTA_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB, overridable via Tenant.settings


class QuotaExceeded(Exception):
    pass


def _quarantine_dir(tenant_id):
    path = Path(settings.MEDIA_ROOT) / str(tenant_id) / '.quarantine'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _published_dir(tenant_id):
    path = Path(settings.MEDIA_ROOT) / str(tenant_id) / 'published'
    path.mkdir(parents=True, exist_ok=True)
    return path


def tenant_quota_bytes(tenant):
    return int((tenant.settings or {}).get('attachment_quota_bytes', DEFAULT_TENANT_QUOTA_BYTES))


def check_tenant_quota(tenant, incoming_bytes):
    used = Attachment.objects.filter(tenant=tenant, deleted_at=None).exclude(
        scan_status=AttachmentScanStatus.REJECTED,
    ).aggregate(total=Sum('bytes'))['total'] or 0
    if used + incoming_bytes > tenant_quota_bytes(tenant):
        raise QuotaExceeded(f'Tenant quota exceeded ({used + incoming_bytes} > {tenant_quota_bytes(tenant)} bytes)')


@transaction.atomic
def receive_upload(context, tenant, patient, uploaded_by, content, original_name, classification, encounter=None, document_date=None):
    """Validates and writes the file into per-tenant quarantine. The
    Attachment row is created with scan_status=quarantined and no
    storage_key yet resolvable to the final path — nothing is available for
    download until the scan task publishes it.
    """
    check_tenant_quota(tenant, len(content))
    safe_name, mime = validate_upload(content, original_name)
    sha256 = hashlib.sha256(content).hexdigest()

    quarantine_key = f'{uuid.uuid4().hex}_{safe_name}'
    quarantine_path = _quarantine_dir(tenant.id) / quarantine_key
    fd = os.open(quarantine_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(content)
    except BaseException:
        quarantine_path.unlink(missing_ok=True)
        raise

    attachment = Attachment.objects.create(
        tenant=tenant, patient=patient, encounter=encounter, storage_key=str(quarantine_path),
        original_name=safe_name, mime=mime, bytes=len(content), sha256=sha256,
        classification=classification, scan_status=AttachmentScanStatus.QUARANTINED,
        uploaded_by=uploaded_by, document_date=document_date,
    )
    return attachment


def publish_from_quarantine(attachment):
    """Atomically moves a clean file from quarantine into the published
    area, keyed by sha256 so an identical file is never duplicated and an
    already-published original is never overwritten.
    """
    published_dir = _published_dir(attachment.tenant_id)
    final_dir = published_dir / attachment.sha256
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / attachment.original_name
    quarantine_path = Path(attachment.storage_key)
    if not final_path.exists():
        os.replace(quarantine_path, final_path)
    else:
        quarantine_path.unlink(missing_ok=True)
    attachment.storage_key = str(final_path)
    attachment.scan_status = AttachmentScanStatus.AVAILABLE
    attachment.save(update_fields=['storage_key', 'scan_status'])
    return attachment


def reject_and_discard(attachment, reason):
    quarantine_path = Path(attachment.storage_key)
    quarantine_path.unlink(missing_ok=True)
    attachment.scan_status = AttachmentScanStatus.REJECTED
    attachment.scan_error = reason[:255]
    attachment.storage_key = ''
    attachment.save(update_fields=['scan_status', 'scan_error', 'storage_key'])
    return attachment


def open_for_read(attachment):
    if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
        raise PermissionError('Attachment is not available')
    return open(attachment.storage_key, 'rb')
