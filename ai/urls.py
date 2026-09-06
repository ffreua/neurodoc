from django.urls import path

from . import views

app_name = 'ai'

urlpatterns = [
    path('encounters/<uuid:encounter_id>/summarize/', views.EncounterSummaryRequestView.as_view(), name='summarize-encounter'),
    path('jobs/<uuid:job_id>/', views.AIJobDetailView.as_view(), name='job-detail'),
    path('artifacts/<uuid:artifact_id>/accept/', views.ArtifactAcceptView.as_view(), name='artifact-accept'),
    path('artifacts/<uuid:artifact_id>/reject/', views.ArtifactRejectView.as_view(), name='artifact-reject'),
]
