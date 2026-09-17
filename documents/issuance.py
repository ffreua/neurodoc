import hashlib
import secrets

from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event
from events.models import OutboxEvent, OutboxEventStatus

from . import document_kinds
from .credentials import credential_is_usable, decrypt_pfx_bytes
from .models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from .pdf import render_medical_document_pdf
from .retention import soft_delete_attachment
from .signing import InvalidPfxPassword, SigningFailed, sign_pdf
from .signing_sessions import SigningSessionKeyMissing, get_active_session, unlock_password
from .storage import store_generated_attachment

DOCUMENT_ISSUED_TOPIC = 'documents.document_issued'


class NotReadyToSign(Exception):
    pass


class SigningNotAuthorized(Exception):
    pass


class MissingPhysicianProfile(Exception):
    pass


def _validate_special_control(kind, content_fields, patient):
    """Receita de controle especial exige endereço completo do paciente.

    A recusa acontece aqui, na criação do rascunho, e não na impressão: a
    farmácia devolve a receita de controle especial sem endereço, e
    descobrir isso com o paciente no balcão significa que ele volta ao
    consultório. Barrar antes de assinar é o único momento em que corrigir
    ainda é barato.

    Portaria SVS/MS 344/98 e sua regulamentação (Portaria 6/99, anexo XVII):
    a 1ª via fica retida na farmácia e precisa identificar o comprador.
    """
    from .pdf.prescription import SPECIAL_CONTROL

    if kind != MedicalDocumentKind.PRESCRIPTION:
        return
    if (content_fields.get('prescription_format') or '') != SPECIAL_CONTROL:
        return
    if not (patient.street and patient.city and patient.state):
        raise ValueError(
            'A receita de controle especial exige o endereço completo do paciente '
            '(logradouro, município e UF). Complete o cadastro antes de emitir, '
            'ou use a receita simples.'
        )


def _as_issued(document):
    """O documento com estado `issued` **só em memória**, para desenhar.

    O PDF final precisa sair sem a tarja de rascunho e com a data de
    emissão, mas gravar `status=issued` antes de a assinatura existir
    deixaria, se a assinatura falhasse, um documento marcado como emitido
    sem arquivo assinado nenhum. O objeto real segue em `signing` até o
    fim; o que muda aqui é uma cópia que só o desenho enxerga.
    """
    document.status = MedicalDocumentStatus.ISSUED
    return document


def _as_paper(document):
    """Cópia em memória marcada como emitida no papel, só para desenhar.

    Mesma razão de `_as_issued`: o estado real só muda depois de o arquivo
    existir.
    """
    document.status = MedicalDocumentStatus.ISSUED_ON_PAPER
    return document


@transaction.atomic
def issue_on_paper(document, actor_id):
    """Emite para ser assinado à caneta e carimbado.

    É o caminho de quem não usa certificado digital, ou de quem está sem
    ele naquele dia. O documento ganha número e data como qualquer outro, e
    o PDF sai **sem** a tarja de rascunho e **sem** QR — ver
    `MedicalDocumentStatus.ISSUED_ON_PAPER` e `pdf/common._qr_flowable`.

    Sem `SELECT ... FOR UPDATE` seria possível emitir duas vezes em duas
    abas e gastar dois números de documento para a mesma receita; o
    `select_for_update` fecha isso, como no caminho da assinatura digital.
    """
    locked = MedicalDocument.objects.select_for_update().get(pk=document.pk)
    if locked.status not in (MedicalDocumentStatus.DRAFT, MedicalDocumentStatus.READY_TO_SIGN):
        raise ValueError('Só um rascunho ou documento pronto para assinar pode ser emitido em papel.')
    locked.document_number = _next_document_number(locked.tenant_id, locked.kind)
    locked.issued_at = timezone.now()
    pdf_bytes = render_medical_document_pdf(_as_paper(locked))
    locked.status = MedicalDocumentStatus.ISSUED_ON_PAPER
    locked.pdf_attachment = store_generated_attachment(
        locked.tenant, locked.patient, locked.physician.user, pdf_bytes,
        f'{locked.kind}_{locked.id}_papel.pdf', encounter=locked.encounter,
    )
    locked.save(update_fields=['document_number', 'issued_at', 'status', 'pdf_attachment'])
    record_audit_event(
        actor_id, locked.tenant_id, 'documents.medicaldocument_issued_on_paper',
        object_type='medical_document', object_id=locked.id, outcome='success',
        purpose='Emitido para assinatura de proprio punho',
    )
    return locked


def new_validation_token():
    """Código do QR e da página pública de verificação.

    16 caracteres hexadecimais — 64 bits — porque ele é a única coisa que
    protege a página de verificação: quem tiver o código vê os metadados
    daquele documento. Curto o bastante para caber impresso e para alguém
    digitar quando o QR não lê; longo o bastante para não se descobrir um
    código por tentativa.

    Aleatório, e nunca derivado do número do documento: uma sequência no QR
    permitiria, a partir da própria receita, montar o código da receita
    seguinte e consultar o documento de outro paciente.
    """
    return secrets.token_hex(8).upper()


def _lock_document_number(tenant_id, year):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
            [f'medicaldocument_number:{tenant_id}:{year}'],
        )


@transaction.atomic
def _next_document_number(tenant_id, kind):
    year = timezone.now().year
    _lock_document_number(tenant_id, year)
    prefix = document_kinds.NUMBER_PREFIX[kind]
    count = MedicalDocument.objects.filter(
        tenant_id=tenant_id, document_number__startswith=f'{prefix}-{year}-',
    ).count()
    return f'{prefix}-{year}-{count + 1:06d}'


@transaction.atomic
def create_draft(tenant, patient, encounter, physician_membership, actor_id, kind, content_fields,
                  version=1, replaces_document=None):
    from accounts.models import PhysicianProfile

    if not PhysicianProfile.objects.filter(user_id=physician_membership.user_id).exists():
        raise MissingPhysicianProfile('Physician membership has no PhysicianProfile (CRM/RQE) on file')
    document_kinds.validate_content(kind, content_fields)
    _validate_special_control(kind, content_fields, patient)
    document = MedicalDocument.objects.create(
        tenant=tenant, patient=patient, encounter=encounter, physician=physician_membership,
        kind=kind, version=version, replaces_document=replaces_document,
        content_snapshot=dict(content_fields), status=MedicalDocumentStatus.DRAFT,
        validation_token=new_validation_token(),
    )
    pdf_bytes = render_medical_document_pdf(document)
    document.pdf_attachment = store_generated_attachment(
        tenant, patient, physician_membership.user, pdf_bytes,
        f'{kind}_{document.id}_draft.pdf', encounter=encounter,
    )
    document.save(update_fields=['pdf_attachment'])
    record_audit_event(
        actor_id, tenant.id, 'documents.medicaldocument_created',
        object_type='medical_document', object_id=document.id, outcome='success',
    )
    return document


@transaction.atomic
def create_correction(original, actor_id, content_fields, reason=''):
    if original.status != MedicalDocumentStatus.ISSUED:
        raise NotReadyToSign('Only an issued document can be corrected')
    corrected = create_draft(
        original.tenant, original.patient, original.encounter, original.physician, actor_id,
        original.kind, content_fields, version=original.version + 1, replaces_document=original,
    )
    # O motivo vai para a trilha, e não para o documento.
    #
    # A tela pedia o motivo da correção e o descartava: o campo tinha o
    # mesmo nome do "Motivo" do encaminhamento e, nos demais tipos, não
    # existia no conteúdo — o médico escrevia e nada era guardado. O motivo
    # de uma retificação é registro de quem alterou o quê e por quê, e é na
    # auditoria que ele responde a isso, não no papel entregue ao paciente.
    record_audit_event(
        actor_id, original.tenant_id, 'documents.medicaldocument_corrected',
        object_type='medical_document', object_id=corrected.id, outcome='success',
        purpose=(reason or '')[:255],
        integrity_metadata={
            'replaces': str(original.id),
            'replaces_number': original.document_number,
            'version': corrected.version,
        },
    )
    return corrected


def mark_reviewed(document, actor_id):
    if document.status != MedicalDocumentStatus.DRAFT:
        raise NotReadyToSign('Document is not in draft status')
    document.status = MedicalDocumentStatus.READY_TO_SIGN
    document.save(update_fields=['status'])
    record_audit_event(
        actor_id, document.tenant_id, 'documents.medicaldocument_reviewed',
        object_type='medical_document', object_id=document.id, outcome='success',
    )
    return document


def discard_document(document, actor_id):
    if document.status not in (MedicalDocumentStatus.DRAFT, MedicalDocumentStatus.READY_TO_SIGN, MedicalDocumentStatus.FAILED):
        raise NotReadyToSign('Only a non-issued document can be discarded')
    if document.pdf_attachment_id:
        soft_delete_attachment(document.pdf_attachment, actor_id, 'medical document discarded')
    record_audit_event(
        actor_id, document.tenant_id, 'documents.medicaldocument_discarded',
        object_type='medical_document', object_id=document.id, outcome='success',
    )
    document.delete()


@transaction.atomic
def sign_and_issue(document, request, physician_membership):
    """Enforces the full authorization chain per document, per PRD 12.2:
    active signing session bound to *this* web session, a still-usable
    credential, and the ephemeral tmpfs key actually present. Any failure
    leaves the document not-issued -- recoverable failures (bad password,
    expired/revoked credential, missing session) return it to
    ready_to_sign for a retry; only an unexpected signing exception moves
    it to the terminal `failed` state.
    """
    locked = MedicalDocument.objects.select_for_update().get(id=document.id)
    if locked.status != MedicalDocumentStatus.READY_TO_SIGN:
        raise NotReadyToSign('Document is not ready to sign')
    if locked.physician_id != physician_membership.id:
        raise SigningNotAuthorized('Document belongs to a different physician')

    session = get_active_session(request, physician_membership)
    if session is None:
        raise SigningNotAuthorized('No active signing session bound to this web session')
    if not credential_is_usable(session.credential):
        raise SigningNotAuthorized('Credential is revoked, expired, or not yet valid')

    try:
        password = unlock_password(session)
    except SigningSessionKeyMissing as exc:
        record_audit_event(
            physician_membership.user_id, locked.tenant_id, 'documents.medicaldocument_sign_failed',
            object_type='medical_document', object_id=locked.id, outcome='denied',
            integrity_metadata={'reason': 'signing_session_key_missing'},
        )
        raise SigningNotAuthorized(str(exc)) from exc

    locked.status = MedicalDocumentStatus.SIGNING
    locked.save(update_fields=['status'])

    # O PDF assinado é montado **agora**, e não é o rascunho.
    #
    # Antes se assinava o arquivo gerado na criação do rascunho, e aquele
    # arquivo trazia impresso "RASCUNHO SEM VALIDADE — só vale depois de
    # revisado e assinado" e, no lugar do número, "RASCUNHO — sem validade
    # até a emissão". O documento saía assinado dizendo de si mesmo que não
    # valia — e o número, que só é atribuído aqui, nunca chegava ao papel.
    #
    # A ordem tem de ser esta: número, estado, então desenhar, então
    # assinar. Assinar primeiro e carimbar depois invalidaria a assinatura,
    # que cobre os bytes do arquivo inteiro.
    locked.document_number = _next_document_number(locked.tenant_id, locked.kind)
    locked.issued_at = timezone.now()
    if not locked.validation_token:
        # Documento criado antes de o código de verificação existir.
        locked.validation_token = new_validation_token()
    final_pdf = render_medical_document_pdf(_as_issued(locked))

    pfx_bytes = decrypt_pfx_bytes(session.credential)
    profile = physician_membership.user.physician_profile
    try:
        signed_bytes = sign_pdf(
            final_pdf, pfx_bytes, password,
            signer_name=profile.professional_name,
            reason=f'{document_kinds.TITLE[locked.kind]} — CRM {profile.crm_number}/{profile.crm_state}',
        )
    except InvalidPfxPassword as exc:
        locked.status = MedicalDocumentStatus.READY_TO_SIGN
        locked.save(update_fields=['status'])
        record_audit_event(
            physician_membership.user_id, locked.tenant_id, 'documents.medicaldocument_sign_failed',
            object_type='medical_document', object_id=locked.id, outcome='denied',
            integrity_metadata={'reason': 'invalid_pfx_password'},
        )
        raise SigningNotAuthorized(str(exc)) from exc
    except SigningFailed as exc:
        locked.status = MedicalDocumentStatus.FAILED
        locked.save(update_fields=['status'])
        record_audit_event(
            physician_membership.user_id, locked.tenant_id, 'documents.medicaldocument_sign_failed',
            object_type='medical_document', object_id=locked.id, outcome='failure',
            integrity_metadata={'reason': 'signing_exception'},
        )
        raise
    finally:
        del pfx_bytes

    locked.signed_pdf_attachment = store_generated_attachment(
        locked.tenant, locked.patient, physician_membership.user, signed_bytes,
        f'{locked.kind}_{locked.document_number}_signed.pdf', encounter=locked.encounter,
    )
    locked.status = MedicalDocumentStatus.ISSUED
    locked.signature_metadata = {
        'certificate_serial': session.credential.certificate_serial,
        'certificate_fingerprint': session.credential.certificate_fingerprint,
        'signed_at': locked.issued_at.isoformat(),
        # Impressão digital do arquivo **assinado**, que é o que a página de
        # verificação compara. O rodapé do PDF mostra o começo dela; o
        # arquivo em si não pode conter o próprio hash inteiro, porque
        # escrevê-lo mudaria o hash.
        'content_sha256': hashlib.sha256(signed_bytes).hexdigest(),
    }
    locked.save(update_fields=[
        'document_number', 'signed_pdf_attachment', 'status', 'issued_at',
        'signature_metadata', 'validation_token',
    ])

    OutboxEvent.objects.get_or_create(
        tenant_id=locked.tenant_id, topic=DOCUMENT_ISSUED_TOPIC, aggregate_type='medical_document',
        aggregate_id=locked.id, event_version=locked.version,
        defaults={
            'payload_minimal': {'medical_document_id': str(locked.id), 'patient_id': str(locked.patient_id)},
            'available_at': timezone.now(),
            'status': OutboxEventStatus.PENDING,
        },
    )
    record_audit_event(
        physician_membership.user_id, locked.tenant_id, 'documents.medicaldocument_signed',
        object_type='medical_document', object_id=locked.id, outcome='success',
    )
    return locked
