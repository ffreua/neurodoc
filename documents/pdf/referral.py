from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, build_pdf, paragrafo_de_texto, texto_seguro

TITLE = 'Encaminhamento'


def render(document):
    content = document.content_snapshot
    body = [
        Paragraph('Especialidade de destino:', LABEL_STYLE),
        Paragraph(texto_seguro(content['referral_specialty']), BODY_STYLE),
        Spacer(1, 0.4 * cm),
        Paragraph('Motivo do encaminhamento:', LABEL_STYLE),
        paragrafo_de_texto(content['reason'], BODY_STYLE),
    ]
    return build_pdf(document, TITLE, body)
