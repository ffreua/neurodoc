import dataclasses
import uuid

from .models import Membership, MembershipStatus, TenantDomain


@dataclasses.dataclass(frozen=True)
class AccessContext:
    """Immutable per-request authorization context.

    ``permissions`` holds the membership's role strings for this request;
    it is rebuilt from the database on every request rather than cached in
    the session, so a revoked/suspended membership stops authorizing new
    requests immediately.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    permissions: frozenset
    request_id: uuid.UUID

    def has_role(self, role):
        return role in self.permissions


def active_membership_for(user, tenant_id):
    if not tenant_id or not getattr(user, 'is_authenticated', False):
        return None
    return (
        Membership.objects
        .filter(tenant_id=tenant_id, user_id=user.id, status=MembershipStatus.ACTIVE)
        .first()
    )


def _hostname_matches_tenant(request, tenant_id):
    hostname = request.get_host().split(':')[0].lower()
    alias = TenantDomain.objects.filter(hostname=hostname).exclude(tenant_id=tenant_id).first()
    return alias is None


def build_access_context(request):
    user = request.user
    if not user.is_authenticated:
        return None
    if user.email_verified_at is None:
        return None
    tenant_id = request.session.get('tenant_id')
    if not tenant_id:
        return None
    membership = active_membership_for(user, tenant_id)
    if membership is None:
        return None
    if not _hostname_matches_tenant(request, membership.tenant_id):
        return None
    return AccessContext(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        membership_id=membership.id,
        permissions=frozenset(membership.roles or []),
        request_id=uuid.uuid4(),
    )
