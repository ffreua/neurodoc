import os
import re
import zipfile

import magic

from .models import ALLOWED_EXTENSIONS, MAX_ATTACHMENT_BYTES

MIME_BY_EXTENSION = {
    'pdf': {'application/pdf'},
    'jpg': {'image/jpeg'},
    'jpeg': {'image/jpeg'},
    'png': {'image/png'},
    'tiff': {'image/tiff'},
    'tif': {'image/tiff'},
    'docx': {'application/zip', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},
}

_SAFE_NAME_RE = re.compile(r'^[A-Za-z0-9._\- ]+$')


class UploadRejected(Exception):
    pass


def sanitize_filename(original_name):
    """Strips any directory component; the client never controls a path."""
    name = os.path.basename((original_name or '').strip().replace('\\', '/'))
    if not name or name in ('.', '..') or not _SAFE_NAME_RE.fullmatch(name):
        raise UploadRejected('Nome de arquivo inválido.')
    return name


def _extension_of(name):
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


#: Mais que isto não é laudo, é outra coisa — e cada página é trabalho para
#: a prévia e para quem vai ler.
MAX_PAGINAS_PDF = 500


def _validate_pdf_structure(content):
    if not content.startswith(b'%PDF-'):
        raise UploadRejected('Este arquivo não é um PDF válido.')
    # Só o começo do arquivo era conferido; agora ele precisa abrir como PDF
    # e ter páginas (auditoria externa de 2026-11-20). `strict=False` para
    # aceitar o PDF levemente fora da norma que todo leitor abre — o que se
    # recusa é o que não abre, o protegido por senha e o desmedido.
    import io

    from pypdf import PdfReader

    try:
        leitor = PdfReader(io.BytesIO(content), strict=False)
        if leitor.is_encrypted and not leitor.decrypt(''):
            raise UploadRejected('Este PDF está protegido por senha. Envie uma cópia sem senha.')
        paginas = len(leitor.pages)
    except UploadRejected:
        raise
    except Exception as exc:                                # noqa: BLE001
        raise UploadRejected('Este PDF está danificado e não pôde ser aberto.') from exc
    if paginas == 0:
        raise UploadRejected('Este PDF não tem páginas.')
    if paginas > MAX_PAGINAS_PDF:
        raise UploadRejected(f'Este PDF tem mais de {MAX_PAGINAS_PDF} páginas.')


def _validate_docx_structure(content):
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if '[Content_Types].xml' not in names or not any(n.startswith('word/') for n in names):
                raise UploadRejected('Este arquivo não é um documento Word válido.')
    except zipfile.BadZipFile as exc:
        raise UploadRejected('Este arquivo não é um documento Word válido.') from exc


def validate_upload(content, original_name):
    """Validates size, extension, real MIME (sniffed, not trusted from the
    client), and minimal internal structure — before anything touches disk
    or the antimalware engine.
    """
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise UploadRejected(
            f'Arquivo grande demais: o limite é '
            f'{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.'
        )
    name = sanitize_filename(original_name)
    extension = _extension_of(name)
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadRejected(
            f'Arquivos .{extension} não são aceitos aqui.'
        )
    sniffed_mime = magic.from_buffer(content, mime=True)
    if sniffed_mime not in MIME_BY_EXTENSION.get(extension, set()):
        raise UploadRejected(
            f'O conteúdo do arquivo não corresponde à extensão .{extension}. '
            f'Confira se ele não foi renomeado.'
        )
    if extension == 'pdf':
        _validate_pdf_structure(content)
    elif extension == 'docx':
        _validate_docx_structure(content)
    return name, sniffed_mime
