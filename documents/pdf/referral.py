from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, build_pdf

TITLE = 'Encaminhamento'


def render(document):
    content = document.content_snapshot
    body = [
        Paragraph('Especialidade de destino:', LABEL_STYLE),
        Paragraph(content['referral_specialty'], BODY_STYLE),
        Spacer(1, 0.4 * cm),
        Paragraph('Motivo do encaminhamento:', LABEL_STYLE),
        Paragraph(content['reason'].replace('\n', '<br/>'), BODY_STYLE),
    ]
    return build_pdf(document, TITLE, body)
