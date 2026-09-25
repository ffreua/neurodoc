from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, build_pdf, paragrafo_de_texto

TITLE = 'Relatório médico'


def render(document):
    content = document.content_snapshot
    body = [
        Paragraph('Relatório:', LABEL_STYLE),
        Spacer(1, 0.2 * cm),
        paragrafo_de_texto(content['report_text'], BODY_STYLE),
    ]
    return build_pdf(document, TITLE, body)
