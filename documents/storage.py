import gzip
import hashlib
import io
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from .models import Attachment, AttachmentClassification, AttachmentScanStatus
from .validators import validate_upload

DEFAULT_TENANT_QUOTA_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB, overridable via Tenant.settings

#: Sufixo do arquivo comprimido. Fica no `storage_key` porque é o que
#: permite saber, olhando só a linha do banco, se o arquivo no disco está
#: comprimido — sem abrir o disco para descobrir.
COMPRESSED_SUFFIX = '.gz'


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
        raise QuotaExceeded(
            f'Espaço de arquivos esgotado: a clínica já usa '
            f'{used // (1024 * 1024)} MB de {tenant_quota_bytes(tenant) // (1024 * 1024)} MB.'
        )


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
        raise PermissionError('Este anexo não está disponível.')
    if is_compressed(attachment):
        return io.BytesIO(read_bytes(attachment))
    return open(attachment.storage_key, 'rb')


def is_compressed(attachment):
    return bool(attachment.storage_key) and attachment.storage_key.endswith(COMPRESSED_SUFFIX)


def read_bytes(attachment):
    """Os bytes do arquivo, comprimido ou não.

    Existe porque o arquivo passou a poder estar comprimido no disco
    (`documents.archive`), e havia seis lugares abrindo `storage_key`
    direto — a tela de download, o link do paciente, a pré-visualização, o
    OCR e duas rotinas da IA. Um caminho de leitura só é o que faz a
    compressão ser invisível para todos eles.

    O que sai daqui são sempre os bytes originais: o mesmo SHA-256 que foi
    gravado na emissão, e no caso do documento assinado os mesmos bytes que
    a assinatura cobre.
    """
    if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
        raise PermissionError('Este anexo não está disponível.')
    if not attachment.storage_key:
        raise FileNotFoundError('Attachment has no stored file')
    if is_compressed(attachment):
        with gzip.open(attachment.storage_key, 'rb') as fh:
            return fh.read()
    with open(attachment.storage_key, 'rb') as fh:
        return fh.read()


@contextmanager
def local_path(attachment):
    """Um caminho de arquivo real, para ferramenta externa.

    `pdftoppm`, o OCR e a extração de texto recebem um caminho, não bytes.
    Quando o arquivo está comprimido, o conteúdo é escrito num temporário
    que some ao fim do bloco — e é por isso que isto é um gerenciador de
    contexto, e não uma função que devolve um caminho: sem o fim do bloco
    não haveria momento certo para apagar o temporário.
    """
    if not is_compressed(attachment):
        yield attachment.storage_key
        return
    content = read_bytes(attachment)
    suffix = Path(attachment.original_name).suffix or '.bin'
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        handle.write(content)
        handle.close()
        yield handle.name
    finally:
        Path(handle.name).unlink(missing_ok=True)


def store_generated_attachment(tenant, patient, uploaded_by, content, original_name,
                                classification=AttachmentClassification.ADMINISTRATIVE, encounter=None):
    """For server-synthesized files (rendered/signed PDFs) rather than
    user uploads: no malware risk from content this application generated
    itself, so this skips quarantine/ClamAV entirely and publishes straight
    to AVAILABLE, deduped by sha256 exactly like publish_from_quarantine.
    """
    sha256 = hashlib.sha256(content).hexdigest()
    final_dir = _published_dir(tenant.id) / sha256
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / original_name
    if not final_path.exists():
        fd = os.open(final_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as fh:
            fh.write(content)
    return Attachment.objects.create(
        tenant=tenant, patient=patient, encounter=encounter, storage_key=str(final_path),
        original_name=original_name, mime='application/pdf', bytes=len(content), sha256=sha256,
        classification=classification, scan_status=AttachmentScanStatus.AVAILABLE, uploaded_by=uploaded_by,
    )
