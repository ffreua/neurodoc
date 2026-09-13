from django.urls import path

from . import chat_views, sse, views

app_name = 'ai'

urlpatterns = [
    path('encounters/<uuid:encounter_id>/summarize/', views.EncounterSummaryRequestView.as_view(), name='summarize-encounter'),
    path('jobs/<uuid:job_id>/', views.AIJobDetailView.as_view(), name='job-detail'),
    path('artifacts/<uuid:artifact_id>/accept/', views.ArtifactAcceptView.as_view(), name='artifact-accept'),
    path('artifacts/<uuid:artifact_id>/reject/', views.ArtifactRejectView.as_view(), name='artifact-reject'),

    path('chat/', chat_views.ChatSessionListView.as_view(), name='chat-list'),
    path('chat/<uuid:session_id>/', chat_views.ChatSessionDetailView.as_view(), name='chat-session-detail'),
    path('chat/<uuid:session_id>/arquivar/', chat_views.ChatSessionArchiveView.as_view(), name='chat-archive'),
    path('chat/<uuid:session_id>/apagar/', chat_views.ChatSessionDeleteView.as_view(), name='chat-delete'),
    path('chat/<uuid:session_id>/messages/', chat_views.ChatMessageCreateView.as_view(), name='chat-message-create'),
    path(
        'chat/<uuid:session_id>/messages/<uuid:message_id>/cancel/',
        chat_views.ChatMessageCancelView.as_view(), name='chat-message-cancel',
    ),
    path('chat/<uuid:session_id>/stream/<str:job_id>/', sse.chat_stream_view, name='chat-stream'),
]
