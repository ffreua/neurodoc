from django.urls import path

from . import request_views, views

app_name = 'documents'

urlpatterns = [
    path('patients/<uuid:patient_id>/', views.AttachmentListView.as_view(), name='list'),
    path(
        'patients/<uuid:patient_id>/documentos/',
        views.PatientDocumentsView.as_view(), name='patient-documents',
    ),
    path(
        'patients/<uuid:patient_id>/exames-do-portal/ciente/',
        views.PortalExamAcknowledgeView.as_view(), name='portal-exams-ack',
    ),
    path('<uuid:attachment_id>/download/', views.AttachmentDownloadView.as_view(), name='download'),
    path('<uuid:attachment_id>/preview/', views.AttachmentPreviewView.as_view(), name='preview'),
    path('<uuid:attachment_id>/delete/', views.AttachmentDeleteView.as_view(), name='delete'),

    path('encounters/<uuid:encounter_id>/medical/', views.MedicalDocumentListView.as_view(), name='medical-list'),
    path('encounters/<uuid:encounter_id>/medical/new/', views.MedicalDocumentCreateView.as_view(), name='medical-new'),
    # Emissão a partir da ficha do paciente, sem atendimento — a renovação
    # de receita que se pede por telefone. Ver `PatientDocumentCreateView`.
    path(
        'patients/<uuid:patient_id>/medical/new/',
        views.PatientDocumentCreateView.as_view(), name='patient-medical-new',
    ),
    path(
        'medical/<uuid:document_id>/emitir-em-papel/',
        views.MedicalDocumentIssueOnPaperView.as_view(), name='medical-issue-paper',
    ),
    path(
        'medical/<uuid:document_id>/refazer-impressa/',
        views.MedicalDocumentToPaperView.as_view(), name='medical-to-paper',
    ),
    path('medical/<uuid:document_id>/', views.MedicalDocumentDetailView.as_view(), name='medical-detail'),
    path('medical/<uuid:document_id>/review/', views.MedicalDocumentReviewView.as_view(), name='medical-review'),
    path('medical/<uuid:document_id>/discard/', views.MedicalDocumentDiscardView.as_view(), name='medical-discard'),
    path('medical/<uuid:document_id>/sign/', views.MedicalDocumentSignView.as_view(), name='medical-sign'),
    path(
        'medical/<uuid:document_id>/enviar/',
        views.MedicalDocumentSendView.as_view(), name='medical-send',
    ),
    path(
        'medical/<uuid:document_id>/correction/',
        views.MedicalDocumentCorrectionView.as_view(), name='medical-correction',
    ),

    path('solicitacoes/', request_views.DocumentRequestQueueView.as_view(), name='request-queue'),
    path(
        'solicitacoes/<uuid:request_id>/',
        request_views.DocumentRequestDetailView.as_view(), name='request-detail',
    ),
    path(
        'solicitacoes/<uuid:request_id>/<str:action>/',
        request_views.DocumentRequestActionView.as_view(), name='request-action',
    ),

    path('signing/credentials/', views.SigningCredentialListView.as_view(), name='credential-list'),
    path('signing/credentials/upload/', views.SigningCredentialUploadView.as_view(), name='credential-upload'),
    path(
        'signing/credentials/<uuid:credential_id>/revoke/',
        views.SigningCredentialRevokeView.as_view(), name='credential-revoke',
    ),
    path('signing/sessions/start/', views.SigningSessionStartView.as_view(), name='session-start'),
    path(
        'signing/sessions/<uuid:session_id>/revoke/',
        views.SigningSessionRevokeView.as_view(), name='session-revoke',
    ),
]
