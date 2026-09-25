from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, build_pdf, paragrafo_de_texto

TITLE = 'Pedido de exame/procedimento'


def render(document):
    content = document.content_snapshot
    body = [
        Paragraph('Procedimento/exame solicitado:', LABEL_STYLE),
        paragrafo_de_texto(content['requested_procedure'], BODY_STYLE),
        Spacer(1, 0.4 * cm),
        Paragraph('Justificativa clínica:', LABEL_STYLE),
        paragrafo_de_texto(content['justification'], BODY_STYLE),
    ]
    return build_pdf(document, TITLE, body)
