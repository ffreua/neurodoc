from django.urls import path

from . import views

app_name = 'reporting'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    # Exportacao do acervo. Sob `reporting` porque reaproveita o motor de
    # exportacao inteiro -- fila, expiracao em 24 h, arquivo privado,
    # trilha --, ainda que a porta esteja no menu de administracao.
    path('acervo/', views.AcervoView.as_view(), name='acervo'),
    path('exports/', views.ExportRequestView.as_view(), name='export-request'),
    path('exports/<uuid:export_id>/', views.ExportDetailView.as_view(), name='export-detail'),
    path('exports/<uuid:export_id>/download/', views.ExportDownloadView.as_view(), name='export-download'),
]
