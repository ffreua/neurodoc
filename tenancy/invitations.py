import hashlib
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Invitation, InvitationPurpose
from .plans import DEFAULT_PLAN, PLANS

DEFAULT_TTL_DAYS = 7


def collaborator_invitation_url(request, raw_token):
    return request.build_absolute_uri(reverse('tenancy:accept-invite', args=[raw_token]))


def send_collaborator_invitation(invitation, raw_token, request):
    """Envia o convite sem retirar a opção de copiá-lo na tela."""
    url = collaborator_invitation_url(request, raw_token)
    send_mail(
        subject='Convite para acessar a NeuroDoc',
        message=render_to_string('tenancy/email/collaborator_invitation.txt', {
            'invitation': invitation,
            'url': url,
        }),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invitation.email_binding],
    )
    return url


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def issue_invitation(
    purpose, issued_by=None, target_tenant=None, email_binding='',
    role_grants=None, ttl_days=DEFAULT_TTL_DAYS,
    plan=None, patient_limit_override=None, doctor_limit_override=None,
    plan_note='',
):
    """Emite um convite. O de plataforma carrega o plano contratado.

    `plan` só faz sentido para `purpose='platform'`, que é o que cria uma
    organização nova. Convite de colaborador entra numa clínica que já tem
    plano, e deixá-lo alterar isso seria uma forma silenciosa de mudar
    contrato — por isso os três campos são ignorados nesse caso, em vez de
    aceitos e sem efeito.
    """
    if purpose == InvitationPurpose.COLLABORATOR and target_tenant is None:
        raise ValueError('Collaborator invitations require a target tenant')
    plataforma = purpose == InvitationPurpose.PLATFORM
    if plataforma and plan is not None and plan not in PLANS:
        raise ValueError(f'Plano desconhecido: {plan}')
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        token_hash=hash_token(raw_token),
        purpose=purpose,
        target_tenant=target_tenant,
        email_binding=(email_binding or '').lower(),
        role_grants=role_grants or [],
        expires_at=timezone.now() + timezone.timedelta(days=ttl_days),
        issued_by=issued_by,
        plan=(plan or DEFAULT_PLAN) if plataforma else DEFAULT_PLAN,
        patient_limit_override=patient_limit_override if plataforma else None,
        doctor_limit_override=doctor_limit_override if plataforma else None,
        plan_note=(plan_note or '')[:255] if plataforma else '',
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
