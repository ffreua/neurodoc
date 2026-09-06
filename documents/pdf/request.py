from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, build_pdf

TITLE = 'Pedido de exame/procedimento'


def render(document):
    content = document.content_snapshot
    body = [
        Paragraph('Procedimento/exame solicitado:', LABEL_STYLE),
        Paragraph(content['requested_procedure'].replace('\n', '<br/>'), BODY_STYLE),
        Spacer(1, 0.4 * cm),
        Paragraph('Justificativa clínica:', LABEL_STYLE),
        Paragraph(content['justification'].replace('\n', '<br/>'), BODY_STYLE),
    ]
    return build_pdf(document, TITLE, body)
