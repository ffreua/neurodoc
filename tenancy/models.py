import re

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from base.models import TenantModel, TimestampedModel
from base.validators import is_valid_cnpj

from .plans import PLANS, PlanCode


SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
RESERVED_SLUGS = {'app', 'admin', 'api', 'static', 'health', 'technical-docs', 'www'}


class Role(models.TextChoices):
    OWNER = 'owner', 'Responsável'
    DOCTOR = 'doctor', 'Médico'
    SECRETARY = 'secretary', 'Secretaria'
    MANAGER = 'manager', 'Gestor'


class TenantStatus(models.TextChoices):
    """Em que pé está a relação comercial com a organização.

    Três estados, porque os dois motivos de desligar uma clínica são
    diferentes e pedem consequências diferentes.

    `SUSPENDED` é a falta de pagamento: a clínica **congela**. Todo mundo
    continua entrando, lendo prontuário, imprimindo e exportando; nada é
    criado nem alterado. É o estado que se desfaz sozinho quando a fatura é
    paga, e é o único compatível com a guarda do prontuário — cortar o
    acesso do médico ao registro dos próprios pacientes por causa de um
    boleto atrasado transformaria uma questão comercial num problema de
    assistência.

    `CLOSED` é a rescisão: ninguém entra mais. O dado **continua no banco**
    — o prontuário tem guarda de vinte anos e não é do sistema decidir
    apagá-lo —, mas a porta fecha, e a tela diz a quem recorrer para pedir
    a exportação.

    Nenhum dos dois apaga nada, nunca. Reativar é trocar o estado de volta.
    """

    ACTIVE = 'active', 'Ativa'
    SUSPENDED = 'suspended', 'Suspensa (somente leitura)'
    CLOSED = 'closed', 'Encerrada'


#: Os estados em que a organização não aceita escrita.
INACTIVE_STATUSES = frozenset({TenantStatus.SUSPENDED, TenantStatus.CLOSED})


class Tenant(TimestampedModel):
    legal_name = models.CharField(max_length=255)
    trade_name = models.CharField(max_length=255, blank=True)
    cnpj = models.CharField(max_length=14, unique=True)
    slug = models.SlugField(max_length=63, unique=True)
    status = models.CharField(max_length=40, choices=TenantStatus.choices, default=TenantStatus.ACTIVE)

    # ------------------------------------------------------------- plano
    #
    # O catálogo vive em `tenancy/plans.py`, em código: um plano é o
    # registro do que foi vendido a alguém, e numa tabela baixar um limite
    # alteraria em silêncio o direito de quem já contratou.
    #
    # O que varia por cliente são os dois *override* abaixo, e não o plano.
    # Nulo significa "usa o plano"; preenchido, vale o valor. É assim que a
    # clínica que negociou 1.200 pacientes continua no Básico em vez de
    # virar um quinto plano — e é assim que a clínica-sede fica irrestrita,
    # como `custom` sem override, e não como uma exceção codificada por
    # e-mail que ninguém vê na tela nem na trilha.
    plan = models.CharField(
        max_length=40, choices=PlanCode.choices, default=PlanCode.FREE,
    )
    patient_limit_override = models.PositiveIntegerField(null=True, blank=True)
    doctor_limit_override = models.PositiveIntegerField(null=True, blank=True)
    #: Por que esta clínica tem o plano e os limites que tem — contrato,
    #: cortesia, piloto. É o que responde à pergunta um ano depois, quando
    #: quem combinou já não lembra e o e-mail se perdeu.
    plan_note = models.CharField(max_length=255, blank=True)

    # ------------------------------------------------- estado comercial
    #
    # Mesma razão do `plan_note`: um estado sem motivo escrito é
    # indistinguível de um erro seis meses depois, e a pergunta que se faz
    # então — "por que esta clínica está suspensa?" — não tem outra fonte.
    #: Por que a organização está no estado em que está. Exigido ao mudar.
    status_note = models.CharField(max_length=255, blank=True)
    #: Quando o estado mudou pela última vez. A trilha guarda o evento
    #: completo; isto existe para a tela poder dizer "suspensa desde"
    #: sem varrer a auditoria a cada linha da listagem.
    status_changed_at = models.DateTimeField(null=True, blank=True)

    timezone = models.CharField(max_length=64, default='America/Sao_Paulo')
    settings = models.JSONField(default=dict, blank=True)

    @property
    def is_active(self):
        return self.status == TenantStatus.ACTIVE

    @property
    def is_read_only(self):
        """Congelada: lê tudo, não escreve nada."""
        return self.status == TenantStatus.SUSPENDED

    @property
    def is_closed(self):
        return self.status == TenantStatus.CLOSED

    def clean(self):
        if not SLUG_RE.fullmatch(self.slug or ''):
            raise ValidationError({'slug': 'Invalid slug format'})
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({'slug': 'Reserved slug'})
        if not is_valid_cnpj(self.cnpj or ''):
            raise ValidationError({'cnpj': 'Invalid CNPJ'})
        if self.plan not in PLANS:
            raise ValidationError({'plan': f'Plano desconhecido: {self.plan}'})

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
    # ---------------------------------------------------- o que foi vendido
    #
    # O convite de plataforma carrega o plano contratado. Antes, todo
    # convite criava a clínica em `free`, com o plano escrito na linha de
    # `accept_platform_invitation` — quem vendesse o Completo teria de
    # corrigir o plano à mão depois, e ninguém saberia dizer se o cliente
    # está no plano certo sem perguntar a quem vendeu.
    #
    # Vale só para `purpose='platform'`: convite de colaborador entra numa
    # clínica que já tem plano, e mudá-lo pela porta do convite seria uma
    # forma silenciosa de alterar contrato.
    plan = models.CharField(
        max_length=40, choices=PlanCode.choices, default=PlanCode.FREE,
    )
    patient_limit_override = models.PositiveIntegerField(null=True, blank=True)
    doctor_limit_override = models.PositiveIntegerField(null=True, blank=True)
    #: Por que este convite tem o plano que tem. Copiado para o
    #: `plan_note` da organização no aceite, que é onde a pergunta é feita
    #: depois — o convite some da vista assim que é consumido.
    plan_note = models.CharField(max_length=255, blank=True)

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


class LeadStatus(models.TextChoices):
    NEW = 'new', 'Novo'
    CONTACTED = 'contacted', 'Contatado'
    CONVERTED = 'converted', 'Convertido'
    DISCARDED = 'discarded', 'Descartado'


class Lead(TimestampedModel):
    """Pedido de contato vindo da pagina publica de vendas.

    Fica em `tenancy` porque um lead e a pre-historia de um inquilino: ele
    vira `Invitation` e depois `Tenant`, e quem o le e quem opera a
    instalacao, no mesmo console. O app `crm` foi removido do produto em
    08/09/2026 (PRD 25.9), e nao se ressuscita um funil inteiro para
    guardar sete campos.

    Herda de `TimestampedModel` e nao de `TenantModel` de proposito: no
    momento em que o pedido chega, a organizacao ainda nao existe -- e
    justamente o que a pessoa esta pedindo.

    Os servicos (limite por IP, aviso por e-mail) ficam em
    `tenancy/leads.py`, como `patients` separa `models.py` de `photo.py`.
    """

    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=32, blank=True)
    clinic_name = models.CharField(max_length=255, blank=True)
    #: Codigo do plano de interesse. `CharField` livre e nao `choices`: o
    #: lead e um retrato do que a pessoa clicou naquele dia, e um plano
    #: aposentado nao pode invalidar um pedido antigo.
    plan = models.CharField(max_length=40, blank=True)
    message = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW)
    #: IP de origem, como no resto do sistema -- serve a investigar abuso,
    #: nao a identificar a pessoa.
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    #: Versao do aviso de privacidade aceita no envio. Demonstrar
    #: consentimento exige saber **a que** se consentiu, e o texto muda.
    privacy_notice_version = models.CharField(max_length=20, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    notify_error = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=['-created_at'], name='tenancy_lead_recent_idx')]

    def __str__(self):
        return f'{self.name} <{self.email}>'
