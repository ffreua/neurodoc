import hashlib
import os
import uuid
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.mfa import mfa_verified_recently

from .credentials import credential_is_usable, decrypt_pfx_bytes
from .models import SigningSession
from .signing import InvalidPfxPassword, verify_pfx_password

ALLOWED_DURATIONS_HOURS = (2, 4, 6, 12)


class RecentMfaRequired(Exception):
    pass


class CredentialNotUsable(Exception):
    pass


class InvalidDuration(Exception):
    pass


class SigningSessionKeyMissing(Exception):
    """The tmpfs ephemeral key is gone -- a reboot or replica restart wiped
    it. The session row may still show as unexpired, but it can never be
    used again; the physician must open a new session.
    """


def _session_binding_hash(request):
    return hashlib.sha256(request.session.session_key.encode()).hexdigest()


def _key_path(ephemeral_key_id):
    return Path(settings.SIGNING_SESSION_KEY_ROOT) / f'{ephemeral_key_id}.key'


@transaction.atomic
def start_session(request, physician_membership, credential, password, duration_hours):
    if not mfa_verified_recently(request):
        raise RecentMfaRequired(
            'Confirme o código do seu aplicativo de autenticação para liberar a assinatura.'
        )
    if duration_hours not in ALLOWED_DURATIONS_HOURS:
        raise InvalidDuration(
            f'A sessão de assinatura dura '
            f'{" ou ".join(str(h) for h in ALLOWED_DURATIONS_HOURS)} horas.'
        )
    if not credential_is_usable(credential):
        raise CredentialNotUsable('Este certificado está revogado, vencido ou ainda não vale.')

    pfx_bytes = decrypt_pfx_bytes(credential)
    try:
        verify_pfx_password(pfx_bytes, password)
    finally:
        del pfx_bytes

    ephemeral_key_id = uuid.uuid4()
    ephemeral_key = Fernet.generate_key()
    key_path = _key_path(ephemeral_key_id)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(ephemeral_key)

    now = timezone.now()
    return SigningSession.objects.create(
        tenant=credential.tenant, physician=physician_membership, credential=credential,
        duration_hours=duration_hours, expires_at=now + timedelta(hours=duration_hours),
        mfa_at=now, session_binding_hash=_session_binding_hash(request),
        encrypted_unlock_material=Fernet(ephemeral_key).encrypt(password.encode()).decode(),
        ephemeral_key_id=ephemeral_key_id,
    )


def get_active_session(request, physician_membership):
    session = SigningSession.objects.filter(
        physician=physician_membership, revoked_at=None, expires_at__gt=timezone.now(),
    ).order_by('-created_at').first()
    if session is None:
        return None
    if session.session_binding_hash != _session_binding_hash(request):
        return None
    return session


def revoke_session(session):
    session.revoked_at = timezone.now()
    session.save(update_fields=['revoked_at'])
    _key_path(session.ephemeral_key_id).unlink(missing_ok=True)
    return session


def unlock_password(session):
    key_path = _key_path(session.ephemeral_key_id)
    if not key_path.exists():
        raise SigningSessionKeyMissing(
            'A sessão de assinatura expirou (o servidor foi reiniciado). '
            'Informe a senha do certificado novamente.'
        )
    ephemeral_key = key_path.read_bytes()
    try:
        return Fernet(ephemeral_key).decrypt(session.encrypted_unlock_material.encode()).decode()
    except InvalidToken as exc:
        raise SigningSessionKeyMissing('A sessão de assinatura não pôde ser aberta. Informe a senha de novo.') from exc


def cleanup_orphan_keys():
    """Removes tmpfs key files with no matching active session row -- run
    every 5 minutes by a host-level timer, never by Celery beat, since the
    worker never mounts this tmpfs (see docker-stack.yml / PRD 8).
    """
    root = Path(settings.SIGNING_SESSION_KEY_ROOT)
    if not root.exists():
        return 0
    active_ids = set(
        str(key_id) for key_id in SigningSession.objects.filter(
            revoked_at=None, expires_at__gt=timezone.now(),
        ).values_list('ephemeral_key_id', flat=True)
    )
    removed = 0
    for key_file in root.glob('*.key'):
        if key_file.stem not in active_ids:
            key_file.unlink(missing_ok=True)
            removed += 1
    return removed
