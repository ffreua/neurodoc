from django.urls import path

from . import views

app_name = 'documents'

urlpatterns = [
    path('patients/<uuid:patient_id>/', views.AttachmentListView.as_view(), name='list'),
    path('<uuid:attachment_id>/download/', views.AttachmentDownloadView.as_view(), name='download'),
    path('<uuid:attachment_id>/preview/', views.AttachmentPreviewView.as_view(), name='preview'),
    path('<uuid:attachment_id>/delete/', views.AttachmentDeleteView.as_view(), name='delete'),
]
