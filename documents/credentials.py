import os
import unicodedata
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import SigningCredential, SigningCredentialStatus


class InvalidPfxFile(Exception):
    pass


class CredentialTitleMismatch(Exception):
    pass


def _normalize(text):
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).strip().casefold()


def _credential_dir(tenant_id):
    path = Path(settings.PFX_ROOT) / str(tenant_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_pkcs12(pfx_bytes, password):
    try:
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            pfx_bytes, password.encode(),
        )
    except Exception as exc:
        raise InvalidPfxFile(str(exc)) from exc
    if private_key is None or certificate is None:
        raise InvalidPfxFile('PKCS#12 archive is missing a private key or certificate')
    return private_key, certificate


def _check_title_holder(certificate, professional_name):
    subject_cn = certificate.subject.rfc4514_string()
    if _normalize(professional_name) not in _normalize(subject_cn) and \
            not any(_normalize(part) in _normalize(subject_cn) for part in professional_name.split()):
        raise CredentialTitleMismatch(
            f'Certificate subject ({subject_cn}) does not appear to match physician name ({professional_name})',
        )


@transaction.atomic
def upload_credential(tenant, physician_membership, pfx_bytes, password):
    """Validates a PFX archive, checks the certificate against the
    physician's registered name (a heuristic stand-in for a real ICP-Brasil
    identity/chain validation, unresolved per P-05), and stores it with
    envelope encryption: a random per-credential data key encrypts the PFX
    bytes, and only that data key -- never the PFX itself -- is wrapped with
    the master key. This lets the master key rotate by re-wrapping data keys
    without touching the (much larger) encrypted archives.
    """
    private_key, certificate = _load_pkcs12(pfx_bytes, password)
    professional_name = physician_membership.user.physician_profile.professional_name
    _check_title_holder(certificate, professional_name)

    data_key = Fernet.generate_key()
    ciphertext = Fernet(data_key).encrypt(pfx_bytes)
    wrapped_key = Fernet(settings.PFX_MASTER_KEY.encode()).encrypt(data_key)

    credential_id = uuid.uuid4()
    path = _credential_dir(tenant.id) / f'{credential_id}.pfx.enc'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(ciphertext)

    return SigningCredential.objects.create(
        id=credential_id, tenant=tenant, physician=physician_membership, ciphertext_path=str(path),
        wrapped_key_metadata={'wrapped_key': wrapped_key.decode()},
        certificate_serial=format(certificate.serial_number, 'x'),
        certificate_fingerprint=certificate.fingerprint(hashes.SHA256()).hex(),
        issuer=certificate.issuer.rfc4514_string(),
        not_before=certificate.not_valid_before_utc,
        not_after=certificate.not_valid_after_utc,
    )


def decrypt_pfx_bytes(credential):
    wrapped_key = credential.wrapped_key_metadata['wrapped_key'].encode()
    data_key = Fernet(settings.PFX_MASTER_KEY.encode()).decrypt(wrapped_key)
    ciphertext = Path(credential.ciphertext_path).read_bytes()
    return Fernet(data_key).decrypt(ciphertext)


def revoke_credential(credential):
    credential.status = SigningCredentialStatus.REVOKED
    credential.save(update_fields=['status'])
    return credential


def credential_is_usable(credential, at=None):
    at = at or timezone.now()
    return (
        credential.status == SigningCredentialStatus.ACTIVE
        and credential.not_before <= at <= credential.not_after
    )
