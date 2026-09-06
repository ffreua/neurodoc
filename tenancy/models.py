import re

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from base.models import TenantModel, TimestampedModel
from base.validators import is_valid_cnpj


SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
RESERVED_SLUGS = {'app', 'admin', 'api', 'static', 'health', 'technical-docs', 'www'}


class Role(models.TextChoices):
    OWNER = 'owner', 'Owner'
    DOCTOR = 'doctor', 'Doctor'
    SECRETARY = 'secretary', 'Secretary'
    MANAGER = 'manager', 'Manager'


class TenantStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    SUSPENDED = 'suspended', 'Suspended'


class Tenant(TimestampedModel):
    legal_name = models.CharField(max_length=255)
    trade_name = models.CharField(max_length=255, blank=True)
    cnpj = models.CharField(max_length=14, unique=True)
    slug = models.SlugField(max_length=63, unique=True)
    status = models.CharField(max_length=40, choices=TenantStatus.choices, default=TenantStatus.ACTIVE)
    plan = models.CharField(max_length=40, default='free')
    timezone = models.CharField(max_length=64, default='America/Sao_Paulo')
    settings = models.JSONField(default=dict, blank=True)

    def clean(self):
        if not SLUG_RE.fullmatch(self.slug or ''):
            raise ValidationError({'slug': 'Invalid slug format'})
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({'slug': 'Reserved slug'})
        if not is_valid_cnpj(self.cnpj or ''):
            raise ValidationError({'cnpj': 'Invalid CNPJ'})

    def __str__(self):
        return self.legal_name


class TenantDomain(TimestampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='domains')
    hostname = models.CharField(max_length=255)
    verified_at = models.DateTimeField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('hostname'), name='tenancy_tenantdomain_hostname_lower_uniq'),
        ]

    def clean(self):
        self.hostname = (self.hostname or '').lower().strip()

    def __str__(self):
        return self.hostname


class MembershipStatus(models.TextChoices):
    INVITED = 'invited', 'Invited'
    ACTIVE = 'active', 'Active'
    SUSPENDED = 'suspended', 'Suspended'
    REVOKED = 'revoked', 'Revoked'


class Membership(TenantModel):
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='memberships')
    roles = ArrayField(models.CharField(max_length=40, choices=Role.choices), default=list, blank=True)
    status = models.CharField(max_length=40, choices=MembershipStatus.choices, default=MembershipStatus.INVITED)
    invited_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'user'], name='tenancy_membership_tenant_user_uniq'),
        ]

    def has_role(self, role):
        return role in (self.roles or [])

    def is_active(self):
        return self.status == MembershipStatus.ACTIVE

    def can_practice_clinically(self):
        """A granted 'doctor' role is not automatic clinical enablement.

        A verified PhysicianProfile is a separate, explicit gate — owners
        cannot self-serve medical capability just by assigning the role.
        """
        if not self.has_role(Role.DOCTOR):
            return False
        from accounts.models import PhysicianProfile
        profile = PhysicianProfile.objects.filter(user_id=self.user_id).first()
        return bool(profile and profile.verification_status == profile.VerificationStatus.VERIFIED)

    def __str__(self):
        return f'{self.user_id}@{self.tenant_id}'


class InvitationPurpose(models.TextChoices):
    PLATFORM = 'platform', 'Platform'
    COLLABORATOR = 'collaborator', 'Collaborator'


class Invitation(TimestampedModel):
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=40, choices=InvitationPurpose.choices)
    target_tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name='invitations',
    )
    email_binding = models.EmailField(max_length=254, blank=True)
    role_grants = ArrayField(
        models.CharField(max_length=40, choices=Role.choices), default=list, blank=True,
    )
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(purpose='platform') | ~models.Q(target_tenant=None),
                name='tenancy_invitation_collaborator_requires_target_tenant',
            ),
        ]

    def is_usable(self, now):
        return self.consumed_at is None and self.revoked_at is None and self.expires_at > now

    def __str__(self):
        return f'{self.purpose} invitation ({self.id})'
