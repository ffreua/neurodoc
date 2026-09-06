from .models import MedicalDocumentKind

NUMBER_PREFIX = {
    MedicalDocumentKind.PRESCRIPTION: 'REC',
    MedicalDocumentKind.REPORT: 'REL',
    MedicalDocumentKind.REQUEST: 'PED',
    MedicalDocumentKind.REFERRAL: 'ENC',
}

TITLE = {
    MedicalDocumentKind.PRESCRIPTION: 'Receita médica',
    MedicalDocumentKind.REPORT: 'Relatório médico',
    MedicalDocumentKind.REQUEST: 'Pedido de exame/procedimento',
    MedicalDocumentKind.REFERRAL: 'Encaminhamento',
}

REQUIRED_FIELDS = {
    MedicalDocumentKind.PRESCRIPTION: ('prescription_text',),
    MedicalDocumentKind.REPORT: ('report_text',),
    MedicalDocumentKind.REQUEST: ('requested_procedure', 'justification'),
    MedicalDocumentKind.REFERRAL: ('referral_specialty', 'reason'),
}

OPTIONAL_FIELDS = {
    MedicalDocumentKind.PRESCRIPTION: ('special_instructions',),
    MedicalDocumentKind.REPORT: (),
    MedicalDocumentKind.REQUEST: (),
    MedicalDocumentKind.REFERRAL: (),
}


def all_fields(kind):
    return REQUIRED_FIELDS[kind] + OPTIONAL_FIELDS[kind]


def validate_content(kind, content):
    missing = [f for f in REQUIRED_FIELDS[kind] if not (content.get(f) or '').strip()]
    if missing:
        raise ValueError(f'Missing required fields for {kind}: {", ".join(missing)}')
