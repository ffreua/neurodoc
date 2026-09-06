import hashlib

from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event
from events.models import OutboxEvent, OutboxEventStatus

from . import document_kinds
from .credentials import credential_is_usable, decrypt_pfx_bytes
from .models import MedicalDocument, MedicalDocumentStatus
from .pdf import render_medical_document_pdf
from .retention import soft_delete_attachment
from .signing import InvalidPfxPassword, SigningFailed, sign_pdf
from .signing_sessions import SigningSessionKeyMissing, get_active_session, unlock_password
from .storage import open_for_read, store_generated_attachment

DOCUMENT_ISSUED_TOPIC = 'documents.document_issued'


class NotReadyToSign(Exception):
    pass


class SigningNotAuthorized(Exception):
    pass


class MissingPhysicianProfile(Exception):
    pass


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
    document = MedicalDocument.objects.create(
        tenant=tenant, patient=patient, encounter=encounter, physician=physician_membership,
        kind=kind, version=version, replaces_document=replaces_document,
        content_snapshot=dict(content_fields), status=MedicalDocumentStatus.DRAFT,
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
def create_correction(original, actor_id, content_fields):
    if original.status != MedicalDocumentStatus.ISSUED:
        raise NotReadyToSign('Only an issued document can be corrected')
    return create_draft(
        original.tenant, original.patient, original.encounter, original.physician, actor_id,
        original.kind, content_fields, version=original.version + 1, replaces_document=original,
    )


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

    pfx_bytes = decrypt_pfx_bytes(session.credential)
    profile = physician_membership.user.physician_profile
    try:
        with open_for_read(locked.pdf_attachment) as fh:
            draft_bytes = fh.read()
        signed_bytes = sign_pdf(
            draft_bytes, pfx_bytes, password,
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

    locked.document_number = _next_document_number(locked.tenant_id, locked.kind)
    locked.signed_pdf_attachment = store_generated_attachment(
        locked.tenant, locked.patient, physician_membership.user, signed_bytes,
        f'{locked.kind}_{locked.document_number}_signed.pdf', encounter=locked.encounter,
    )
    locked.status = MedicalDocumentStatus.ISSUED
    locked.issued_at = timezone.now()
    locked.signature_metadata = {
        'certificate_serial': session.credential.certificate_serial,
        'certificate_fingerprint': session.credential.certificate_fingerprint,
        'signed_at': locked.issued_at.isoformat(),
        'content_sha256': hashlib.sha256(signed_bytes).hexdigest(),
    }
    locked.save(update_fields=[
        'document_number', 'signed_pdf_attachment', 'status', 'issued_at', 'signature_metadata',
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
