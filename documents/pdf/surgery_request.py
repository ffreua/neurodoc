"""Solicitação de cirurgia, nascida de modelo (`modelos/emissao.py`).

O que a guia de internação pede, na ordem em que o auditor do convênio lê:
convênio e CID, a indicação, os procedimentos com o código TUSS, os
materiais (OPME) e as condições da internação.
"""

from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from modelos.estrutura import ANESTESIA, CARATER, LATERALIDADE, REGIME

from .common import BODY_STYLE, LABEL_STYLE, build_pdf, texto_seguro
from .exam_request import LARGURA_UTIL, bloco_rotulado, cabecalho_comum, tabela

TITLE = 'Solicitação de cirurgia'


def _rotulo(opcoes, valor):
    return dict(opcoes).get(valor or '', '')


def render(document):
    conteudo = document.content_snapshot or {}
    corpo = cabecalho_comum(document, conteudo)
    corpo += bloco_rotulado('Indicação clínica:', conteudo.get('indicacao'))

    procedimentos = conteudo.get('procedimentos') or []
    corpo.append(Paragraph('Procedimentos:', LABEL_STYLE))
    corpo.append(tabela(
        ['Código TUSS', 'Procedimento', 'Qtd.'],
        [[p.get('codigo') or '—', p.get('descricao', ''), str(p.get('quantidade') or 1)]
         for p in procedimentos],
        [3 * cm, LARGURA_UTIL - 4.5 * cm, 1.5 * cm],
    ))
    corpo.append(Spacer(1, 0.4 * cm))

    materiais = conteudo.get('materiais') or []
    if materiais:
        corpo.append(Paragraph('Materiais e OPME:', LABEL_STYLE))
        corpo.append(tabela(
            ['Qtd.', 'Material'],
            [[str(m.get('quantidade') or 1), m.get('descricao', '')] for m in materiais],
            [1.5 * cm, LARGURA_UTIL - 1.5 * cm],
        ))
        corpo.append(Spacer(1, 0.4 * cm))

    condicoes = [
        ('Caráter', _rotulo(CARATER, conteudo.get('carater'))),
        ('Regime', _rotulo(REGIME, conteudo.get('regime'))),
        ('Dias de internação previstos', conteudo.get('dias_internacao') or ''),
        ('Anestesia', _rotulo(ANESTESIA, conteudo.get('anestesia'))),
        ('Lateralidade', _rotulo(LATERALIDADE, conteudo.get('lateralidade'))
         if conteudo.get('lateralidade') else ''),
        ('UTI no pós-operatório', 'Sim' if conteudo.get('uti') else 'Não'),
        ('Reserva de hemoderivados', 'Sim' if conteudo.get('reserva_sangue') else 'Não'),
        ('Local', conteudo.get('local') or ''),
    ]
    corpo.append(Paragraph('Condições:', LABEL_STYLE))
    for rotulo, valor in condicoes:
        if valor:
            corpo.append(Paragraph(f'<b>{texto_seguro(rotulo)}:</b> {texto_seguro(valor)}', BODY_STYLE))
    corpo.append(Spacer(1, 0.4 * cm))
    corpo += bloco_rotulado('Observações:', conteudo.get('observacoes'))
    return build_pdf(document, TITLE, corpo)
