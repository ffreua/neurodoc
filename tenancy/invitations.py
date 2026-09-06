import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from .models import Invitation, InvitationPurpose

DEFAULT_TTL_DAYS = 7


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def issue_invitation(
    purpose, issued_by=None, target_tenant=None, email_binding='',
    role_grants=None, ttl_days=DEFAULT_TTL_DAYS,
):
    if purpose == InvitationPurpose.COLLABORATOR and target_tenant is None:
        raise ValueError('Collaborator invitations require a target tenant')
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        token_hash=hash_token(raw_token),
        purpose=purpose,
        target_tenant=target_tenant,
        email_binding=(email_binding or '').lower(),
        role_grants=role_grants or [],
        expires_at=timezone.now() + timezone.timedelta(days=ttl_days),
        issued_by=issued_by,
    )
    return invitation, raw_token


def peek_invitation(raw_token):
    """Read-only lookup for rendering a form; never consumes the invitation."""
    invitation = Invitation.objects.filter(token_hash=hash_token(raw_token)).first()
    if invitation is None or not invitation.is_usable(timezone.now()):
        return None
    return invitation


@transaction.atomic
def consume_invitation(raw_token, consumed_by, expected_purpose=None):
    """Locks and consumes the invitation atomically.

    Concurrent callers racing on the same raw token serialize on the row
    lock; only the first to observe consumed_at=None succeeds.
    """
    invitation = (
        Invitation.objects
        .select_for_update()
        .filter(token_hash=hash_token(raw_token))
        .first()
    )
    if invitation is None or not invitation.is_usable(timezone.now()):
        return None
    if expected_purpose is not None and invitation.purpose != expected_purpose:
        return None
    invitation.consumed_at = timezone.now()
    invitation.consumed_by = consumed_by
    invitation.save(update_fields=['consumed_at', 'consumed_by', 'updated_at'])
    return invitation
