from django.urls import path

from . import views

app_name = 'clinical'

urlpatterns = [
    path('patients/<uuid:patient_id>/timeline/', views.TimelineView.as_view(), name='timeline'),
    path('patients/<uuid:patient_id>/new/', views.EncounterCreateView.as_view(), name='new'),
    path('<uuid:encounter_id>/', views.EncounterDetailView.as_view(), name='detail'),
    path('<uuid:encounter_id>/autosave/', views.EncounterAutosaveView.as_view(), name='autosave'),
    path('<uuid:encounter_id>/findings/', views.FindingUpsertView.as_view(), name='add-finding'),
    path(
        '<uuid:encounter_id>/exam/<slug:axis>/',
        views.ExamAxisSaveView.as_view(), name='save-exam-axis',
    ),
    path(
        '<uuid:encounter_id>/exam-normal/',
        views.ExamGroupNormalView.as_view(), name='exam-group-normal',
    ),
    path('<uuid:encounter_id>/diagnoses/', views.DiagnosisCreateView.as_view(), name='add-diagnosis'),
    path(
        '<uuid:encounter_id>/carry-forward/<uuid:item_id>/review/',
        views.CarryForwardReviewView.as_view(), name='review-carry-forward',
    ),
    path('<uuid:encounter_id>/finalize/', views.FinalizeEncounterView.as_view(), name='finalize'),
    path('<uuid:encounter_id>/amendments/', views.AmendmentCreateView.as_view(), name='add-amendment'),
]
