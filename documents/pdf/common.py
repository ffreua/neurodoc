import io

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

STYLES = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle('DocTitle', parent=STYLES['Title'], alignment=TA_CENTER, fontSize=14)
LABEL_STYLE = ParagraphStyle('Label', parent=STYLES['Normal'], fontName='Helvetica-Bold', fontSize=9)
BODY_STYLE = ParagraphStyle('Body', parent=STYLES['Normal'], fontSize=10, leading=14)


def _physician_profile(document):
    return document.physician.user.physician_profile


def build_pdf(document, title, body_flowables):
    """Assembles the shared header (physician/patient identification, date,
    document number) and footer (signature status) around a kind-specific
    body. Physician/CRM/RQE/contact and patient identification are required
    on every medical document per CFM 2.381/2024 (PRD section 12.1).
    """
    profile = _physician_profile(document)
    patient = document.patient

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    story = [Paragraph(title, TITLE_STYLE), Spacer(1, 0.5 * cm)]

    rqe_line = f' — RQE {profile.rqe}' if profile.rqe else ''
    story.append(Paragraph(
        f'{profile.professional_name} — CRM {profile.crm_number}/{profile.crm_state}{rqe_line}',
        LABEL_STYLE,
    ))
    contact_bits = [b for b in [profile.professional_address, profile.professional_phone, profile.professional_email] if b]
    if contact_bits:
        story.append(Paragraph(' | '.join(contact_bits), BODY_STYLE))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5))
    story.append(Spacer(1, 0.3 * cm))

    birth = patient.birth_date.strftime('%d/%m/%Y') if patient.birth_date else 'não informada'
    story.append(Paragraph(f'<b>Paciente:</b> {patient.full_name}', BODY_STYLE))
    story.append(Paragraph(f'<b>Nascimento:</b> {birth}', BODY_STYLE))
    if patient.cpf:
        story.append(Paragraph(f'<b>CPF:</b> {patient.cpf}', BODY_STYLE))
    story.append(Paragraph(f'<b>Data do documento:</b> {document.encounter.occurred_at.strftime("%d/%m/%Y")}', BODY_STYLE))
    doc_number = document.document_number or 'RASCUNHO — sem validade até a emissão'
    story.append(Paragraph(f'<b>Número:</b> {doc_number} (versão {document.version})', BODY_STYLE))
    story.append(Spacer(1, 0.5 * cm))

    story.extend(body_flowables)

    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5))
    story.append(Spacer(1, 0.2 * cm))
    if document.status == 'issued':
        story.append(Paragraph(
            'Documento assinado digitalmente (PAdES) pelo médico emissor. A validade jurídica decorre '
            'da assinatura eletrônica embutida no arquivo, verificável em software compatível.',
            BODY_STYLE,
        ))
    else:
        story.append(Paragraph(
            'RASCUNHO SEM VALIDADE — este documento só é válido após revisão e assinatura digital pelo médico.',
            ParagraphStyle('Warning', parent=BODY_STYLE, textColor='red'),
        ))

    doc.build(story)
    return buf.getvalue()
