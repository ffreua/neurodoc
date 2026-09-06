import hashlib
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import DocumentAccessToken

TOKEN_VALIDITY_DAYS = 7
OTP_VALIDITY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


class OtpExpired(Exception):
    pass


class OtpAttemptsExceeded(Exception):
    pass


class OtpIncorrect(Exception):
    pass


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_access_token(document, contact):
    """The raw token never touches the database -- only its hash does, so a
    read-only DB leak cannot be replayed as a working link, mirroring how
    RecoveryCode/session tokens are handled elsewhere in this project.
    """
    raw_token = secrets.token_urlsafe(32)
    token = DocumentAccessToken.objects.create(
        tenant=document.tenant, document=document, contact=contact,
        token_hash=_hash_token(raw_token), expires_at=timezone.now() + timezone.timedelta(days=TOKEN_VALIDITY_DAYS),
    )
    return token, raw_token


def resolve_token(raw_token):
    token = DocumentAccessToken.objects.filter(token_hash=_hash_token(raw_token)).first()
    if token is None or token.revoked_at is not None or token.expires_at < timezone.now():
        return None
    return token


def request_otp(token):
    raw_otp = f'{secrets.randbelow(10 ** 8):08d}'
    token.otp_hash = make_password(raw_otp)
    token.otp_expires_at = timezone.now() + timezone.timedelta(minutes=OTP_VALIDITY_MINUTES)
    token.otp_attempts = 0
    token.save(update_fields=['otp_hash', 'otp_expires_at', 'otp_attempts'])
    return raw_otp


def verify_otp(token, raw_otp):
    """Each viewing session requires its own freshly requested code -- a
    successful verification clears otp_hash rather than leaving a
    long-lived unlock, so a leaked/guessed code from one session can never
    be replayed for a later one within the link's 7-day window.
    """
    if not token.otp_hash or token.otp_expires_at is None or token.otp_expires_at < timezone.now():
        raise OtpExpired('OTP expired or never requested')
    if token.otp_attempts >= OTP_MAX_ATTEMPTS:
        raise OtpAttemptsExceeded('Too many attempts')
    if not check_password(raw_otp, token.otp_hash):
        token.otp_attempts += 1
        token.save(update_fields=['otp_attempts'])
        raise OtpIncorrect('Incorrect code')
    token.last_access_at = timezone.now()
    token.otp_hash = ''
    token.otp_expires_at = None
    token.save(update_fields=['last_access_at', 'otp_hash', 'otp_expires_at'])
    return True


def revoke_token(token):
    token.revoked_at = timezone.now()
    token.save(update_fields=['revoked_at'])
    return token
