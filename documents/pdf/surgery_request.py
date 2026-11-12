"""Solicitação de cirurgia, nascida de modelo (`modelos/emissao.py`).

O que a guia de internação pede, na ordem em que o auditor do convênio lê:
convênio e CID, a indicação, os procedimentos com o código TUSS, os
materiais (OPME) com os fornecedores, a monitorização, os materiais do
hospital, os hemocomponentes e as condições da internação.

Os campos do guia (fornecedores, monitorização, materiais hospitalares,
hemocomponentes, equipe de anestesia, tempo de sala e dias de UTI) entraram
em 2026-11-12. O documento emitido antes deles não os tem, e cada bloco só
aparece quando há o que dizer — o papel antigo, refeito, sai igual.
"""

from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer

from modelos.emissao import hemocomponentes
from modelos.estrutura import ANESTESIA, CARATER, EQUIPE_ANESTESIA, LATERALIDADE, REGIME

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

    fornecedores = conteudo.get('fornecedores') or []
    if fornecedores:
        corpo += bloco_rotulado('Fornecedores de OPME:', ', '.join(fornecedores))

    if conteudo.get('monitorizacao'):
        corpo.append(Paragraph('<b>Monitorização neurofisiológica intraoperatória:</b> Sim',
                               BODY_STYLE))
        corpo.append(Spacer(1, 0.3 * cm))

    hospitalares = conteudo.get('materiais_hospitalares') or []
    if hospitalares:
        corpo += bloco_rotulado('Materiais hospitalares:', '\n'.join(f'- {m}' for m in hospitalares))

    hemo = hemocomponentes(conteudo)
    if hemo:
        corpo += bloco_rotulado('Hemocomponentes:', ', '.join(hemo))

    uti = 'Não'
    if conteudo.get('uti'):
        uti = f"Sim, {conteudo['dias_uti']} dia(s)" if conteudo.get('dias_uti') else 'Sim'
    condicoes = [
        ('Caráter', _rotulo(CARATER, conteudo.get('carater'))),
        ('Regime', _rotulo(REGIME, conteudo.get('regime'))),
        ('Tempo total de internação (dias)', conteudo.get('dias_internacao') or ''),
        ('Tempo total de sala (minutos)', conteudo.get('tempo_sala') or ''),
        ('Anestesia', _rotulo(ANESTESIA, conteudo.get('anestesia'))),
        ('Equipe de anestesia', _rotulo(EQUIPE_ANESTESIA, conteudo.get('equipe_anestesia'))
         if conteudo.get('equipe_anestesia') else ''),
        ('Lateralidade', _rotulo(LATERALIDADE, conteudo.get('lateralidade'))
         if conteudo.get('lateralidade') else ''),
        ('UTI no pós-operatório', uti),
        # O documento anterior aos hemocomponentes dizia só sim ou não.
        ('Reserva de hemoderivados', '' if hemo else ('Sim' if conteudo.get('reserva_sangue') else 'Não')),
        ('Local', conteudo.get('local') or ''),
    ]
    corpo.append(Paragraph('Condições:', LABEL_STYLE))
    for rotulo, valor in condicoes:
        if valor:
            corpo.append(Paragraph(f'<b>{texto_seguro(rotulo)}:</b> {texto_seguro(valor)}', BODY_STYLE))
    corpo.append(Spacer(1, 0.4 * cm))
    corpo += bloco_rotulado('Observações:', conteudo.get('observacoes'))
    return build_pdf(document, TITLE, corpo)
