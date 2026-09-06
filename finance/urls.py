from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.FinanceOverviewView.as_view(), name='overview'),
    path('<uuid:receivable_id>/', views.ReceivableDetailView.as_view(), name='receivable-detail'),
    path('<uuid:receivable_id>/payments/', views.RecordPaymentView.as_view(), name='record-payment'),
    path('<uuid:receivable_id>/adjustments/', views.ApplyAdjustmentView.as_view(), name='apply-adjustment'),
]
