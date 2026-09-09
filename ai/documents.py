"""Texto de um anexo, para a IA ler.

Nenhum arquivo é enviado a provedor externo. O que sai daqui é **texto**, e
ele passa pela desidentificação e pela política de privacidade antes de
qualquer chamada — mandar o PDF original seria mandar o cabeçalho do
laboratório com nome, data de nascimento e número de convênio do paciente
junto.

Duas fontes, nesta ordem:

1. **camada de texto do PDF** (pypdf). Laudo emitido por sistema quase
   sempre tem; é fiel e não custa nada.
2. **OCR local** já gravado em `AttachmentOcrPage` (tesseract, pt-BR), para
   laudo digitalizado. Se o OCR ainda não rodou, esta função diz isso em vez
   de mandar meia página para o modelo.
"""

from documents.models import AttachmentOcrPage, AttachmentScanStatus
from documents.storage import local_path

#: Abaixo disto a camada de texto não é confiável: é o PDF que só tem a
#: imagem digitalizada e alguns caracteres de metadado.
MIN_TEXT_LAYER_CHARS = 200

#: O que vai ao modelo. Laudo laboratorial de rotina cabe folgado; laudo
#: gigante entra truncado, e o truncamento é declarado no artefato.
MAX_DOCUMENT_CHARS = 60000


class DocumentTextUnavailable(Exception):
    pass


def _pdf_text_layer(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ''
    try:
        reader = PdfReader(path)
        return '\n'.join((page.extract_text() or '') for page in reader.pages)
    except Exception:
        # PDF corrompido ou protegido: o OCR ainda pode dar conta.
        return ''


def _ocr_text(attachment):
    pages = AttachmentOcrPage.objects.filter(
        tenant_id=attachment.tenant_id, attachment=attachment,
    ).order_by('page_number')
    return '\n'.join(page.text for page in pages if page.text)


def attachment_text(attachment):
    """Texto do anexo e de onde ele veio.

    Devolve `(texto, origem, truncado)`. `origem` é `'text_layer'` ou
    `'ocr'`, e vai para as limitações do artefato: o médico que revisa o
    rascunho precisa saber se aquilo saiu de OCR de um fax ou da camada de
    texto do laudo original.
    """
    if attachment is None:
        raise DocumentTextUnavailable('Nenhum laudo anexado a este exame.')
    if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
        raise DocumentTextUnavailable(
            'O laudo ainda está em verificação de malware. Tente novamente em instantes.'
        )

    source = 'text_layer'
    text = ''
    if attachment.original_name.lower().endswith('.pdf'):
        # `caminho`, e não `source`: `source` logo abaixo é a origem do
        # texto ('text_layer' ou 'ocr'), e reaproveitar o nome faria o
        # caminho do arquivo virar essa origem.
        with local_path(attachment) as caminho:
            text = _pdf_text_layer(caminho)

    if len(text.strip()) < MIN_TEXT_LAYER_CHARS:
        ocr = _ocr_text(attachment)
        if len(ocr.strip()) >= MIN_TEXT_LAYER_CHARS:
            text, source = ocr, 'ocr'
        elif not text.strip():
            raise DocumentTextUnavailable(
                'Não foi possível extrair texto deste laudo. Se é um documento '
                'digitalizado, rode o reconhecimento de texto (OCR) antes de pedir a '
                'leitura pela IA.'
            )

    truncated = len(text) > MAX_DOCUMENT_CHARS
    return text[:MAX_DOCUMENT_CHARS], source, truncated
