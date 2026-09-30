from django.contrib import admin
from django.urls import include, path
from base.csp_views import CspReportView

from communications.views import UnsubscribeView
from documents.verification import DocumentVerificationView
from ops.docs import technical_docs

urlpatterns = [
    path('admin/dj-control-room-base/', include('dj_control_room_base.urls')),
    path('admin/dj-celery-panel/', include('dj_celery_panel.urls')),
    path('admin/dj-control-room/', include('dj_control_room.urls')),
    path('admin/', admin.site.urls),
    # Console do superadministrador. Fora de `/app/` de propósito: aquele
    # prefixo significa "dentro de uma clínica", e `TenantMiddleware`
    # devolve 404 ali para quem não tem vínculo — que é justamente o caso
    # de quem opera o servidor. Fica ao lado de `/admin/` e
    # `/technical-docs/`, que se protegem sozinhos pela mesma razão.
    path('instalacao/', include('ops.superadmin_urls')),
    path('technical-docs/', technical_docs, name='technical-docs-index'),
    path('technical-docs/<path:path>', technical_docs, name='technical-docs'),
    # Onde o navegador deposita o que a política teria bloqueado. Fora de
    # `/app/` e sem sessão porque é o navegador que manda, sozinho.
    path('csp-report/', CspReportView.as_view(), name='csp-report'),
    path('accounts/', include('accounts.urls')),
    path('', include('tenancy.urls')),
    path('app/patients/', include('patients.urls')),
    path('app/scheduling/', include('scheduling.urls')),
    path('app/clinical/', include('clinical.urls')),
    path('app/documents/', include('documents.urls')),
    path('app/finance/', include('finance.urls')),
    path('app/ai/', include('ai.urls')),
    path('app/codigos/', include('catalogs.urls')),
    path('app/reporting/', include('reporting.urls')),
    path('app/notifications/', include('notifications.urls')),
    path('app/mensagens/', include('teamchat.urls')),
    path('app/org/', include('communications.admin_urls')),
    path('app/org/', include('ai.admin_urls')),
    path('app/org/', include('patients.admin_urls')),
    path('app/org/', include('finance.admin_urls')),
    path('d/', include('communications.urls')),
    # Verificação pública de documento — é o destino do QR impresso na
    # receita. Fica na raiz, e não sob `/app/`, porque quem a abre está na
    # farmácia e não tem conta neste sistema.
    # Descadastro de comunicação em massa — público, um clique, sem conta.
    path('descadastrar/<str:token>/', UnsubscribeView.as_view(), name='marketing-unsubscribe'),
    path('verificar/', DocumentVerificationView.as_view(), name='verify-document'),
    path('verificar/<str:token>/', DocumentVerificationView.as_view(), name='verify-document-token'),
    # Portal de solicitações do paciente — público, por clínica.
    path('solicitacoes/', include('documents.portal_urls')),
    path('', include('base.urls')),
]
