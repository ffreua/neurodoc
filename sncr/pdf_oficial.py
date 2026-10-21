"""O PDF da receita eletrônica do SNCR: o modelo da Anvisa, preenchido.

**A RCE é escrita por cima do próprio modelo oficial**, e não redesenhada.
`modelos/rce_eletronica_anvisa.pdf` é o arquivo publicado pela Anvisa em
"Modelos de receituários eletrônicos" (revisão de 13/03/2026); o gerador
abre a página dele e acrescenta só os valores, nas posições medidas no
próprio arquivo. Caixas, rótulos, fontes e o rodapé são os do modelo —
redesenhar "parecido" é o que a FAQ de Integração (P40–41) proíbe, e um
redesenho por aproximação nunca se prova igual. O SHA-256 do modelo está
em `SHA256_MODELO_RCE`: trocar o arquivo sem trocar a constante derruba a
geração em vez de imprimir outro modelo em silêncio.

**A RET não tem modelo oficial** (página Receituário Eletrônico,
"Receituários não contemplados"; decisão D5). Ela sai com a **mesma
estrutura** do modelo da RCE — título, N.º, emitente, paciente,
prescrição, rodapé de verificação —, desenhada aqui, sem timbre, logotipo
nem marca da clínica, e com os campos que a RDC 471/2021 pede do paciente
(idade e sexo).

**Uma folha por medicamento** (decisão I12). O modelo da Anvisa tem os
campos de um medicamento; cada medicamento sai numa página do modelo, com
o **número SNCR próprio**, e o PDF reúne as folhas numa assinatura só.
Cada folha é uma receita inteira — emitente, paciente, prescrição,
rodapé e QR — para que a farmácia que recebe uma delas não dependa das
outras.

**O que nunca entra**, nas duas (decisão D6): o cabeçalho e o rodapé da
clínica de `documents/pdf/common.py`. `build_pdf` não é chamado daqui.

**Rascunho e homologação vêm marcados.** O rascunho sai com a tarja
"RASCUNHO — SEM VALIDADE" e sem número nem QR; a receita numerada no
ambiente de **homologação** da Anvisa sai com "HOMOLOGAÇÃO — SEM VALIDADE",
porque o número do treinamento não vale em farmácia nenhuma.

Coordenadas: medidas com a origem no **alto** da página (como o PyMuPDF
as devolve), em pontos, e convertidas por `_y`. A página do modelo começa
em y = 7,83 (`mediabox`), e a camada de valores é desenhada no mesmo
sistema de coordenadas e mesclada sem transformação.
"""

import hashlib
import io
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, black, white
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas

from .receita import ReceitaInvalida

MODELO_RCE = Path(__file__).resolve().parent / 'modelos' / 'rce_eletronica_anvisa.pdf'
SHA256_MODELO_RCE = '112946ead832ec07f9343f81b35b3571065eb51dea5526cf5c949e0259c11fde'

#: Página do modelo: 595,5 × 842,25 pt, começando em y = 7,83.
LARGURA = 595.5
TOPO = 850.08
BASE = 7.83

FONTE = 'Helvetica'
FONTE_NEGRITO = 'Helvetica-Bold'
FONTE_ITALICO = 'Helvetica-Oblique'

#: Caixas do modelo (x0, y0, x1, y1, origem no alto).
CAIXA_NUMERO = (370.5, 22.8, 586.8, 59.5)
CAIXA_EMITENTE = (24.5, 113.3, 282.8, 307.0)
CAIXA_PACIENTE = (297.8, 113.3, 586.7, 307.0)
CAIXA_PRESCRICAO = (26.2, 340.4, 586.7, 673.1)
ALTURA_TITULO_CAIXA = 26.4
QR = (491.6, 712.0, 558.2, 782.4)

#: Rótulos do quadro "Emitente": topo e fim (y1) do texto, medidos.
EMITENTE_X, EMITENTE_FIM_X = 31.3, 278.0
PACIENTE_X, PACIENTE_FIM_X = 306.9, 582.0
QUADRO_TOPOS = (150.7, 190.1, 229.5, 268.9)
QUADRO_ALTURA_ROTULO = 14.6

#: Rótulos da prescrição no modelo: (topo, fim do rótulo em x, base do texto).
PRESCRICAO_X = 36.2
PRESCRICAO_FIM_X = 580.0
ROTULOS_PRESCRICAO_RCE = {
    'nome': (377.2, 281.0),
    'concentracao': (407.0, 134.1),
    'forma': (436.7, 170.7),
    'quantidade': (466.5, 115.3),
    'posologia': (496.3, 106.6),
}
TAMANHO_ROTULO_PRESCRICAO = 11.92

#: Rodapé: (topo do rótulo, fim do rótulo em x).
RODAPE_PLATAFORMA = (705.5, 139.2)
RODAPE_ASSINATURA = (726.7, 172.8)
RODAPE_VERIFICACAO = (769.1, 181.0)
TAMANHO_RODAPE = 7.96
RODAPE_FIM_X = 486.0

VALOR = 10.0
VALOR_QUADRO = 8.6
VALOR_RODAPE = 6.8


def _y(topo):
    """De "distância do alto" para a coordenada do PDF."""
    return TOPO - topo


def _base(topo_do_rotulo, tamanho):
    """A linha de base de um texto cujo retângulo começa em `topo_do_rotulo`.

    O retângulo do Open Sans vai do ascendente ao descendente; a base fica
    a ~1,07 do tamanho (métrica do Open Sans) abaixo do topo. Mesma conta para os valores, para que
    o valor e o rótulo assentem na mesma linha.
    """
    return topo_do_rotulo + tamanho * 1.07


def _carregar_modelo_rce():
    dados = MODELO_RCE.read_bytes()
    if hashlib.sha256(dados).hexdigest() != SHA256_MODELO_RCE:
        raise RuntimeError(
            'O modelo oficial da RCE eletrônica não confere com o SHA-256 registrado em '
            'sncr/pdf_oficial.py. Um modelo novo da Anvisa entra com a constante trocada no mesmo commit.'
        )
    return dados


# --- valores do documento ------------------------------------------------------

def _clinica(document):
    from tenancy.models import ClinicProfile

    return ClinicProfile.objects.filter(tenant_id=document.tenant_id).first()


def _emitente(document):
    perfil = document.physician.user.physician_profile
    clinica = _clinica(document)
    endereco = (clinica.address_summary() if clinica else '') or perfil.professional_address or ''
    telefone = (clinica.phone if clinica else '') or perfil.professional_phone or ''
    return [
        perfil.professional_name,
        f'CRM {perfil.crm_number} / {perfil.crm_state}',
        endereco,
        telefone,
    ]


def _idade(nascimento, hoje):
    anos = hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
    return f'{anos} anos'


def _paciente(document, com_idade_e_sexo):
    from documents.pdf.common import format_cpf, patient_address

    p = document.patient
    valores = [p.full_name, format_cpf(p.cpf)]
    if com_idade_e_sexo:
        hoje = timezone.localdate()
        idade = _idade(p.birth_date, hoje) if p.birth_date else 'não informada'
        sexo = p.get_sex_at_registration_display() if getattr(p, 'sex_at_registration', '') else 'não informado'
        valores.append(f'{idade} — {sexo}')
    valores.append(patient_address(p))
    return valores


def numeros_do_documento(document):
    """Os números SNCR, um por folha e na ordem dos medicamentos.

    Os que a assinatura acabou de reservar (ainda só em memória), os
    gravados nos metadados da emitida, ou — para o PDF redesenhado depois —
    os do banco, na mesma ordem do bloco que a reserva usou.
    """
    numeros = getattr(document, 'nd_numeros_sncr', None)
    if numeros:
        return list(numeros)
    meta = (document.signature_metadata or {}).get('sncr') or {}
    if meta.get('numeros'):
        return list(meta['numeros'])
    from .numeracao import numeros_do_documento as do_banco

    return [n.numero for n in do_banco(document.pk)]


def _ambiente_de_homologacao(document):
    ambiente = getattr(document, 'nd_ambiente_sncr', None)
    if ambiente is None:
        ambiente = ((document.signature_metadata or {}).get('sncr') or {}).get('ambiente')
    if ambiente is None:
        from .models import NumeroSncr

        registro = NumeroSncr.objects.filter(documento_id=document.pk).first()
        ambiente = registro.ambiente if registro else None
    return ambiente == 'homologacao'


def _identificacao_da_plataforma(document, folha, total):
    from base.version import VERSION

    from .models import Configuracao

    cnpj = ''.join(c for c in Configuracao.carregar().cnpj_mantenedora if c.isdigit())
    host = (settings.PUBLIC_BASE_URL or '').split('://')[-1].rstrip('/')
    partes = [f'NeuroDoc {VERSION}', host]
    if len(cnpj) == 14:
        partes.append(f'CNPJ {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}')
    partes.append(f'documento {document.document_number or "em rascunho"}')
    if total > 1:
        # A folha diz que faz parte de um conjunto, sem depender das outras:
        # cada uma tem número SNCR próprio e vale sozinha na farmácia.
        partes.append(f'receita {folha} de {total}')
    return ' · '.join(p for p in partes if p)


def _registro_da_assinatura(document):
    registro = getattr(document, 'nd_registro_assinatura', None)
    if registro:
        return registro
    meta = document.signature_metadata or {}
    return meta.get('sncr', {}).get('registro_assinatura', '')


# --- desenho ---------------------------------------------------------------------

def _texto(c, x, topo, texto, fonte=FONTE, tamanho=VALOR, cor=black):
    c.setFillColor(cor)
    c.setFont(fonte, tamanho)
    c.drawString(x, _y(_base(topo, tamanho)), texto)


def _linhas(texto, largura, fonte, tamanho, largura_primeira=None):
    """Quebra em linhas; a primeira pode ser mais curta (começa depois do rótulo)."""
    if largura_primeira is None or largura_primeira >= largura:
        return simpleSplit(texto, fonte, tamanho, largura)
    palavras, primeira = texto.split(), ''
    while palavras and stringWidth((primeira + ' ' + palavras[0]).strip(), fonte, tamanho) <= largura_primeira:
        primeira = (primeira + ' ' + palavras.pop(0)).strip()
    resto = simpleSplit(' '.join(palavras), fonte, tamanho, largura) if palavras else []
    return ([primeira] if primeira else []) + resto


def _valor_no_quadro(c, x, x_fim, indice, texto):
    """O valor abaixo do rótulo do quadro, em até duas linhas (ou mais no último)."""
    topo = QUADRO_TOPOS[indice] + QUADRO_ALTURA_ROTULO + 0.5
    proximo = QUADRO_TOPOS[indice + 1] if indice + 1 < len(QUADRO_TOPOS) else CAIXA_EMITENTE[3] - 2
    linhas = _linhas(texto or '—', x_fim - x, FONTE, VALOR_QUADRO)
    cabem = max(1, int((proximo - topo) // (VALOR_QUADRO * 1.15)))
    if len(linhas) > cabem:
        raise ReceitaInvalida('Um dado do emitente ou do paciente é longo demais para o modelo da Anvisa.')
    for n, linha in enumerate(linhas):
        _texto(c, x, topo + n * VALOR_QUADRO * 1.15, linha, tamanho=VALOR_QUADRO)


def _item_no_modelo(c, item, rotulos, fim_x):
    """O primeiro item: cada valor na linha do rótulo do modelo. Devolve o
    topo livre depois dele."""
    entrelinha = VALOR * 1.25
    ultimo = 0
    for campo, (topo, fim_rotulo) in rotulos.items():
        x = fim_rotulo + 5
        linhas = _linhas(item[campo], fim_x - PRESCRICAO_X, FONTE, VALOR, largura_primeira=fim_x - x)
        ajuste = (TAMANHO_ROTULO_PRESCRICAO - VALOR) * 1.07
        for n, linha in enumerate(linhas):
            _texto(c, x if n == 0 else PRESCRICAO_X, topo + ajuste + n * entrelinha, linha)
        ultimo = topo + ajuste + max(len(linhas) - 1, 0) * entrelinha
    return ultimo + VALOR * 1.6


_ROTULOS = (
    ('nome', 'NOME DO MEDICAMENTO OU SUBSTÂNCIA:'),
    ('concentracao', 'CONCENTRAÇÃO:'),
    ('forma', 'FORMA FARMACÊUTICA:'),
    ('quantidade', 'QUANTIDADE:'),
    ('posologia', 'POSOLOGIA:'),
)


def _prescricao(c, item, rotulos):
    """O medicamento da folha, cada valor na linha do rótulo do modelo."""
    topo = _item_no_modelo(c, item, rotulos, PRESCRICAO_FIM_X)
    if topo > CAIXA_PRESCRICAO[3] - 4:
        raise ReceitaInvalida(
            f'O medicamento {item["nome"]} não cabe na folha do modelo da Anvisa. Encurte a posologia.'
        )


def _rodape(c, document, rascunho, folha, total, rodape=None):
    """Os valores depois dos rótulos do rodapé. `rodape` troca as posições
    medidas no modelo da RCE pelas da RET, cujos rótulos são desenhados em
    outra fonte e terminam noutro ponto."""
    plataforma, assinatura, verificacao = rodape or (RODAPE_PLATAFORMA, RODAPE_ASSINATURA, RODAPE_VERIFICACAO)
    dados = (
        (plataforma, _identificacao_da_plataforma(document, folha, total)),
        (assinatura, 'será registrado na assinatura' if rascunho else _registro_da_assinatura(document)),
    )
    if not rascunho:
        from documents.pdf.common import format_validation_code, verification_url

        dados += ((verificacao, f'{verification_url(document)} — código '
                                f'{format_validation_code(document.validation_token)}'),)
    for (topo, fim_rotulo), texto in dados:
        x = fim_rotulo + 4
        ajuste = (TAMANHO_RODAPE - VALOR_RODAPE) * 1.07
        linhas = _linhas(texto, RODAPE_FIM_X - PRESCRICAO_X, FONTE, VALOR_RODAPE,
                         largura_primeira=RODAPE_FIM_X - x)
        for n, linha in enumerate(linhas[:2]):
            _texto(c, x if n == 0 else x, topo + ajuste + n * VALOR_RODAPE * 1.15, linha, tamanho=VALOR_RODAPE)


def _qr(c, document, rascunho):
    """O QR leva à página de verificação **do NeuroDoc** (decisão I9).

    O modelo traz um QR de exemplo nesse lugar; ele é coberto. Para receita
    de plataforma privada, a verificação da assinatura é a indicada pela
    própria plataforma (FAQ RDC 1.000, pergunta 42), e o rodapé do modelo
    diz "esta prescrição pode ser verificada em:" — é para lá que o QR
    aponta. A numeração continua sendo conferida em sncr.anvisa.gov.br,
    como o rodapé impresso manda.
    """
    x0, y0, x1, y1 = QR
    c.setFillColor(white)
    c.setStrokeColor(white)
    c.rect(x0 - 1, _y(y1 + 1), x1 - x0 + 2, y1 - y0 + 2, stroke=0, fill=1)
    if rascunho:
        _texto(c, x0 + 4, (y0 + y1) / 2 - 4, 'QR na emissão', tamanho=7, cor=Color(0.5, 0.5, 0.5))
        return
    from documents.pdf.common import verification_url

    lado = min(x1 - x0, y1 - y0)
    widget = qr.QrCodeWidget(verification_url(document), barLevel='M')
    b = widget.getBounds()
    desenho = Drawing(lado, lado, transform=[lado / (b[2] - b[0]), 0, 0, lado / (b[3] - b[1]), 0, 0])
    desenho.add(widget)
    renderPDF.draw(desenho, c, x0, _y(y0 + lado))


def _tarja(c, texto):
    c.saveState()
    c.setFillColor(Color(0.85, 0.1, 0.1, alpha=0.18))
    c.setFont(FONTE_NEGRITO, 46)
    c.translate(LARGURA / 2, TOPO / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, texto)
    c.restoreState()


def _numero(c, numero, rascunho):
    if numero and not rascunho:
        _texto(c, 400.0, 31.3 + (13.39 - 13) * 1.07, numero, fonte=FONTE_NEGRITO, tamanho=13)
    else:
        _texto(c, 400.0, 35.0, 'atribuído pelo SNCR na assinatura', tamanho=8, cor=Color(0.45, 0.45, 0.45))


def _itens(document):
    itens = (document.content_snapshot or {}).get('itens') or []
    if not itens:
        raise ReceitaInvalida('A receita eletrônica não tem medicamentos.')
    return itens


def _numeros_das_folhas(document, itens, rascunho):
    """Um número por folha; o rascunho não tem nenhum.

    A emitida com quantidade de números diferente da de medicamentos não é
    desenhada: uma folha sem número, ou com o número de outra, sairia
    parecendo válida.
    """
    if rascunho:
        return [''] * len(itens)
    numeros = numeros_do_documento(document)
    if len(numeros) != len(itens):
        raise ReceitaInvalida(
            f'A receita tem {len(itens)} medicamento(s) e {len(numeros)} número(s) SNCR; '
            'cada folha precisa do seu.'
        )
    return numeros


def _camada(document, item, numero, folha, total, desenhar_estrutura=None, rotulos=ROTULOS_PRESCRICAO_RCE,
            com_idade_e_sexo=False, rodape=None):
    """A camada de valores de uma folha, do tamanho exato da página do modelo."""
    rascunho = document.status != 'issued'
    saida = io.BytesIO()
    c = pdfcanvas.Canvas(saida, pagesize=(LARGURA, TOPO))
    if desenhar_estrutura:
        desenhar_estrutura(c)
    _numero(c, numero, rascunho)
    for indice, valor in enumerate(_emitente(document)):
        _valor_no_quadro(c, EMITENTE_X, EMITENTE_FIM_X, indice, valor)
    for indice, valor in enumerate(_paciente(document, com_idade_e_sexo)):
        _valor_no_quadro(c, PACIENTE_X, PACIENTE_FIM_X, indice, valor)
    _prescricao(c, item, rotulos)
    _rodape(c, document, rascunho, folha, total, rodape)
    _qr(c, document, rascunho)
    if rascunho:
        _tarja(c, 'RASCUNHO — SEM VALIDADE')
    elif _ambiente_de_homologacao(document):
        _tarja(c, 'HOMOLOGAÇÃO — SEM VALIDADE')
    c.showPage()
    c.save()
    return saida.getvalue()


def _juntar(base_pdf, camadas, titulo):
    """Uma página do modelo por camada, cada uma lida de novo do modelo
    (mesclar duas camadas na mesma página as sobreporia)."""
    from pypdf.generic import RectangleObject

    escritor = PdfWriter()
    for camada_pdf in camadas:
        pagina = PdfReader(io.BytesIO(base_pdf)).pages[0]
        pagina.merge_page(PdfReader(io.BytesIO(camada_pdf)).pages[0])
        # A página fica do tamanho da do modelo (595,5 × 842,25, começando
        # em 7,83): a RET, que nasce numa página em branco, sai do mesmo tamanho.
        pagina.mediabox = RectangleObject([0, BASE, LARGURA, TOPO])
        pagina.cropbox = RectangleObject([0, BASE, LARGURA, TOPO])
        escritor.add_page(pagina)
    escritor.add_metadata({'/Title': titulo, '/Producer': 'NeuroDoc'})
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def _folhas(document, **opcoes):
    itens = _itens(document)
    numeros = _numeros_das_folhas(document, itens, document.status != 'issued')
    total = len(itens)
    return [_camada(document, item, numero, folha, total, **opcoes)
            for folha, (item, numero) in enumerate(zip(itens, numeros), start=1)]


def render_rce(document):
    return _juntar(_carregar_modelo_rce(), _folhas(document), 'Receita de Controle Especial — eletrônica')


# --- RET: a mesma estrutura, desenhada ------------------------------------------

_ROTULOS_RET = {}


def _rotulos_ret():
    """Os rótulos da prescrição desenhados em Helvetica: o fim de cada um
    muda com a fonte, e o valor começa depois dele."""
    if not _ROTULOS_RET:
        for campo, rotulo in _ROTULOS:
            topo = ROTULOS_PRESCRICAO_RCE[campo][0]
            _ROTULOS_RET[campo] = (topo, PRESCRICAO_X + stringWidth(rotulo, FONTE, TAMANHO_ROTULO_PRESCRICAO))
    return _ROTULOS_RET


def _caixa(c, caixa, titulo=None):
    x0, y0, x1, y1 = caixa
    c.setStrokeColor(black)
    c.setLineWidth(1.5)
    c.roundRect(x0, _y(y1), x1 - x0, y1 - y0, 4, stroke=1, fill=0)
    if titulo:
        c.line(x0, _y(y0 + ALTURA_TITULO_CAIXA), x1, _y(y0 + ALTURA_TITULO_CAIXA))
        c.setFont(FONTE_NEGRITO, 13.55)
        c.setFillColor(black)
        c.drawCentredString((x0 + x1) / 2, _y(y0 + 18.5), titulo)


def _estrutura_ret(c):
    c.setFont(FONTE_NEGRITO, 17)
    c.drawString(28.0, _y(46.0), 'RECEITA SUJEITA À RETENÇÃO')
    c.setFont(FONTE_NEGRITO, 13.66)
    c.drawCentredString(197.0, _y(71.0), 'ELETRÔNICA')
    _caixa(c, CAIXA_NUMERO)
    _texto(c, 376.1, 31.3, 'N.º', tamanho=13.39)
    _caixa(c, CAIXA_EMITENTE, 'EMITENTE')
    _caixa(c, CAIXA_PACIENTE, 'PACIENTE')
    _caixa(c, CAIXA_PRESCRICAO, 'PRESCRIÇÃO')
    # 10 pt e não os 10,71 do modelo: em Helvetica, "INSCRIÇÃO NO CONSELHO
    # PROFISSIONAL / UF:" no tamanho do modelo encosta na borda da caixa.
    for topo, rotulo in zip(QUADRO_TOPOS, ('NOME DO PRESCRITOR:', 'INSCRIÇÃO NO CONSELHO PROFISSIONAL / UF:',
                                          'ENDEREÇO COMPLETO:', 'TELEFONE:')):
        _texto(c, EMITENTE_X, topo, rotulo, tamanho=10)
    for topo, rotulo in zip(QUADRO_TOPOS, ('NOME:', 'CPF:', 'IDADE E SEXO:', 'ENDEREÇO COMPLETO:')):
        _texto(c, PACIENTE_X, topo, rotulo, tamanho=10)
    for campo, rotulo in _ROTULOS:
        _texto(c, PRESCRICAO_X, ROTULOS_PRESCRICAO_RCE[campo][0], rotulo, tamanho=TAMANHO_ROTULO_PRESCRICAO)
    for topo, rotulo in _RODAPE_RET:
        _texto(c, 26.2, topo, rotulo, fonte=FONTE_ITALICO, tamanho=TAMANHO_RODAPE)


_RODAPE_RET = (
    (705.5, 'IDENTIFICAÇÃO DA PLATAFORMA'),
    (726.7, 'REGISTRO DA ASSINATURA DIGITAL E DATA'),
    (747.9, 'VALIDE ESSA ASSINATURA EM validar.iti.gov.br'),
    (769.1, 'ESTA PRESCRIÇÃO PODE SER VERIFICADA EM:'),
    (790.4, 'VERIFIQUE A NUMERAÇÃO E REGISTRE A UTILIZAÇÃO DESTA PRESCRIÇÃO EM sncr.anvisa.gov.br'),
)


def _fim_do_rotulo_ret(indice):
    topo, rotulo = _RODAPE_RET[indice]
    return (topo, 26.2 + stringWidth(rotulo, FONTE_ITALICO, TAMANHO_RODAPE))


def _pagina_em_branco():
    saida = io.BytesIO()
    c = pdfcanvas.Canvas(saida, pagesize=(LARGURA, TOPO))
    c.showPage()
    c.save()
    return saida.getvalue()


def render_ret(document):
    folhas = _folhas(document, desenhar_estrutura=_estrutura_ret, rotulos=_rotulos_ret(), com_idade_e_sexo=True,
                     rodape=(_fim_do_rotulo_ret(0), _fim_do_rotulo_ret(1), _fim_do_rotulo_ret(3)))
    return _juntar(_pagina_em_branco(), folhas, 'Receita Sujeita à Retenção — eletrônica')


def render(document):
    from .models import TipoReceita
    from .receita import tipo_do_documento

    if tipo_do_documento(document) == TipoReceita.RCE:
        return render_rce(document)
    return render_ret(document)


def registro_de_assinatura(perfil, credencial, quando):
    """O texto de "Registro da assinatura digital e data", montado antes de assinar.

    O PDF é desenhado e **depois** assinado; o que o rodapé diz tem de ser
    sabido antes. Nome, CRM, o certificado ICP-Brasil (número de série) e a
    hora de Brasília. A assinatura em si fica no arquivo e se confere no
    validar.iti.gov.br, como o modelo manda.
    """
    hora = timezone.localtime(quando).strftime('%d/%m/%Y %H:%M')
    serie = (credencial.certificate_serial or '')[:24]
    return (f'Assinado digitalmente por {perfil.professional_name} (CRM {perfil.crm_number}/{perfil.crm_state}) '
            f'com certificado ICP-Brasil nº {serie}, em {hora} (horário de Brasília).')


__all__ = ['render', 'render_rce', 'render_ret', 'registro_de_assinatura', 'numeros_do_documento']
