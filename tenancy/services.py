import re

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .invitations import consume_invitation
from .models import InvitationPurpose, Membership, MembershipStatus, Role, Tenant


class EmailAlreadyRegistered(Exception):
    pass


def _unique_slug(base_text):
    from .models import RESERVED_SLUGS

    base = slugify(base_text)[:55] or 'clinica'
    candidate = base
    suffix = 1
    while Tenant.objects.filter(slug=candidate).exists() or candidate in RESERVED_SLUGS:
        suffix += 1
        candidate = f'{base}-{suffix}'
    return candidate


class InvalidInvitation(Exception):
    pass


@transaction.atomic
def accept_platform_invitation(token, email, password, legal_name, cnpj, trade_name=''):
    """Consumes a platform invitation and creates org+owner atomically.

    If organization creation fails for any reason (duplicate e-mail,
    invalid CNPJ, ...), the invitation consumption rolls back with it, so a
    failed signup never burns a one-time invite.
    """
    from accounts.models import User

    invitation = consume_invitation(token, consumed_by=None, expected_purpose=InvitationPurpose.PLATFORM)
    if invitation is None:
        raise InvalidInvitation(token)

    email = email.strip().lower()
    if User.objects.filter(email=email).exists():
        raise EmailAlreadyRegistered(email)
    user = User.objects.create_user(email=email, password=password)
    tenant = Tenant(
        legal_name=legal_name,
        trade_name=trade_name,
        cnpj=re.sub(r'\D', '', cnpj),
        slug=_unique_slug(trade_name or legal_name),
        plan='free',
    )
    tenant.full_clean()
    tenant.save()
    membership = Membership.objects.create(
        tenant=tenant, user=user, roles=[Role.OWNER],
        status=MembershipStatus.ACTIVE, activated_at=timezone.now(),
    )
    invitation.consumed_by = user
    invitation.save(update_fields=['consumed_by'])
    return user, tenant, membership


class InvitationEmailMismatch(Exception):
    pass


def _assert_doctor_vacancy(invitation):
    """O convite traz o papel médico? Então a clínica precisa ter vaga.

    A emissão já conferiu (`tenancy/admin_views.py`), e esta é a
    verificação que vale: entre emitir e aceitar cabem sete dias, e a
    última vaga pode ter sido ocupada nesse meio-tempo. Sem ela, o convite
    emitido sob o limite de ontem entraria acima do limite de hoje.
    """
    from .limits import assert_can_add_doctor

    if Role.DOCTOR in (invitation.role_grants or []):
        assert_can_add_doctor(invitation.target_tenant)


@transaction.atomic
def accept_collaborator_invitation_for_user(token, user):
    """Adds a Membership to an already-authenticated user's own account.

    This is the 'vinculação autorizada' path: an existing account gains a
    new tenant relationship, never a duplicate account.
    """
    invitation = consume_invitation(token, consumed_by=user, expected_purpose=InvitationPurpose.COLLABORATOR)
    if invitation is None:
        raise InvalidInvitation(token)
    if invitation.email_binding and invitation.email_binding != user.email:
        raise InvitationEmailMismatch(token)
    _assert_doctor_vacancy(invitation)
    membership, created = Membership.objects.get_or_create(
        tenant=invitation.target_tenant, user=user,
        defaults={
            'roles': invitation.role_grants, 'status': MembershipStatus.ACTIVE,
            'activated_at': timezone.now(), 'invited_by': invitation.issued_by,
        },
    )
    if not created:
        merged_roles = sorted(set(membership.roles) | set(invitation.role_grants))
        membership.roles = merged_roles
        membership.row_version += 1
        membership.save(update_fields=['roles', 'row_version', 'updated_at'])
    return membership


@transaction.atomic
def accept_collaborator_invitation_new_user(token, email, password):
    from accounts.models import User

    invitation = consume_invitation(token, consumed_by=None, expected_purpose=InvitationPurpose.COLLABORATOR)
    if invitation is None:
        raise InvalidInvitation(token)
    email = email.strip().lower()
    if invitation.email_binding and invitation.email_binding != email:
        raise InvitationEmailMismatch(token)
    if User.objects.filter(email=email).exists():
        raise EmailAlreadyRegistered(email)
    _assert_doctor_vacancy(invitation)
    user = User.objects.create_user(email=email, password=password)
    membership = Membership.objects.create(
        tenant=invitation.target_tenant, user=user, roles=invitation.role_grants,
        status=MembershipStatus.ACTIVE, activated_at=timezone.now(), invited_by=invitation.issued_by,
    )
    invitation.consumed_by = user
    invitation.save(update_fields=['consumed_by'])
    return user, membership
