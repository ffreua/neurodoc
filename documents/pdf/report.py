from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, build_pdf

TITLE = 'Relatório médico'


def render(document):
    content = document.content_snapshot
    body = [
        Paragraph('Relatório:', LABEL_STYLE),
        Spacer(1, 0.2 * cm),
        Paragraph(content['report_text'].replace('\n', '<br/>'), BODY_STYLE),
    ]
    return build_pdf(document, TITLE, body)
