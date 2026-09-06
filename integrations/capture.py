import hashlib
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from audit.services import record_audit_event

from .models import CaptureDevice, CaptureDeviceStatus, CaptureSession, CaptureSessionStatus

SESSION_TTL_MINUTES = 30


class PairingError(Exception):
    pass


def initiate_pairing(tenant, name, actor_membership):
    """A 6-digit code, single use, shown once on the clinic's own screen
    and typed into the scanning workstation -- never sent over the wire
    unencrypted beyond that local step, and cleared the moment pairing
    completes (see complete_pairing).
    """
    raw_code = f'{secrets.randbelow(10 ** 6):06d}'
    device = CaptureDevice.objects.create(
        tenant=tenant, name=name, paired_by=actor_membership,
        pairing_code_hash=make_password(raw_code), status=CaptureDeviceStatus.PENDING,
    )
    return device, raw_code


def complete_pairing(device, raw_code):
    if device.status != CaptureDeviceStatus.PENDING:
        raise PairingError('Device is not awaiting pairing')
    if not device.pairing_code_hash or not check_password(raw_code, device.pairing_code_hash):
        raise PairingError('Invalid pairing code')
    raw_api_key = secrets.token_urlsafe(32)
    device.api_key_hash = make_password(raw_api_key)
    device.status = CaptureDeviceStatus.PAIRED
    device.paired_at = timezone.now()
    device.pairing_code_hash = ''
    device.save(update_fields=['api_key_hash', 'status', 'paired_at', 'pairing_code_hash'])
    return raw_api_key


def revoke_device(device, actor_id):
    device.status = CaptureDeviceStatus.REVOKED
    device.revoked_at = timezone.now()
    device.api_key_hash = ''
    device.save(update_fields=['status', 'revoked_at', 'api_key_hash'])
    record_audit_event(
        actor_id, device.tenant_id, 'integrations.capture_device_revoked',
        object_type='capture_device', object_id=device.id, outcome='success',
    )
    return device


def resolve_device(tenant, raw_api_key):
    for device in CaptureDevice.objects.filter(tenant=tenant, status=CaptureDeviceStatus.PAIRED):
        if device.api_key_hash and check_password(raw_api_key, device.api_key_hash):
            return device
    return None


def open_session(device, patient, opened_by_membership, encounter=None):
    """The token minted here authorizes uploads into *this* session only --
    a different patient/encounter always needs its own session and its own
    token; the device's own long-lived API key never doubles as an upload
    credential by itself.
    """
    raw_token = secrets.token_urlsafe(32)
    session = CaptureSession.objects.create(
        tenant=device.tenant, device=device, patient=patient, encounter=encounter, opened_by=opened_by_membership,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=timezone.now() + timezone.timedelta(minutes=SESSION_TTL_MINUTES),
    )
    return session, raw_token


def resolve_session(raw_token):
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    session = CaptureSession.objects.filter(token_hash=token_hash, status=CaptureSessionStatus.OPEN).first()
    if session is None:
        return None
    if session.expires_at < timezone.now():
        session.status = CaptureSessionStatus.EXPIRED
        session.save(update_fields=['status'])
        return None
    return session


def close_session(session):
    session.status = CaptureSessionStatus.CLOSED
    session.save(update_fields=['status'])
    return session
