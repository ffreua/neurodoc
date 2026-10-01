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
    # `prescription_format` decide se a receita sai em uma via ou em duas
    # (controle especial). Opcional porque a receita simples é o padrão e
    # não exige escolha — o valor ausente é lido como simples.
    MedicalDocumentKind.PRESCRIPTION: ('special_instructions', 'prescription_format'),
    MedicalDocumentKind.REPORT: (),
    MedicalDocumentKind.REQUEST: (),
    MedicalDocumentKind.REFERRAL: (),
}


def all_fields(kind):
    return REQUIRED_FIELDS[kind] + OPTIONAL_FIELDS[kind]


def validate_content(kind, content):
    missing = [f for f in REQUIRED_FIELDS[kind] if not (content.get(f) or '').strip()]
    if missing:
        raise ValueError(
            f'Faltam campos obrigatórios: {", ".join(missing)}.'
        )
