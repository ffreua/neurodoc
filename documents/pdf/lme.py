"""O PDF da LME: o modelo do Ministério da Saúde, preenchido.

A página é a do modelo travado em `documents/lme.py` (SHA-256), **sem os
campos interativos**: o arquivo do Ministério é um formulário do Acrobat,
com botões no topo ("Salvar como", "Limpar", "Buscar CNES") e campos que
qualquer leitor de PDF deixaria editar depois de impresso o número. Tirados
os campos, fica o desenho do formulário — moldura, rótulos, caixas de
marcar — e os valores entram numa camada por cima, cada um no retângulo
que o próprio modelo define para ele. O cabeçalho e o rodapé da clínica
(`common.build_pdf`) não entram: a farmácia recebe o formulário oficial.

O que se acrescenta fora da moldura do formulário, e só ali:

- no alto, onde ficavam os botões do Acrobat, uma linha discreta com o
  número do documento no NeuroDoc e a data — é o que liga o papel ao
  prontuário quando o paciente volta com ele;
- no pé, a linha "Para suporte..." do Ministério, que no modelo era um
  campo e some com os campos — redesenhada igual;
- no rascunho, a tarja "RASCUNHO — SEM VALIDADE", como no SNCR.

Os campos 17 e 23 (assinaturas) ficam em branco: a LME é sempre impressa,
assinada à mão e carimbada.
"""

import io

from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from reportlab.lib.colors import Color, black
from reportlab.pdfgen import canvas as pdfcanvas

from .. import lme

CINZA = Color(0.42, 0.42, 0.42)
AZUL_DO_MODELO = Color(0.0, 0.2, 0.8)
SUPORTE = 'Para suporte, entre em contato pelo: ceaf.daf@saude.gov.br'


def _data(document):
    """A data da solicitação (campo 16): a da emissão, no dia de Brasília.

    O rascunho mostra a de hoje, que é a que sairá se for emitido hoje.
    """
    quando = document.issued_at or timezone.now()
    return timezone.localtime(quando).strftime('%d/%m/%Y')


def _valores(document):
    """O conteúdo com as formatações do papel."""
    conteudo = dict(document.content_snapshot or {})
    conteudo['data'] = _data(document)
    conteudo['medico_cns'] = lme.formatar_cns(conteudo.get('medico_cns'))
    conteudo['preenchido_outro_cpf'] = lme.formatar_cpf(conteudo.get('preenchido_outro_cpf'))
    conteudo['telefone1'] = lme.formatar_telefone(conteudo.get('telefone1'))
    conteudo['telefone2'] = lme.formatar_telefone(conteudo.get('telefone2'))
    tipo = conteudo.get('documento_tipo')
    if tipo == 'cpf':
        conteudo['documento_numero'] = lme.formatar_cpf(conteudo.get('documento_numero'))
    elif tipo == 'cns':
        conteudo['documento_numero'] = lme.formatar_cns(conteudo.get('documento_numero'))
    if conteudo.get('tratamento_previo') != 'sim':
        conteudo['tratamento_relato'] = ''
    if conteudo.get('incapaz') != 'sim':
        conteudo['responsavel'] = ''
    if conteudo.get('preenchido_por') != 'outro':
        conteudo['preenchido_outro_nome'] = ''
        conteudo['preenchido_outro_cpf'] = ''
    if conteudo.get('raca') != 'indigena':
        conteudo['etnia'] = ''
    return conteudo


def _texto_no_campo(c, valor, caixa, max_linhas, centralizar=False):
    x0, y0, x1, y1 = caixa
    ajuste = lme.ajustar(valor, x1 - x0, y1 - y0, max_linhas)
    if ajuste is None:
        # `lme.validar` recusa antes de chegar aqui; desenhar cortado seria
        # entregar à farmácia um laudo com texto pela metade.
        raise lme.LmeInvalida('Um valor não cabe no campo da LME. Revise o rascunho.')
    tamanho, linhas = ajuste
    if not linhas:
        return
    c.setFillColor(black)
    c.setFont(lme.FONTE, tamanho)
    entrelinha = tamanho * 1.15
    altura_texto = entrelinha * (len(linhas) - 1) + tamanho * 0.72
    if max_linhas > 2:
        # Várias linhas (anamnese): do alto da caixa para baixo.
        base = y1 - 2 - tamanho * 0.8
    else:
        base = y0 + (y1 - y0 - altura_texto) / 2 + entrelinha * (len(linhas) - 1)
    for linha in linhas:
        if centralizar:
            c.drawCentredString((x0 + x1) / 2, base, linha)
        else:
            c.drawString(x0, base, linha)
        base -= entrelinha


def _marcar(c, caixa):
    x0, y0, x1, y1 = caixa
    lado = min(x1 - x0, y1 - y0)
    tamanho = lado + 1.5
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', tamanho)
    c.drawCentredString((x0 + x1) / 2, y0 + (y1 - y0 - tamanho * 0.72) / 2, 'X')


def _camada(document, largura, altura):
    rascunho = document.status not in ('issued', 'issued_on_paper')
    valores = _valores(document)
    saida = io.BytesIO()
    c = pdfcanvas.Canvas(saida, pagesize=(largura, altura))

    for chave, nome_pdf in lme.CAMPOS_DE_TEXTO.items():
        valor = valores.get(chave) or ''
        if not str(valor).strip():
            continue
        centralizar = chave in ('cnes', 'peso', 'altura', 'cid', 'medico_cns', 'data')
        _texto_no_campo(c, valor, lme.caixa_de(chave, nome_pdf), lme._max_linhas(chave), centralizar)

    for indice, item in enumerate((valores.get('medicamentos') or [])[:lme.MAX_MEDICAMENTOS]):
        _texto_no_campo(c, item.get('nome', ''), lme.caixa_de('medicamento', lme.CAMPOS_DE_MEDICAMENTO[indice]), 2)
        for mes, quantidade in enumerate((item.get('quantidades') or [])[:lme.MESES]):
            if str(quantidade or '').strip():
                _texto_no_campo(c, str(quantidade), lme.retangulo(lme.CAMPOS_DE_QUANTIDADE[indice][mes]), 1,
                                centralizar=True)

    for chave, (nome_pdf, estados) in lme.CAIXAS.items():
        estado = estados.get(valores.get(chave) or '')
        if estado:
            _marcar(c, lme.retangulo_da_caixa(nome_pdf, estado))

    # Fora da moldura: o número no alto e a linha de suporte do modelo no pé.
    c.setFillColor(CINZA)
    c.setFont(lme.FONTE, 7.5)
    if rascunho:
        identificacao = 'RASCUNHO — ainda sem número. Revise, emita e imprima para assinar e carimbar.'
    else:
        identificacao = (f'{document.document_number} · emitida em {valores["data"]} · '
                         'assinar à mão e carimbar (campo 17)')
    c.drawString(46, altura - 20, lme.imprimivel(identificacao))
    c.drawRightString(549, altura - 20, f'Modelo {lme.VERSAO_MODELO}')
    c.setFillColor(AZUL_DO_MODELO)
    c.setFont(lme.FONTE, 7.5)
    c.drawCentredString(321, 4, SUPORTE)

    if rascunho:
        c.saveState()
        c.setFillColor(Color(0.85, 0.1, 0.1, alpha=0.18))
        c.setFont('Helvetica-Bold', 46)
        c.translate(largura / 2, altura / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, 'RASCUNHO — SEM VALIDADE')
        c.restoreState()
    c.showPage()
    c.save()
    return saida.getvalue()


def render(document):
    pagina = PdfReader(io.BytesIO(lme.carregar_modelo())).pages[0]
    # Sem os campos e os botões do Acrobat: só o desenho do formulário.
    if '/Annots' in pagina:
        del pagina[NameObject('/Annots')]
    caixa = pagina.mediabox
    largura, altura = float(caixa.width), float(caixa.height)
    camada = PdfReader(io.BytesIO(_camada(document, largura, altura))).pages[0]
    pagina.merge_page(camada)
    # `merge_page` recria `/Annots` (vazio): tirado de novo, o PDF sai sem
    # nenhuma estrutura de formulário.
    if '/Annots' in pagina:
        del pagina[NameObject('/Annots')]
    escritor = PdfWriter()
    escritor.add_page(pagina)
    escritor.add_metadata({
        '/Title': 'LME — Laudo de Solicitação, Avaliação e Autorização de Medicamento(s)',
        '/Producer': 'NeuroDoc',
    })
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()
