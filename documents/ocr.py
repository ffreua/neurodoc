import subprocess
import tempfile
from pathlib import Path

from django.db import transaction

from .models import Attachment, AttachmentOcrPage, AttachmentScanStatus, MAX_ATTACHMENT_PAGES

OCR_TIMEOUT_SECONDS = 30


class OcrError(Exception):
    pass


def _rasterize_pdf_pages(path, tmp_dir):
    out_prefix = str(Path(tmp_dir) / 'page')
    subprocess.run(
        ['pdftoppm', '-png', '-r', '150', '-l', str(MAX_ATTACHMENT_PAGES), path, out_prefix],
        check=True, capture_output=True, timeout=OCR_TIMEOUT_SECONDS * MAX_ATTACHMENT_PAGES,
    )
    return sorted(Path(tmp_dir).glob('page*.png'))


def _tesseract_text(image_path):
    result = subprocess.run(
        ['tesseract', str(image_path), 'stdout', '-l', 'por'],
        capture_output=True, text=True, timeout=OCR_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise OcrError(result.stderr.strip()[:255])
    return result.stdout


@transaction.atomic
def run_ocr(attachment: Attachment):
    """Extracts text locally (tesseract, pt-BR); never sends the file or its
    content anywhere external. Text is stored per page for provenance.
    """
    if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
        raise OcrError('Attachment is not available')
    extension = attachment.original_name.rsplit('.', 1)[-1].lower()
    AttachmentOcrPage.objects.filter(attachment=attachment).delete()
    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        if extension == 'pdf':
            try:
                image_paths = _rasterize_pdf_pages(attachment.storage_key, tmp)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
                raise OcrError(str(exc)) from exc
        else:
            image_paths = [Path(attachment.storage_key)]
        for page_number, image_path in enumerate(image_paths, start=1):
            text = _tesseract_text(image_path)
            page = AttachmentOcrPage.objects.create(
                tenant_id=attachment.tenant_id, attachment=attachment,
                page_number=page_number, text=text, engine='tesseract',
            )
            pages.append(page)
    return pages
