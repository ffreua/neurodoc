from celery import shared_task

from integrations.antivirus import DefinitionUpdateFailed, ScanInfected, ScanUnavailable, scan_file, update_definitions

from .models import Attachment, AttachmentScanStatus
from .storage import publish_from_quarantine, reject_and_discard


@shared_task(name='documents.tasks.scan_attachment', expires=600)
def scan_attachment(attachment_id):
    attachment = Attachment.objects.filter(id=attachment_id, scan_status=AttachmentScanStatus.QUARANTINED).first()
    if attachment is None:
        return {'skipped': True}
    try:
        scan_file(attachment.storage_key)
    except ScanInfected as exc:
        reject_and_discard(attachment, f'Malware detected: {exc.signature}')
        return {'status': 'rejected', 'signature': exc.signature}
    except ScanUnavailable as exc:
        attachment.scan_error = str(exc)[:255]
        attachment.save(update_fields=['scan_error'])
        return {'status': 'quarantined', 'error': str(exc)}
    publish_from_quarantine(attachment)
    return {'status': 'available'}


@shared_task(name='documents.tasks.update_clamav_definitions', expires=3600)
def update_clamav_definitions():
    """Runs every 6h from Celery beat (see CELERY_BEAT_SCHEDULE); a failure
    here just leaves the existing definitions in place — scan_attachment
    keeps failing closed (ScanUnavailable) if they go stale enough that
    clamscan itself refuses them.
    """
    try:
        update_definitions()
    except DefinitionUpdateFailed as exc:
        return {'status': 'failed', 'error': str(exc)}
    return {'status': 'updated'}
