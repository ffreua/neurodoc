from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.FinanceOverviewView.as_view(), name='overview'),
    path('export/competence.csv', views.CompetenceExportView.as_view(), name='export-competence'),
    path('export/cash.csv', views.CashExportView.as_view(), name='export-cash'),
    path('history/', views.FinancialHistoryView.as_view(), name='history'),
    path('history/archive/', views.ArchiveFinancialHistoryView.as_view(), name='archive-history'),
    path('history/restore/', views.RestoreFinancialHistoryView.as_view(), name='restore-history'),
    path('history/delete/', views.DeleteFinancialHistoryView.as_view(), name='delete-history'),
    path('<uuid:receivable_id>/', views.ReceivableDetailView.as_view(), name='receivable-detail'),
    path(
        '<uuid:receivable_id>/fiscal-document/',
        views.FiscalDocumentUpdateView.as_view(), name='update-fiscal-document',
    ),
    path(
        '<uuid:receivable_id>/doctor-share/mark/',
        views.MarkDoctorSharePaidView.as_view(), name='mark-doctor-share-paid',
    ),
    path(
        '<uuid:receivable_id>/doctor-share/undo/',
        views.UndoDoctorSharePaidView.as_view(), name='undo-doctor-share-paid',
    ),
    path('<uuid:receivable_id>/payments/', views.RecordPaymentView.as_view(), name='record-payment'),
    path('<uuid:receivable_id>/adjustments/', views.ApplyAdjustmentView.as_view(), name='apply-adjustment'),
]
