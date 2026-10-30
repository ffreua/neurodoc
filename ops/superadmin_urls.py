"""Rotas do console do superadministrador, sob `/instalacao/`.

**Fora de `/app/`.** Aquele prefixo significa "dentro de uma clínica":
`TenantMiddleware` resolve a organização corrente ali e devolve 404 a quem
não tem vínculo nenhum — que é exatamente o caso de quem só opera o
servidor. Um console de instalação montado sob `/app/` só funcionaria para
um superadministrador que também fosse funcionário de alguma clínica, o
que é coincidência e não regra.

Mesma sessão, porém: quem entra por `/accounts/login/` chega aqui sem
segundo login. O que exige escrita continua em `/admin/`, para onde estas
telas apontam.
"""
from django.urls import path

from . import superadmin

app_name = 'superadmin'

urlpatterns = [
    path('', superadmin.OverviewView.as_view(), name='overview'),
    path('organizacoes/', superadmin.TenantsView.as_view(), name='tenants'),
    path(
        'organizacoes/<uuid:tenant_id>/plano/',
        superadmin.TenantPlanView.as_view(), name='tenant-plan',
    ),
    path(
        'organizacoes/<uuid:tenant_id>/tiss/',
        superadmin.TenantTissView.as_view(), name='tenant-tiss',
    ),
    path(
        'organizacoes/<uuid:tenant_id>/estado/',
        superadmin.TenantStatusView.as_view(), name='tenant-status',
    ),
    path('convites/', superadmin.InvitationsView.as_view(), name='invitations'),
    path(
        'convites/<uuid:invitation_id>/revogar/',
        superadmin.InvitationRevokeView.as_view(), name='revoke-invitation',
    ),
    path('leads/', superadmin.LeadsView.as_view(), name='leads'),
    path(
        'mensagens/',
        superadmin.ClinicMessagesView.as_view(), name='clinic-messages',
    ),
    path('contratos/', superadmin.ContractsView.as_view(), name='contracts'),
    path('usuarios/', superadmin.UsersView.as_view(), name='users'),
    path('operacao/', superadmin.OperationsView.as_view(), name='operations'),
    path(
        'operacao/provedor-de-ia/',
        superadmin.InstallationAIView.as_view(), name='operations-installation-ai',
    ),
    path(
        'operacao/provedor-de-ia/reserva/',
        superadmin.InstallationAIReserveView.as_view(), name='operations-installation-ai-reserve',
    ),
    path(
        'operacao/ia/',
        superadmin.AIAllowlistView.as_view(), name='operations-ai-allowlist',
    ),
    path(
        'operacao/sncr/',
        superadmin.SncrInstallationView.as_view(), name='operations-sncr',
    ),
    path(
        'operacao/tiss/',
        superadmin.TissInstallationView.as_view(), name='operations-tiss',
    ),
    path(
        'operacao/coleta/',
        superadmin.GarbageCollectionView.as_view(), name='operations-gc',
    ),
    path('auditoria/', superadmin.AuditView.as_view(), name='audit'),
]
