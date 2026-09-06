import subprocess
import tempfile
from pathlib import Path

from .models import AttachmentScanStatus

PREVIEW_TIMEOUT_SECONDS = 15
PREVIEW_DPI = 72


class PreviewUnavailable(Exception):
    pass


def render_preview_png(attachment):
    """Renders a static, non-executable PNG preview of page 1 only —
    bounded by timeout/DPI so a large file cannot monopolize the worker.
    Returns bytes, or raises PreviewUnavailable (e.g. DOCX has no preview
    renderer in this scope).
    """
    if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
        raise PreviewUnavailable('Attachment is not available')
    extension = attachment.original_name.rsplit('.', 1)[-1].lower()
    with tempfile.TemporaryDirectory() as tmp:
        out_prefix = str(Path(tmp) / 'preview')
        if extension == 'pdf':
            try:
                subprocess.run(
                    ['pdftoppm', '-png', '-f', '1', '-l', '1', '-r', str(PREVIEW_DPI),
                     attachment.storage_key, out_prefix],
                    check=True, capture_output=True, timeout=PREVIEW_TIMEOUT_SECONDS,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
                raise PreviewUnavailable(str(exc)) from exc
            candidates = sorted(Path(tmp).glob('preview*.png'))
            if not candidates:
                raise PreviewUnavailable('No page rendered')
            return candidates[0].read_bytes()
        if extension in ('jpg', 'jpeg', 'png', 'tiff', 'tif'):
            from PIL import Image

            with Image.open(attachment.storage_key) as image:
                image.thumbnail((800, 800))
                out_path = Path(tmp) / 'thumb.png'
                image.convert('RGB').save(out_path, format='PNG')
                return out_path.read_bytes()
    raise PreviewUnavailable(f'No preview renderer for .{extension}')
