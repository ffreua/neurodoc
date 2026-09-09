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
    OWNER = 'owner', 'Responsável'
    DOCTOR = 'doctor', 'Médico'
    SECRETARY = 'secretary', 'Secretaria'
    MANAGER = 'manager', 'Gestor'


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
    # Os rótulos são o que a tela da equipe mostra a quem administra a
    # clínica. Os valores gravados continuam em inglês, como no resto do
    # esquema — mudar valor de coluna para traduzir rótulo quebraria todo
    # filtro escrito contra eles.
    INVITED = 'invited', 'Convidado'
    ACTIVE = 'active', 'Ativo'
    SUSPENDED = 'suspended', 'Suspenso'
    REVOKED = 'revoked', 'Revogado'


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


class ClinicProfile(TenantModel):
    """Identidade da clínica: o que aparece no papel timbrado e na tela.

    Separado de `Tenant` porque as duas coisas respondem a perguntas
    diferentes. `Tenant` é quem a organização é perante o sistema — razão
    social, CNPJ, slug, plano, estado da assinatura —, e mexer nisso é ato
    de cadastro. Isto aqui é como a clínica se apresenta ao paciente:
    endereço que sai na receita, telefone que ele liga, logotipo no
    cabeçalho. Muda quando a clínica muda de sala, e não deveria obrigar a
    tocar na linha que identifica a pessoa jurídica.

    O logotipo é guardado como arquivo em `/data/media`, não como coluna
    binária: é o mesmo caminho dos anexos, fica fora do dump do banco e é
    lido direto do disco na hora de montar o PDF.
    """

    #: Caminho absoluto do arquivo. Guardado, e não derivado do id, porque a
    #: extensão depende do formato enviado e o PDF precisa do arquivo real.
    logo_path = models.CharField(max_length=500, blank=True)
    logo_mime = models.CharField(max_length=100, blank=True)
    logo_bytes = models.PositiveIntegerField(default=0)
    logo_updated_at = models.DateTimeField(null=True, blank=True)

    #: Contato que sai no cabeçalho do documento. O endereço do médico
    #: (`accounts.PhysicianProfile`) continua existindo e é outro: numa
    #: clínica com vários médicos, o consultório é um e os CRMs são vários.
    address_line = models.CharField(max_length=255, blank=True)
    address_district = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=2, blank=True)
    postal_code = models.CharField(max_length=9, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    website = models.URLField(max_length=255, blank=True)

    #: Portal público de solicitações do paciente.
    #:
    #: Desligado por padrão, e por clínica. Ligar publica um endereço que
    #: qualquer pessoa alcança e que aceita CPF e data de nascimento — não
    #: é algo que deva existir para uma clínica que não pediu.
    patient_portal_enabled = models.BooleanField(default=False)
    #: Aviso que a clínica quer exibir no portal: prazo de atendimento,
    #: o que o portal não substitui, orientações da primeira consulta.
    #: Fica com a clínica porque o prazo é dela.
    patient_portal_notice = models.TextField(blank=True)

    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant'], name='tenancy_clinicprofile_tenant_uniq'),
        ]

    @property
    def has_logo(self):
        return bool(self.logo_path)

    def address_summary(self):
        """Endereço em uma linha, para o cabeçalho do documento.

        Devolve string vazia quando não há endereço, em vez de uma linha de
        vírgulas soltas: um cabeçalho com ", /" impresso é pior do que um
        cabeçalho sem endereço.
        """
        street = ' — '.join(p for p in [self.address_line, self.address_district] if p)
        place = self.city
        if self.city and self.state:
            place = f'{self.city}/{self.state}'
        return ' — '.join(p for p in [street, place, self.postal_code] if p)

    def __str__(self):
        return f'Identidade de {self.tenant_id}'


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
