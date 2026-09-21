"""Estrutura comum a todo documento médico: timbre, identificação e rodapé.

O que muda entre uma receita e um encaminhamento é o miolo. O resto — quem
assina, para quem, quando, sob que número, e como conferir se é verdadeiro —
é o mesmo, e é o que a CFM 2.381/2024 exige em todos eles.
"""

import io

from django.conf import settings
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

STYLES = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle('DocTitle', parent=STYLES['Title'], alignment=TA_CENTER, fontSize=14)
LABEL_STYLE = ParagraphStyle('Label', parent=STYLES['Normal'], fontName='Helvetica-Bold', fontSize=9)
BODY_STYLE = ParagraphStyle('Body', parent=STYLES['Normal'], fontSize=10, leading=14)
SMALL_STYLE = ParagraphStyle('Small', parent=STYLES['Normal'], fontSize=7.5, leading=10,
                             textColor=colors.HexColor('#555555'))
CLINIC_NAME_STYLE = ParagraphStyle('ClinicName', parent=STYLES['Normal'],
                                   fontName='Helvetica-Bold', fontSize=11, leading=14)
VIA_STYLE = ParagraphStyle('Via', parent=STYLES['Normal'], fontName='Helvetica-Bold',
                           fontSize=8.5, alignment=TA_RIGHT,
                           textColor=colors.HexColor('#444444'))

#: Lado do QR no papel. Grande o bastante para a câmera de um celular comum
#: ler de uma folha impressa em impressora doméstica, e pequeno o bastante
#: para não disputar espaço com a prescrição.
QR_SIZE = 26 * mm


def _physician_profile(document):
    return document.physician.user.physician_profile


def _clinic_profile(document):
    from tenancy.models import ClinicProfile

    return ClinicProfile.objects.filter(tenant_id=document.tenant_id).first()


def verification_url(document):
    """Endereço que o QR carrega.

    Só o código opaco, nunca nome, CPF ou conteúdo. Um QR impresso numa
    receita é lido por qualquer câmera, inclusive a de quem está atrás na
    fila da farmácia — o que ele revelar, revela para essa pessoa.
    """
    base = (settings.PUBLIC_BASE_URL or '').rstrip('/')
    return f'{base}/verificar/{document.validation_token}/'


def format_validation_code(token):
    """O código em grupos de quatro, para conferir de olho e digitar.

    A página de verificação aceita digitação porque QR falha: impressão
    borrada, folha amassada, celular sem câmera. Sem uma forma de digitar, o
    documento com QR ilegível deixa de ser verificável.
    """
    clean = (token or '').upper()[:16]
    return '-'.join(clean[i:i + 4] for i in range(0, len(clean), 4))


def _qr_flowable(document):
    """O QR — e ele só existe com assinatura digital.

    O QR leva à página que responde "esta receita saiu mesmo daquele
    consultório e não foi alterada?". Quem sustenta essa resposta é a
    assinatura, que cobre os bytes do arquivo. Num rascunho, ou num
    documento impresso para ser assinado à caneta, não há o que o QR
    prometa — e um QR impresso ali faria o balconista da farmácia conferir
    e receber "documento não emitido", ou pior, tratá-lo como conferido.

    Antes o QR saía em qualquer PDF: `validation_token` é atribuído já na
    criação do rascunho, e a única condição era ele existir.
    """
    if document.status != 'issued' or not document.validation_token:
        return None
    widget = qr.QrCodeWidget(verification_url(document), barLevel='M')
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(QR_SIZE, QR_SIZE, transform=[QR_SIZE / width, 0, 0, QR_SIZE / height, 0, 0])
    drawing.add(widget)
    return drawing


def _logo_flowable(clinic):
    """Logotipo da clínica, se houver e se o arquivo abrir.

    Falha em silêncio de propósito: arquivo perdido numa restauração de
    backup não pode impedir a emissão de uma receita. O documento sai com o
    cabeçalho em texto.
    """
    if clinic is None or not clinic.has_logo:
        return None
    try:
        from tenancy.branding import read_logo

        content = read_logo(clinic)
        if not content:
            return None
        image = Image(io.BytesIO(content))
        ratio = image.imageHeight / image.imageWidth if image.imageWidth else 1
        image.drawWidth = 3.2 * cm
        image.drawHeight = min(3.2 * cm * ratio, 2.0 * cm)
        if ratio:
            image.drawWidth = image.drawHeight / ratio
        return image
    except Exception:                                   # noqa: BLE001
        return None


def _letterhead(document, clinic):
    """Timbre: logotipo à esquerda, clínica e médico à direita.

    Numa tabela e não em parágrafos empilhados porque as duas colunas
    precisam ficar lado a lado com alturas diferentes — e porque sem
    logotipo a coluna simplesmente some, sem deixar buraco.
    """
    profile = _physician_profile(document)
    rqe = f' — RQE {profile.rqe}' if profile.rqe else ''

    right = []
    if clinic is not None:
        tenant = document.tenant
        name = tenant.trade_name or tenant.legal_name
        right.append(Paragraph(name, CLINIC_NAME_STYLE))
        endereco = clinic.address_summary()
        if endereco:
            right.append(Paragraph(endereco, SMALL_STYLE))
        contato = ' · '.join(p for p in [clinic.phone, clinic.email, clinic.website] if p)
        if contato:
            right.append(Paragraph(contato, SMALL_STYLE))
        right.append(Spacer(1, 0.15 * cm))

    right.append(Paragraph(
        f'{profile.professional_name} — CRM {profile.crm_number}/{profile.crm_state}{rqe}',
        LABEL_STYLE,
    ))
    contact_bits = [b for b in [profile.professional_address, profile.professional_phone,
                                profile.professional_email] if b]
    if contact_bits:
        right.append(Paragraph(' | '.join(contact_bits), SMALL_STYLE))

    logo = _logo_flowable(clinic)
    if logo is None:
        return right

    table = Table([[logo, right]], colWidths=[3.6 * cm, None])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return [table]


def format_cpf(cpf):
    """CPF pontuado. Guardado só com dígitos, impresso como se lê.

    Num documento que a farmácia confere contra o RG do paciente, um número
    de onze dígitos corridos obriga a contar com o dedo.
    """
    digits = ''.join(c for c in (cpf or '') if c.isdigit())
    if len(digits) != 11:
        return cpf or ''
    return f'{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}'


def format_postal_code(code):
    digits = ''.join(c for c in (code or '') if c.isdigit())
    if len(digits) != 8:
        return code or ''
    return f'{digits[:5]}-{digits[5:]}'


def patient_address(patient):
    """Endereço do paciente em uma linha.

    Exigência do Receituário de Controle Especial (Portaria SVS/MS 344/98):
    sem endereço completo do paciente a farmácia não pode reter a receita, e
    ele volta ao consultório para pedir outra. Devolve texto explícito
    quando falta, em vez de linha vazia — a falta tem de ser visível para
    quem revisa antes de assinar.
    """
    street = ', '.join(p for p in [patient.street, patient.number] if p)
    if patient.complement:
        street = f'{street} — {patient.complement}' if street else patient.complement
    place = f'{patient.city}/{patient.state}' if patient.city and patient.state else (patient.city or '')
    parts = [street, patient.district, place, format_postal_code(patient.postal_code)]
    return ' — '.join(p for p in parts if p) or 'NÃO INFORMADO'


def _patient_block(document, include_address):
    patient = document.patient
    birth = patient.birth_date.strftime('%d/%m/%Y') if patient.birth_date else 'não informada'
    rows = [
        Paragraph(f'<b>Paciente:</b> {patient.full_name}', BODY_STYLE),
        Paragraph(f'<b>Nascimento:</b> {birth}', BODY_STYLE),
    ]
    if patient.record_number:
        # O número do prontuário sai no papel para o caminho de volta:
        # o paciente liga citando a receita, e a recepção acha a ficha
        # pelo número em vez de pelo nome, que pode ter homônimo.
        rows.append(Paragraph(f'<b>Prontuário:</b> {patient.record_number}', BODY_STYLE))
    if patient.cpf:
        rows.append(Paragraph(f'<b>CPF:</b> {format_cpf(patient.cpf)}', BODY_STYLE))
    if include_address:
        rows.append(Paragraph(f'<b>Endereço:</b> {patient_address(patient)}', BODY_STYLE))
    # A data do atendimento quando há um; senão, a da emissão, e por fim a
    # da criação do rascunho.
    #
    # `document.encounter` passou a ser opcional: a renovação de receita
    # pedida por telefone não tem consulta. Antes esta linha era
    # `document.encounter.occurred_at` direto, e um documento sem
    # atendimento estourava `AttributeError` no meio de gerar o PDF — com o
    # rascunho já criado no banco e nenhum arquivo.
    momento = (
        document.encounter.occurred_at if document.encounter_id
        else (document.issued_at or document.created_at)
    )
    rows.append(Paragraph(
        f'<b>Data do documento:</b> {momento.strftime("%d/%m/%Y")}',
        BODY_STYLE,
    ))
    doc_number = document.document_number or 'RASCUNHO — sem validade até a emissão'
    rows.append(Paragraph(f'<b>Número:</b> {doc_number} (versão {document.version})', BODY_STYLE))
    return rows


def _signature_footer(document):
    """Rodapé: assinatura, QR e código de verificação.

    O QR aponta para a página de verificação **deste** sistema, e não para
    um validador de assinatura genérico. São perguntas diferentes: o
    validador do ITI responde "esta assinatura é criptograficamente
    válida?", e quem está na farmácia precisa de "esta receita saiu mesmo
    daquele consultório e não foi alterada?". A página responde a segunda e
    aponta para a primeira.
    """
    issued = document.status == 'issued'
    no_papel = document.status == 'issued_on_paper'
    profile = _physician_profile(document)

    left = [
        Paragraph('_' * 42, BODY_STYLE),
        Paragraph(profile.professional_name, LABEL_STYLE),
        Paragraph(f'CRM {profile.crm_number}/{profile.crm_state}', SMALL_STYLE),
    ]
    if issued:
        assinado = document.issued_at.strftime('%d/%m/%Y às %H:%M') if document.issued_at else ''
        left.append(Spacer(1, 0.15 * cm))
        left.append(Paragraph(
            'Assinado digitalmente (PAdES/ICP-Brasil)'
            + (f' em {assinado}.' if assinado else '.'),
            SMALL_STYLE,
        ))
        digest = (document.signature_metadata or {}).get('content_sha256', '')
        if digest:
            left.append(Paragraph(f'SHA-256: {digest[:32]}…', SMALL_STYLE))
    elif no_papel:
        # Nem tarja de rascunho nem declaração de assinatura digital: o
        # papel vale pela assinatura de próprio punho e pelo carimbo, e o
        # rodapé diz isso em vez de afirmar o que não houve.
        left.append(Spacer(1, 0.15 * cm))
        left.append(Paragraph(
            'Documento emitido para assinatura de próprio punho. '
            'Válido apenas com a assinatura e o carimbo do profissional.',
            SMALL_STYLE,
        ))
    else:
        left.append(Spacer(1, 0.15 * cm))
        left.append(Paragraph(
            'RASCUNHO SEM VALIDADE — só vale depois de revisado e assinado digitalmente.',
            ParagraphStyle('Warning', parent=SMALL_STYLE, textColor=colors.red),
        ))

    qr_drawing = _qr_flowable(document)
    if qr_drawing is None:
        return left

    right = [
        qr_drawing,
        Paragraph('Confira este documento em', SMALL_STYLE),
        Paragraph(f'<b>{verification_url(document)}</b>', SMALL_STYLE),
        Paragraph(f'Código: {format_validation_code(document.validation_token)}', SMALL_STYLE),
    ]
    table = Table([[left, right]], colWidths=[None, 4.6 * cm])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    # `KeepTogether` para a assinatura não ficar numa página e o QR na
    # seguinte: um documento cuja assinatura se separou do código de
    # verificação é um documento que a farmácia devolve.
    return [KeepTogether([table])]


# --------------------------------------------------- receituário de controle
#
# O quadro de identificação do comprador e do fornecedor, exigido pelo
# Anexo XVII da Portaria SVS/MS nº 344/1998 na Notificação de Receita e no
# Receituário de Controle Especial.
#
# Sai **em branco**, para ser preenchido à mão no balcão da farmácia. Não é
# o sistema que sabe quem vai comprar: o comprador pode ser o paciente, um
# familiar ou um cuidador, e quem confere o documento de identidade dele é
# o farmacêutico no ato da dispensação. Preencher com os dados do paciente
# afirmaria, num papel que fica retido, que foi ele quem comprou — o que
# nem sempre é verdade e não é o sistema que pode atestar.
#
# Vai nas **duas** vias. A 1ª fica retida na farmácia e é a que responde à
# fiscalização sanitária; a 2ª é a prova do paciente de que a compra
# ocorreu, e sem o quadro ela não registra nada sobre a dispensação.

CONTROL_BOX_LABEL = ParagraphStyle(
    'ControlBoxLabel', parent=STYLES['Normal'], fontName='Helvetica-Bold',
    fontSize=6.5, leading=8, textColor=colors.HexColor('#333333'),
)
CONTROL_FIELD = ParagraphStyle(
    'ControlField', parent=STYLES['Normal'], fontSize=7, leading=15,
    textColor=colors.HexColor('#111111'),
)

#: Altura das linhas de preenchimento. Precisa caber letra de mão adulta:
#: uma linha de 8pt obriga quem escreve a espremer, e endereço espremido
#: em receita retida é endereço ilegível na fiscalização.
_WRITE_LINE = 0.72 * cm


def _control_identification_block():
    """Os dois quadros lado a lado, com as linhas de preenchimento.

    Numa tabela aninhada, e não em parágrafos com sublinhado: as duas
    colunas têm alturas iguais e bordas próprias, e é a borda que faz o
    balconista enxergar dois quadros em vez de um bloco de texto.
    """
    def campo(texto):
        return Paragraph(texto, CONTROL_FIELD)

    comprador = Table(
        [
            [campo('Nome:'), ''],
            [campo('Ident.:'), campo('Órg. Emissor:')],
            [campo('End.:'), ''],
            [campo('Cidade:'), campo('UF:')],
            [campo('Telefone:'), ''],
        ],
        colWidths=[4.7 * cm, 3.1 * cm],
        rowHeights=[_WRITE_LINE] * 5,
    )
    comprador.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('SPAN', (0, 0), (1, 0)),
        ('SPAN', (0, 2), (1, 2)),
        ('SPAN', (0, 4), (1, 4)),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor('#999999')),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    # O lado do fornecedor tem menos campos e mais espaço por campo: a
    # assinatura do farmacêutico e o carimbo da farmácia ocupam área, e
    # espreme-los faz o carimbo cobrir a data.
    fornecedor = Table(
        [
            [campo('Assinatura do farmacêutico:')],
            [''],
            [campo('Data:  ____ / ____ / ________')],
            [campo('Carimbo da farmácia / drogaria:')],
            [''],
        ],
        colWidths=[7.8 * cm],
        rowHeights=[0.42 * cm, _WRITE_LINE, _WRITE_LINE, 0.42 * cm, _WRITE_LINE],
    )
    fornecedor.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LINEBELOW', (0, 1), (0, 1), 0.4, colors.HexColor('#999999')),
        ('LINEBELOW', (0, 2), (0, 2), 0.4, colors.HexColor('#999999')),
        ('LINEBELOW', (0, 4), (0, 4), 0.4, colors.HexColor('#999999')),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    quadro = Table(
        [
            [Paragraph('IDENTIFICAÇÃO DO COMPRADOR', CONTROL_BOX_LABEL),
             Paragraph('IDENTIFICAÇÃO DO FORNECEDOR', CONTROL_BOX_LABEL)],
            [comprador, fornecedor],
        ],
        colWidths=[8.3 * cm, 8.3 * cm],
    )
    quadro.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (0, -1), 0.6, colors.HexColor('#666666')),
        ('BOX', (1, 0), (1, -1), 0.6, colors.HexColor('#666666')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, colors.HexColor('#666666')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, 0), 3),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
        ('TOPPADDING', (0, 1), (-1, 1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 2),
    ]))
    # `KeepTogether` porque o quadro partido entre duas páginas deixa
    # metade dos campos numa folha que não é a que a farmácia retém.
    return [KeepTogether([quadro])]


def _one_copy(document, title, body_flowables, clinic, via_label='', include_address=False,
              control_identification=False):
    story = []
    if via_label:
        story.append(Paragraph(via_label, VIA_STYLE))
        story.append(Spacer(1, 0.1 * cm))
    story.extend(_letterhead(document, clinic))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(title, TITLE_STYLE))
    story.append(Spacer(1, 0.4 * cm))
    story.extend(_patient_block(document, include_address))
    story.append(Spacer(1, 0.5 * cm))
    story.extend(body_flowables)
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5))
    story.append(Spacer(1, 0.3 * cm))
    story.extend(_signature_footer(document))
    if control_identification:
        # Depois da assinatura, no pe da folha.
        #
        # Esta ordem ja foi a inversa, com o argumento de que a assinatura
        # de quem emite fecha o documento e nao deve ter campos em branco
        # embaixo. O argumento e razoavel e esta errado: o formulario do
        # Anexo XVII da Portaria SVS/MS 344/98 traz os dois quadros no
        # rodape, abaixo da assinatura do prescritor, e e la que o
        # balconista da farmacia aprendeu a procura-los. Uma receita que
        # os coloca no meio da folha obriga quem dispensa a caçar o campo
        # -- e o custo de contrariar um formulario que todo mundo conhece
        # e pago no balcao, nao aqui.
        story.append(Spacer(1, 0.7 * cm))
        story.extend(_control_identification_block())
    return story


def build_pdf(document, title, body_flowables, copies=(), include_address=False,
              control_identification=False):
    """Monta o PDF. `copies` são os rótulos das vias, quando há mais de uma.

    Uma via por página, e não duas metades na mesma folha: a farmácia retém
    a primeira e o paciente leva a segunda, e isso só funciona se cada uma
    for uma folha inteira com identificação e assinatura próprias.

    `body_flowables` é reconstruído por via — um `Flowable` do reportlab
    guarda estado de posicionamento depois de desenhado, e reaproveitar a
    mesma instância em duas páginas produz a segunda em branco. Por isso o
    parâmetro pode ser uma função que devolve a lista.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
        title=f'{title} — {document.document_number or "rascunho"}',
        author=_physician_profile(document).professional_name,
    )
    clinic = _clinic_profile(document)

    def flowables_for_copy():
        return body_flowables() if callable(body_flowables) else list(body_flowables)

    story = []
    labels = list(copies) or ['']
    for index, label in enumerate(labels):
        if index:
            from reportlab.platypus import PageBreak

            story.append(PageBreak())
        story.extend(_one_copy(
            document, title, flowables_for_copy(), clinic,
            via_label=label, include_address=include_address,
            control_identification=control_identification,
        ))

    doc.build(story)
    return buf.getvalue()
