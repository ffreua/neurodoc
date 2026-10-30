import dataclasses
import uuid

from .models import Membership, MembershipStatus, TenantDomain, TenantStatus


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
    #: Estado comercial da organização (`TenantStatus`). Vem junto do
    #: contexto porque o vínculo já traz o tenant por `select_related`:
    #: perguntar "esta clínica está congelada?" não deve custar uma
    #: consulta a cada requisição, e muito menos ser esquecido.
    tenant_status: str = TenantStatus.ACTIVE
    #: Capacidades derivadas dos papéis (`tenancy.permissions`). Calculadas
    #: junto com o contexto, uma vez por requisição, e não a cada `if` de
    #: view ou template — a alternativa era consultar o vínculo e o perfil
    #: profissional em cada verificação.
    capabilities: frozenset = dataclasses.field(default_factory=frozenset)

    def has_role(self, role):
        return role in self.permissions

    @property
    def tenant_is_read_only(self):
        """Clínica congelada: lê tudo, não escreve nada.

        Quem responde por isto é o middleware, que recusa método inseguro.
        A propriedade existe para a **tela**: um botão de salvar que só
        falha quando clicado é pior do que botão nenhum.
        """
        return self.tenant_status == TenantStatus.SUSPENDED

    def can(self, capability):
        """Se este vínculo tem a capacidade.

        É o que as views e os templates devem perguntar. Perguntar pelo
        papel espalha a matriz do PRD pelo código e a faz divergir dele.
        """
        return capability in self.capabilities


def active_membership_for(user, tenant_id):
    if not tenant_id or not getattr(user, 'is_authenticated', False):
        return None
    return (
        Membership.objects
        .select_related('tenant')
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
    from .permissions import capabilities_for
    from .plans import has_clinical_ai, has_tiss

    return AccessContext(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        membership_id=membership.id,
        permissions=frozenset(membership.roles or []),
        request_id=uuid.uuid4(),
        tenant_status=membership.tenant.status,
        capabilities=capabilities_for(
            membership.roles, clinically_enabled=membership.can_practice_clinically(),
            # `active_membership_for` ja traz o tenant por `select_related`:
            # ler o plano aqui nao acrescenta consulta a requisicao.
            ai_contracted=has_clinical_ai(membership.tenant.plan),
            # Plano e liberação moram no tenant, já carregado: sem consulta
            # a mais. A terceira chave (a da instalação) é conferida nas
            # telas e tarefas do `tiss`, e não aqui — senão toda tela de
            # `/app/` pagaria uma consulta por um módulo que ela não usa.
            tiss_contracted=(
                has_tiss(membership.tenant.plan) and membership.tenant.tiss_liberado
            ),
        ),
    )
