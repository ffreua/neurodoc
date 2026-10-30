"""A guia impressa, no modelo em papel da ANS (A4: Consulta p.469, SP/SADT p.520).

Os campos levam a **numeração oficial** do modelo (1 - Registro ANS, 2 - Nº
Guia no Prestador...), na ordem dele, em A4 paisagem. Três regras:

- **Guia fechada imprime do snapshot**: o que foi faturado, e não o cadastro
  de hoje. Reimprimir depois de mudar a carteira do paciente devolve a mesma
  folha.
- **Guia em preenchimento sai com tarja** "EM PREENCHIMENTO — NÃO ENVIAR":
  serve para conferir, não para cobrar.
- **SP/SADT com mais procedimentos que as cinco linhas do modelo** continua
  em outra folha, com o cabeçalho repetido, "Folha N de M" e os totais só
  na última — como a continuação que o modelo prevê.

Nada clínico além do que o modelo pede: a indicação clínica (campo 23 da
SP/SADT), que o médico escreveu para a operadora.
"""

from decimal import Decimal
from io import BytesIO

from django.utils import timezone

from . import terminologia
from .models import EstadoGuia, IdentificacaoNaOperadora, TipoGuia

LINHAS_POR_FOLHA = 5


def _brl(valor):
    if valor in (None, ''):
        return ''
    texto = f'{Decimal(valor):,.2f}'
    return texto.replace(',', 'X').replace('.', ',').replace('X', '.')


def _data(valor):
    if not valor:
        return ''
    if isinstance(valor, str):
        a, m, d = valor[:10].split('-')
        return f'{d}/{m}/{a}'
    return valor.strftime('%d/%m/%Y')


def _hora(valor):
    if not valor:
        return ''
    return valor[:5] if isinstance(valor, str) else valor.strftime('%H:%M')


def dados(guia):
    """Tudo o que a folha mostra, de uma fonte só: o snapshot se fechada."""
    fechada = guia.estado != EstadoGuia.RASCUNHO and guia.snapshot
    if fechada:
        s = guia.snapshot
        operadora, prestador = s['operadora'], s['prestador']
        cred = s['credenciamento']
        benef = s['beneficiario']
        executante, solicitante = s.get('executante'), s.get('solicitante')
        itens = s['itens']
        total = s['total']
    else:
        c = guia.credenciamento
        operadora = {'nome': c.operadora.name, 'registro_ans': c.operadora.ans_registration} if c else {}
        prestador = ({'nome': c.prestador.nome, 'documento': c.prestador.documento,
                      'cnes': c.prestador.cnes or '9999999'} if c else {})
        cred = {'identificacao': c.identificacao, 'codigo': c.codigo_na_operadora} if c else {}
        benef = {'nome': guia.paciente.full_name, 'carteira': guia.carteira,
                 'validade_carteira': guia.validade_carteira.isoformat() if guia.validade_carteira else None,
                 'atendimento_rn': guia.atendimento_rn}

        def prof(p):
            return ({'nome': p.nome, 'conselho': p.conselho, 'numero': p.numero_conselho,
                     'uf': p.uf, 'cbo': p.cbo} if p else None)

        executante, solicitante = prof(guia.executante), prof(guia.solicitante)
        itens = [
            {'sequencial': i.sequencial, 'data': i.data_execucao.isoformat(),
             'hora_inicial': i.hora_inicial.isoformat() if i.hora_inicial else None,
             'hora_final': i.hora_final.isoformat() if i.hora_final else None,
             'tabela': i.tabela, 'codigo': i.codigo, 'descricao': i.descricao,
             'quantidade': i.quantidade, 'via_acesso': i.via_acesso, 'tecnica': i.tecnica,
             'fator': str(i.fator), 'valor_unitario': str(i.valor_unitario), 'valor_total': str(i.valor_total)}
            for i in guia.itens.order_by('sequencial')
        ]
        total = str(sum((Decimal(i['valor_total']) for i in itens), Decimal('0.00')))
    codigo_prestador = (
        cred.get('codigo') if cred.get('identificacao') == IdentificacaoNaOperadora.CODIGO
        else prestador.get('documento', '')
    )
    return {
        'rascunho': not fechada, 'cancelada': guia.estado == EstadoGuia.CANCELADA,
        'substituida': guia.estado == EstadoGuia.SUBSTITUIDA,
        'operadora': operadora, 'prestador': prestador, 'codigo_prestador': codigo_prestador or '',
        'beneficiario': benef, 'executante': executante, 'solicitante': solicitante,
        'itens': itens, 'total': total,
    }


class _Folha:
    """Caixas com rótulo pequeno em cima e valor embaixo, como no modelo."""

    def __init__(self, canvas, largura, altura):
        self.c, self.L, self.A = canvas, largura, altura
        self.m = 22  # margem

    def caixa(self, x, y, w, h, rotulo, valor='', tamanho=8.5):
        c = self.c
        c.setLineWidth(0.6)
        c.rect(x, y, w, h)
        c.setFont('Helvetica', 5.8)
        c.drawString(x + 2, y + h - 7, rotulo)
        if valor not in (None, ''):
            c.setFont('Helvetica', tamanho)
            texto = str(valor)
            while c.stringWidth(texto, 'Helvetica', tamanho) > w - 4 and len(texto) > 1:
                texto = texto[:-1]
            c.drawString(x + 2, y + 3, texto)

    def faixa(self, y, texto):
        c = self.c
        c.setFillGray(0.82)
        c.rect(self.m, y, self.L - 2 * self.m, 9, stroke=0, fill=1)
        c.setFillGray(0)
        c.setFont('Helvetica-Bold', 6.5)
        c.drawString(self.m + 2, y + 2.3, texto)

    def texto_longo(self, x, y, w, h, rotulo, valor):
        from reportlab.lib.utils import simpleSplit

        self.caixa(x, y, w, h, rotulo)
        linhas = simpleSplit(valor or '', 'Helvetica', 7.5, w - 6)
        self.c.setFont('Helvetica', 7.5)
        for n, linha in enumerate(linhas[: int((h - 10) // 8.5)]):
            self.c.drawString(x + 3, y + h - 16 - n * 8.5, linha)

    def tarjas(self, d, folha, folhas, guia, titulo):
        c = self.c
        c.setFont('Helvetica-Bold', 12)
        c.drawCentredString(self.L / 2, self.A - 34, titulo)
        c.setFont('Helvetica', 7)
        c.drawString(self.m, self.A - 34, d['prestador'].get('nome', '')[:60])
        c.setFont('Helvetica', 6)
        c.drawRightString(self.L - self.m, self.A - 24, '2 - Nº Guia no Prestador')
        c.setFont('Helvetica-Bold', 13)
        c.drawRightString(self.L - self.m, self.A - 38, guia.numero_prestador)
        c.setFont('Helvetica', 6.5)
        rodape = (f'NeuroDoc — guia {guia.get_tipo_display().lower()} nº {guia.numero_prestador} — '
                  f'versão do padrão TISS {guia.versao_efetiva} — impresso em '
                  f'{timezone.localtime():%d/%m/%Y %H:%M} — Folha {folha} de {folhas}')
        c.drawString(self.m, 12, rodape)
        if d['rascunho'] or d['cancelada'] or d['substituida']:
            # Translúcida: a tarja diz que a folha não é para enviar, mas não
            # pode cobrir os campos que a pessoa está conferindo.
            c.saveState()
            c.setFillColorRGB(0.85, 0.2, 0.2)
            c.setFillAlpha(0.18)
            c.setFont('Helvetica-Bold', 34)
            c.translate(self.L / 2, self.A / 2)
            c.rotate(18)
            aviso = ('EM PREENCHIMENTO — NÃO ENVIAR' if d['rascunho']
                     else 'GUIA CANCELADA' if d['cancelada'] else 'SUBSTITUÍDA POR REVISÃO')
            c.drawCentredString(0, 0, aviso)
            c.restoreState()


def _consulta(f, guia, d):
    m, L, A = f.m, f.L, f.A
    W = L - 2 * m
    b, e = d['beneficiario'], d['executante'] or {}
    item = d['itens'][0] if d['itens'] else {}
    f.tarjas(d, 1, 1, guia, 'GUIA DE CONSULTA')
    y = A - 78
    f.caixa(m, y, 110, 24, '1 - Registro ANS', d['operadora'].get('registro_ans'))
    f.caixa(m + 116, y, 300, 24, '3 - Número da Guia Atribuído pela Operadora', guia.numero_operadora)
    y -= 14
    f.faixa(y, 'Dados do Beneficiário')
    y -= 28
    f.caixa(m, y, 300, 24, '4 - Número da Carteira', b.get('carteira'))
    f.caixa(m + 306, y, 140, 24, '5 - Validade da Carteira', _data(b.get('validade_carteira')))
    f.caixa(m + 452, y, 120, 24, '6 - Atendimento a RN (Sim ou Não)', 'S' if b.get('atendimento_rn') else 'N')
    y -= 28
    f.caixa(m, y, 446, 24, '26 - Nome Social', '')
    y -= 28
    f.caixa(m, y, 446, 24, '7 - Nome', b.get('nome'))
    y -= 14
    f.faixa(y, 'Dados do Contratado')
    y -= 28
    f.caixa(m, y, 200, 24, '9 - Código na Operadora', d['codigo_prestador'])
    f.caixa(m + 206, y, W - 206 - 126, 24, '10 - Nome do Contratado', d['prestador'].get('nome'))
    f.caixa(L - m - 120, y, 120, 24, '11 - Código CNES', d['prestador'].get('cnes'))
    y -= 28
    f.caixa(m, y, 330, 24, '12 - Nome do Profissional Executante', e.get('nome'))
    f.caixa(m + 336, y, 70, 24, '13 - Conselho Profissional', e.get('conselho'))
    f.caixa(m + 412, y, 190, 24, '14 - Número no Conselho', e.get('numero'))
    f.caixa(m + 608, y, 40, 24, '15 - UF', e.get('uf'))
    f.caixa(m + 654, y, W - 654, 24, '16 - Código CBO', e.get('cbo'))
    y -= 14
    f.faixa(y, 'Dados do Atendimento / Procedimento Realizado')
    y -= 28
    f.caixa(m, y, 180, 24, '17 - Indicação de Acidente', terminologia.rotulo('36', guia.indicacao_acidente)
            and f'{guia.indicacao_acidente} - {terminologia.rotulo("36", guia.indicacao_acidente)}')
    f.caixa(m + 186, y, 150, 24, '27 - Indicador de Cobertura Especial', guia.cobertura_especial)
    f.caixa(m + 342, y, 120, 24, '28 - Regime de Atendimento', guia.regime_atendimento)
    f.caixa(m + 468, y, 120, 24, '29 - Saúde Ocupacional', guia.saude_ocupacional)
    y -= 28
    f.caixa(m, y, 120, 24, '18 - Data do Atendimento', _data(item.get('data')))
    f.caixa(m + 126, y, 120, 24, '19 - Tipo de Consulta', guia.tipo_consulta
            and f'{guia.tipo_consulta} - {terminologia.rotulo("52", guia.tipo_consulta)}')
    f.caixa(m + 252, y, 60, 24, '20 - Tabela', item.get('tabela'))
    f.caixa(m + 318, y, 200, 24, '21 - Código do Procedimento', item.get('codigo'))
    f.caixa(m + 524, y, 160, 24, '22 - Valor do Procedimento', _brl(item.get('valor_total')))
    y -= 70
    f.texto_longo(m, y, W, 66, '23 - Observação / Justificativa', guia.observacao)
    y -= 40
    f.caixa(m, y, W / 2 - 4, 34, '24 - Assinatura do Profissional Executante')
    f.caixa(m + W / 2 + 4, y, W / 2 - 4, 34, '25 - Assinatura do Beneficiário ou Responsável')


def _sadt_folha(f, guia, d, itens, folha, folhas):
    m, L, A = f.m, f.L, f.A
    W = L - 2 * m
    b, s, e = d['beneficiario'], d['solicitante'] or {}, d['executante'] or {}
    ultima = folha == folhas
    f.tarjas(d, folha, folhas, guia, 'GUIA DE SERVIÇO PROFISSIONAL / SERVIÇO AUXILIAR DE DIAGNÓSTICO E TERAPIA - SP/SADT')
    y = A - 74
    f.caixa(m, y, 90, 20, '1 - Registro ANS', d['operadora'].get('registro_ans'))
    f.caixa(m + 94, y, 220, 20, '3 - Número da Guia Principal', guia.guia_principal)
    y -= 23
    f.caixa(m, y, 110, 20, '4 - Data da Autorização', _data(guia.data_autorizacao))
    f.caixa(m + 114, y, 220, 20, '5 - Senha', guia.senha)
    f.caixa(m + 338, y, 110, 20, '6 - Data de Validade da Senha', _data(guia.validade_senha))
    f.caixa(m + 452, y, 220, 20, '7 - Número da Guia Atribuído pela Operadora', guia.numero_operadora)
    y -= 12
    f.faixa(y, 'Dados do Beneficiário')
    y -= 22
    f.caixa(m, y, 230, 20, '8 - Número da Carteira', b.get('carteira'))
    f.caixa(m + 234, y, 100, 20, '9 - Validade da Carteira', _data(b.get('validade_carteira')))
    f.caixa(m + 338, y, 190, 20, '89 - Nome Social', '')
    f.caixa(m + 532, y, 200, 20, '10 - Nome', b.get('nome'))
    f.caixa(m + 736, y, W - 736, 20, '12 - Atendimento a RN', 'S' if b.get('atendimento_rn') else 'N')
    y -= 12
    f.faixa(y, 'Dados do Solicitante')
    y -= 22
    proprio = guia.contratado_solicitante_tipo == 'proprio'
    f.caixa(m, y, 160, 20, '13 - Código na Operadora',
            d['codigo_prestador'] if proprio else guia.contratado_solicitante_codigo)
    f.caixa(m + 164, y, W - 164, 20, '14 - Nome do Contratado',
            d['prestador'].get('nome') if proprio else guia.contratado_solicitante_nome)
    y -= 23
    f.caixa(m, y, 250, 20, '15 - Nome do Profissional Solicitante', s.get('nome'))
    f.caixa(m + 254, y, 55, 20, '16 - Conselho', s.get('conselho'))
    f.caixa(m + 313, y, 120, 20, '17 - Número no Conselho', s.get('numero'))
    f.caixa(m + 437, y, 35, 20, '18 - UF', s.get('uf'))
    f.caixa(m + 476, y, 70, 20, '19 - Código CBO', s.get('cbo'))
    f.caixa(m + 550, y, W - 550, 20, '20 - Assinatura do Profissional Solicitante')
    y -= 12
    f.faixa(y, 'Dados da Solicitação / Procedimentos ou Itens Assistenciais Solicitados')
    y -= 22
    f.caixa(m, y, 70, 20, '21 - Caráter do Atendimento', guia.carater_atendimento)
    f.caixa(m + 74, y, 90, 20, '22 - Data da Solicitação', _data(guia.data_solicitacao))
    f.caixa(m + 168, y, W - 168 - 124, 20, '23 - Indicação Clínica', guia.indicacao_clinica, tamanho=7)
    f.caixa(L - m - 120, y, 120, 20, '90 - Indicador de Cobertura Especial', guia.cobertura_especial)
    # Procedimentos solicitados = os realizados desta folha (24 a 28).
    y -= 6 + 11 * LINHAS_POR_FOLHA
    f.caixa(m, y, W, 11 * LINHAS_POR_FOLHA + 4, '24-Tabela  25-Código do Procedimento  26-Descrição  27-Qtde. Solic.  28-Qtde. Aut.')
    f.c.setFont('Helvetica', 6.8)
    for n, i in enumerate(itens):
        yy = y + 11 * LINHAS_POR_FOLHA - 10 - n * 11
        f.c.drawString(m + 4, yy, f'{i["sequencial"]}- {i["tabela"]}')
        f.c.drawString(m + 50, yy, i['codigo'])
        f.c.drawString(m + 120, yy, i['descricao'][:95])
        f.c.drawRightString(L - m - 70, yy, str(i['quantidade']))
    y -= 12
    f.faixa(y, 'Dados do Contratado Executante')
    y -= 22
    f.caixa(m, y, 160, 20, '29 - Código na Operadora', d['codigo_prestador'])
    f.caixa(m + 164, y, W - 164 - 104, 20, '30 - Nome do Contratado', d['prestador'].get('nome'))
    f.caixa(L - m - 100, y, 100, 20, '31 - Código CNES', d['prestador'].get('cnes'))
    y -= 12
    f.faixa(y, 'Dados do Atendimento')
    y -= 22
    f.caixa(m, y, 100, 20, '32 - Tipo de Atendimento', guia.tipo_atendimento)
    f.caixa(m + 104, y, 130, 20, '33 - Indicação de Acidente', guia.indicacao_acidente)
    f.caixa(m + 238, y, 80, 20, '34 - Tipo de Consulta', guia.tipo_consulta)
    f.caixa(m + 322, y, 150, 20, '35 - Motivo de Encerramento', guia.motivo_encerramento)
    f.caixa(m + 476, y, 100, 20, '91 - Regime de Atendimento', guia.regime_atendimento)
    f.caixa(m + 580, y, 100, 20, '92 - Saúde Ocupacional', guia.saude_ocupacional)
    y -= 12
    f.faixa(y, 'Dados da Execução / Procedimentos e Exames Realizados')
    y -= 6 + 11 * LINHAS_POR_FOLHA
    f.caixa(m, y, W, 11 * LINHAS_POR_FOLHA + 4,
            '36-Data  37-Hora Inicial  38-Hora Final  39-Tabela  40-Código  41-Descrição  42-Qtde.  '
            '43-Via  44-Téc.  45-Fator  46-Valor Unitário (R$)  47-Valor Total (R$)')
    f.c.setFont('Helvetica', 6.8)
    for n, i in enumerate(itens):
        yy = y + 11 * LINHAS_POR_FOLHA - 10 - n * 11
        f.c.drawString(m + 4, yy, f'{i["sequencial"]}- {_data(i["data"])}')
        f.c.drawString(m + 70, yy, f'{_hora(i.get("hora_inicial"))} a {_hora(i.get("hora_final"))}')
        f.c.drawString(m + 130, yy, i['tabela'])
        f.c.drawString(m + 150, yy, i['codigo'])
        f.c.drawString(m + 200, yy, i['descricao'][:70])
        f.c.drawString(m + 520, yy, str(i['quantidade']))
        f.c.drawString(m + 545, yy, i.get('via_acesso') or '')
        f.c.drawString(m + 565, yy, i.get('tecnica') or '')
        f.c.drawString(m + 585, yy, _brl(i.get('fator')))
        f.c.drawRightString(m + 700, yy, _brl(i['valor_unitario']))
        f.c.drawRightString(L - m - 4, yy, _brl(i['valor_total']))
    y -= 12
    f.faixa(y, 'Identificação do(s) Profissional(is) Executante(s)')
    y -= 22
    f.caixa(m, y, 300, 20, '51 - Nome do Profissional', e.get('nome'))
    f.caixa(m + 304, y, 70, 20, '52 - Conselho Profissional', e.get('conselho'))
    f.caixa(m + 378, y, 140, 20, '53 - Número no Conselho', e.get('numero'))
    f.caixa(m + 522, y, 40, 20, '54 - UF', e.get('uf'))
    f.caixa(m + 566, y, 90, 20, '55 - Código CBO', e.get('cbo'))
    y -= 34
    f.texto_longo(m, y, W, 30, '58 - Observação / Justificativa', guia.observacao)
    y -= 23
    largura = W / 7
    rotulos = ['59 - Total de Procedimentos (R$)', '60 - Total de Taxas e Aluguéis (R$)',
               '61 - Total de Materiais (R$)', '62 - Total de OPME (R$)', '63 - Total de Medicamentos (R$)',
               '64 - Total de Gases Medicinais (R$)', '65 - Total Geral (R$)']
    valores = [_brl(d['total']), '0,00', '0,00', '0,00', '0,00', '0,00', _brl(d['total'])] if ultima \
        else ['(continua)'] + [''] * 6
    for n, (r, v) in enumerate(zip(rotulos, valores)):
        f.caixa(m + n * largura, y, largura - 4, 20, r, v)
    y -= 30
    f.caixa(m, y, W / 3 - 4, 26, '66 - Assinatura do Responsável pela Autorização')
    f.caixa(m + W / 3, y, W / 3 - 4, 26, '67 - Assinatura do Beneficiário ou Responsável')
    f.caixa(m + 2 * W / 3, y, W / 3, 26, '68 - Assinatura do Contratado')


def pdf_da_guia(guia):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    largura, altura = landscape(A4)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(largura, altura))
    c.setTitle(f'{guia.get_tipo_display()} {guia.numero_prestador}')
    c.setAuthor('NeuroDoc')
    d = dados(guia)
    f = _Folha(c, largura, altura)
    if guia.tipo == TipoGuia.CONSULTA:
        _consulta(f, guia, d)
        c.showPage()
    else:
        blocos = [d['itens'][i:i + LINHAS_POR_FOLHA] for i in range(0, len(d['itens']), LINHAS_POR_FOLHA)] or [[]]
        for n, bloco in enumerate(blocos, start=1):
            _sadt_folha(f, guia, d, bloco, n, len(blocos))
            c.showPage()
    c.save()
    return buffer.getvalue()
