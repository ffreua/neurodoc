from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, build_pdf

TITLE = 'Receita médica'


def render(document):
    content = document.content_snapshot
    body = [
        Paragraph('Prescrição:', LABEL_STYLE),
        Spacer(1, 0.2 * cm),
        Paragraph(content['prescription_text'].replace('\n', '<br/>'), BODY_STYLE),
    ]
    if content.get('special_instructions'):
        body += [
            Spacer(1, 0.4 * cm),
            Paragraph('Instruções especiais:', LABEL_STYLE),
            Paragraph(content['special_instructions'].replace('\n', '<br/>'), BODY_STYLE),
        ]
    return build_pdf(document, TITLE, body)
