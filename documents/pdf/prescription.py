from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from .common import BODY_STYLE, LABEL_STYLE, SMALL_STYLE, build_pdf, paragrafo_de_texto

TITLE = 'Receita médica'
SPECIAL_TITLE = 'Receituário de Controle Especial'

#: Formatos de receita.
#:
#: `simple` é a receita comum, uma via. `special_control` é o Receituário de
#: Controle Especial da Portaria SVS/MS 344/98 — o que a prática chama de
#: "receita carbonada", porque em papel se usava papel-carbono para tirar as
#: duas vias de uma vez. Impresso, o carbono vira duas folhas: a farmácia
#: retém uma e o paciente leva a outra.
SIMPLE = 'simple'
SPECIAL_CONTROL = 'special_control'

FORMAT_CHOICES = (
    (SIMPLE, 'Receita simples (uma via)'),
    (SPECIAL_CONTROL, 'Controle especial (duas vias — farmácia e paciente)'),
)

#: Os rótulos exigidos em cada via. O texto não é decoração: é o que diz ao
#: balconista qual folha fica retida e ao paciente qual é a dele.
SPECIAL_COPIES = (
    '1ª VIA — RETENÇÃO DA FARMÁCIA',
    '2ª VIA — ORIENTAÇÃO AO PACIENTE',
)


#: As receitas eletrônicas com numeração do SNCR (Anvisa). Moram em
#: `sncr/receita.py` e são desenhadas por `sncr/pdf_oficial.py`, no modelo
#: da Anvisa e **sem** o timbre da clínica — por isso o `render` abaixo as
#: desvia antes de chegar a `build_pdf` (decisão D6, `docs/sncr/`).
SNCR_RCE = 'sncr_rce'
SNCR_RET = 'sncr_ret'
ELECTRONIC_FORMATS = (SNCR_RCE, SNCR_RET)


def prescription_format(document):
    value = (document.content_snapshot or {}).get('prescription_format') or SIMPLE
    return value if value in dict(FORMAT_CHOICES) or value in ELECTRONIC_FORMATS else SIMPLE


def render(document):
    content = document.content_snapshot
    kind = prescription_format(document)
    if kind in ELECTRONIC_FORMATS:
        from sncr.pdf_oficial import render as render_sncr

        return render_sncr(document)

    def body():
        """Reconstruído a cada via.

        Um `Flowable` do reportlab guarda o estado de quando foi desenhado;
        reaproveitar a mesma instância nas duas vias faz a segunda sair em
        branco. Por isso é função, e não lista.
        """
        parts = [
            Paragraph('Prescrição:', LABEL_STYLE),
            Spacer(1, 0.2 * cm),
            paragrafo_de_texto(content['prescription_text'], BODY_STYLE),
        ]
        if content.get('special_instructions'):
            parts += [
                Spacer(1, 0.4 * cm),
                Paragraph('Instruções especiais:', LABEL_STYLE),
                paragrafo_de_texto(content['special_instructions'], BODY_STYLE),
            ]
        if kind == SPECIAL_CONTROL:
            parts += [
                Spacer(1, 0.6 * cm),
                Paragraph(
                    'Receituário de Controle Especial — Portaria SVS/MS nº 344/1998. '
                    'Válido por 30 dias a partir da data de emissão em todo o território '
                    'nacional. A 1ª via fica retida na farmácia.',
                    SMALL_STYLE,
                ),
            ]
        return parts

    if kind == SPECIAL_CONTROL:
        return build_pdf(
            document, SPECIAL_TITLE, body,
            copies=SPECIAL_COPIES,
            # Endereço do paciente é obrigatório nesta modalidade.
            include_address=True,
            # Quadro de identificação do comprador e do fornecedor, do
            # Anexo XVII da Portaria SVS/MS 344/98. Sai em branco, para o
            # balconista preencher no ato da dispensação — ver
            # `_control_identification_block`.
            control_identification=True,
        )
    return build_pdf(document, TITLE, body)
