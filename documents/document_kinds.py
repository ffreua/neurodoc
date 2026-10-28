from sncr.receita import CAMPOS_DO_FORMULARIO as ITENS_DO_SNCR

from .models import MedicalDocumentKind

NUMBER_PREFIX = {
    MedicalDocumentKind.PRESCRIPTION: 'REC',
    MedicalDocumentKind.REPORT: 'REL',
    MedicalDocumentKind.REQUEST: 'PED',
    MedicalDocumentKind.REFERRAL: 'ENC',
    MedicalDocumentKind.EXAM_REQUEST: 'PEX',
    MedicalDocumentKind.SURGERY_REQUEST: 'CIR',
}

TITLE = {
    MedicalDocumentKind.PRESCRIPTION: 'Receita médica',
    MedicalDocumentKind.REPORT: 'Relatório médico',
    MedicalDocumentKind.REQUEST: 'Pedido de exame/procedimento',
    MedicalDocumentKind.REFERRAL: 'Encaminhamento',
    MedicalDocumentKind.EXAM_REQUEST: 'Pedido de exames',
    MedicalDocumentKind.SURGERY_REQUEST: 'Solicitação de cirurgia',
}

REQUIRED_FIELDS = {
    MedicalDocumentKind.PRESCRIPTION: ('prescription_text',),
    MedicalDocumentKind.REPORT: ('report_text',),
    MedicalDocumentKind.REQUEST: ('requested_procedure', 'justification'),
    MedicalDocumentKind.REFERRAL: ('referral_specialty', 'reason'),
    # Os dois de modelo não têm campo de texto obrigatório: o que eles
    # exigem é uma **lista** não vazia, conferida em `LISTA_OBRIGATORIA`.
    MedicalDocumentKind.EXAM_REQUEST: (),
    MedicalDocumentKind.SURGERY_REQUEST: (),
}

#: A lista que não pode chegar vazia, por tipo. `validate_content` conferia
#: só texto (`.strip()`), e uma lista ali derrubaria a chamada.
LISTA_OBRIGATORIA = {
    MedicalDocumentKind.EXAM_REQUEST: ('itens', 'Inclua ao menos um exame no pedido.'),
    MedicalDocumentKind.SURGERY_REQUEST: ('procedimentos', 'Inclua ao menos um procedimento.'),
}

OPTIONAL_FIELDS = {
    # `prescription_format` decide se a receita sai em uma via ou em duas
    # (controle especial). Opcional porque a receita simples é o padrão e
    # não exige escolha — o valor ausente é lido como simples.
    #
    # Os itens (`item1_nome`...) e a confirmação da classificação só valem
    # para a receita eletrônica do SNCR; `issuance.create_draft` os tira do
    # conteúdo das outras, para a receita impressa não guardar quinze chaves
    # vazias.
    MedicalDocumentKind.PRESCRIPTION: (
        'special_instructions', 'prescription_format', 'classificacao_confirmada', *ITENS_DO_SNCR,
    ),
    MedicalDocumentKind.REPORT: (),
    MedicalDocumentKind.REQUEST: (),
    MedicalDocumentKind.REFERRAL: (),
    MedicalDocumentKind.EXAM_REQUEST: (
        'categoria', 'categoria_rotulo', 'itens', 'indicacao', 'cid', 'observacoes', 'modelo',
    ),
    MedicalDocumentKind.SURGERY_REQUEST: (
        'procedimentos', 'materiais', 'indicacao', 'cid', 'carater', 'regime',
        'dias_internacao', 'anestesia', 'lateralidade', 'uti', 'reserva_sangue', 'local',
        'observacoes', 'modelo',
    ),
}


def all_fields(kind):
    return REQUIRED_FIELDS[kind] + OPTIONAL_FIELDS[kind]


def validate_content(kind, content):
    missing = [f for f in REQUIRED_FIELDS[kind] if not (content.get(f) or '').strip()]
    if missing:
        raise ValueError(
            f'Faltam campos obrigatórios: {", ".join(missing)}.'
        )
    if kind in LISTA_OBRIGATORIA:
        campo, mensagem = LISTA_OBRIGATORIA[kind]
        if not content.get(campo):
            raise ValueError(mensagem)
