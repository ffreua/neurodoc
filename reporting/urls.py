from django.urls import path

from . import views

app_name = 'reporting'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('exports/', views.ExportRequestView.as_view(), name='export-request'),
    path('exports/<uuid:export_id>/', views.ExportDetailView.as_view(), name='export-detail'),
    path('exports/<uuid:export_id>/download/', views.ExportDownloadView.as_view(), name='export-download'),
]
