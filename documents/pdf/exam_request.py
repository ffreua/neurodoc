"""Pedido de exames de uma categoria, nascido de modelo (`modelos/emissao.py`).

Um pedido é **uma categoria**: o laboratório, o serviço de imagem e o de
neurofisiologia recebem papéis diferentes, e o convênio autoriza cada um
por guia própria. O título diz qual é ("Pedido de exames — Imagem").

Timbre, paciente, rodapé de assinatura e paginação vêm de `build_pdf`,
como em todo documento: só o corpo é deste módulo.

O convênio do paciente sai no corpo, e não no bloco de identificação comum:
é dado de guia, que receita e relatório não levam.
"""

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from .common import BODY_STYLE, LABEL_STYLE, build_pdf, paragrafo_de_texto, texto_seguro

TITLE = 'Pedido de exames'

LARGURA_UTIL = 17.8 * cm


def titulo(document):
    rotulo = (document.content_snapshot or {}).get('categoria_rotulo') or ''
    return f'{TITLE} — {rotulo}' if rotulo else TITLE


def convenio(patient):
    """`Convênio · plano · carteirinha`, ou vazio para particular."""
    cobertura = getattr(patient, 'active_coverage', None)
    if cobertura is None:
        return ''
    plano = cobertura.plan
    partes = [plano.insurer.name, plano.name]
    if cobertura.member_number:
        partes.append(f'carteirinha {cobertura.member_number}')
    return ' · '.join(p for p in partes if p)


def bloco_rotulado(rotulo, texto):
    if not (texto or '').strip():
        return []
    return [Paragraph(texto_seguro(rotulo), LABEL_STYLE), paragrafo_de_texto(texto, BODY_STYLE),
            Spacer(1, 0.3 * cm)]


def linha_de_cabecalho(texto):
    return Paragraph(f'<b>{texto_seguro(texto)}</b>', BODY_STYLE)


def tabela(cabecalho, linhas, larguras):
    """Tabela simples com cabeçalho cinza. Todo valor passa por `texto_seguro`."""
    dados = [[linha_de_cabecalho(c) for c in cabecalho]]
    for linha in linhas:
        dados.append([Paragraph(texto_seguro(c), BODY_STYLE) for c in linha])
    t = Table(dados, colWidths=larguras, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef0f4')),
        ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#c8ccd4')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    return t


def cabecalho_comum(document, conteudo):
    corpo = []
    texto_convenio = convenio(document.patient)
    if texto_convenio:
        corpo += [Paragraph(f'<b>Convênio:</b> {texto_seguro(texto_convenio)}', BODY_STYLE)]
    cid = (conteudo.get('cid') or '').strip()
    if cid:
        corpo += [Paragraph(f'<b>CID-10:</b> {texto_seguro(cid)}', BODY_STYLE)]
    if corpo:
        corpo.append(Spacer(1, 0.3 * cm))
    return corpo


def render(document):
    conteudo = document.content_snapshot or {}
    itens = conteudo.get('itens') or []
    com_codigo = any(i.get('codigo') for i in itens)

    corpo = cabecalho_comum(document, conteudo)
    corpo.append(Paragraph('Exames solicitados:', LABEL_STYLE))
    if com_codigo:
        corpo.append(tabela(
            ['Nº', 'Exame', 'Código TUSS'],
            [[str(n), i.get('descricao', ''), i.get('codigo', '')] for n, i in enumerate(itens, 1)],
            [1 * cm, LARGURA_UTIL - 4 * cm, 3 * cm],
        ))
    else:
        corpo.append(tabela(
            ['Nº', 'Exame'],
            [[str(n), i.get('descricao', '')] for n, i in enumerate(itens, 1)],
            [1 * cm, LARGURA_UTIL - 1 * cm],
        ))
    corpo.append(Spacer(1, 0.4 * cm))
    corpo += bloco_rotulado('Indicação clínica:', conteudo.get('indicacao'))
    corpo += bloco_rotulado('Observações:', conteudo.get('observacoes'))
    return build_pdf(document, titulo(document), corpo)
