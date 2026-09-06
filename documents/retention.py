from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import Attachment, AttachmentScanStatus

BACKUP_LOCK_PATH = Path('/data/media/.backup_lock')
GC_MIN_AGE_DAYS = 30


class BackupInProgress(Exception):
    pass


def backup_lock_active():
    return BACKUP_LOCK_PATH.exists()


@transaction.atomic
def soft_delete_attachment(attachment, actor_id, reason):
    """Logical removal only — the file stays on disk until the GC pass
    considers it eligible; a deleted row is simply excluded from listings
    and downloads.
    """
    attachment.deleted_at = timezone.now()
    attachment.deleted_reason = reason[:255]
    attachment.save(update_fields=['deleted_at', 'deleted_reason'])
    record_audit_event(
        actor_id, attachment.tenant_id, 'documents.attachment_soft_deleted',
        object_type='attachment', object_id=attachment.id, outcome='success',
    )
    return attachment


def garbage_collect(dry_run=True):
    """Physically deletes the on-disk file for attachments soft-deleted long
    enough ago, skipping entirely while a backup is in progress and never
    touching a file another Attachment row still references by storage_key.
    """
    if backup_lock_active():
        raise BackupInProgress('Backup lock present; GC refuses to run')

    cutoff = timezone.now() - timezone.timedelta(days=GC_MIN_AGE_DAYS)
    candidates = Attachment.objects.filter(
        deleted_at__isnull=False, deleted_at__lt=cutoff,
    ).exclude(scan_status=AttachmentScanStatus.REJECTED)

    removed = []
    for attachment in candidates:
        if not attachment.storage_key:
            continue
        still_referenced = Attachment.objects.filter(
            storage_key=attachment.storage_key, deleted_at__isnull=True,
        ).exclude(id=attachment.id).exists()
        if still_referenced:
            continue
        removed.append(attachment.id)
        if not dry_run:
            Path(attachment.storage_key).unlink(missing_ok=True)
            attachment.storage_key = ''
            attachment.save(update_fields=['storage_key'])
    return removed
