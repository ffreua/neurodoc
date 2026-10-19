from django.urls import path

from . import views

app_name = 'clinical'

urlpatterns = [
    path('cid-lookup/', views.DiagnosisLookupView.as_view(), name='cid-lookup'),
    # Busca de paciente por diagnóstico. Fica sob `/app/clinical/` porque é
    # aí que a exigência de `READ_CLINICAL` vale para a rota inteira.
    path('por-cid/', views.PatientsByDiagnosisView.as_view(), name='por-cid'),
    path('patients/<uuid:patient_id>/timeline/', views.TimelineView.as_view(), name='timeline'),
    # Fragmento do sobreposto de evolução. Carregado sob demanda para que a
    # linha do tempo não pague a varredura de achados e laudos de quem só
    # queria ver a lista de consultas.
    path(
        'patients/<uuid:patient_id>/evolucao/',
        views.PatientEvolutionView.as_view(), name='evolucao',
    ),
    path('patients/<uuid:patient_id>/new/', views.EncounterCreateView.as_view(), name='new'),
    path('<uuid:encounter_id>/', views.EncounterDetailView.as_view(), name='detail'),
    path('<uuid:encounter_id>/resumo/', views.EncounterSummaryView.as_view(), name='summary'),
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
    path(
        '<uuid:encounter_id>/escala/<slug:code>/',
        views.ScaleRecordView.as_view(), name='record-scale',
    ),
    path(
        '<uuid:encounter_id>/achados/<uuid:finding_id>/remover/',
        views.FindingDeleteView.as_view(), name='delete-finding',
    ),
    path('<uuid:encounter_id>/medicacoes/', views.MedicationCreateView.as_view(), name='add-medication'),
    path(
        '<uuid:encounter_id>/medicacoes/<uuid:medication_id>/editar/',
        views.MedicationUpdateView.as_view(), name='update-medication',
    ),
    path(
        '<uuid:encounter_id>/medicacoes/<uuid:medication_id>/remover/',
        views.MedicationDeleteView.as_view(), name='delete-medication',
    ),
    path('<uuid:encounter_id>/exames/', views.ExamResultCreateView.as_view(), name='add-exam-result'),
    path(
        '<uuid:encounter_id>/exames/<uuid:exam_result_id>/remover/',
        views.ExamResultDeleteView.as_view(), name='delete-exam-result',
    ),
    path(
        '<uuid:encounter_id>/exames/<uuid:exam_result_id>/analitos/',
        views.LabValueCreateView.as_view(), name='add-lab-value',
    ),
    path(
        '<uuid:encounter_id>/analitos/<uuid:value_id>/remover/',
        views.LabValueDeleteView.as_view(), name='delete-lab-value',
    ),
    path(
        '<uuid:encounter_id>/exames/<uuid:exam_result_id>/ler-laudo/',
        views.ExamResultExtractView.as_view(), name='extract-exam-result',
    ),
    path(
        '<uuid:encounter_id>/exames/<uuid:exam_result_id>/rascunho/',
        views.ExamResultDraftReviewView.as_view(), name='review-exam-draft',
    ),
    path('<uuid:encounter_id>/diagnoses/', views.DiagnosisCreateView.as_view(), name='add-diagnosis'),
    path(
        '<uuid:encounter_id>/apoio-diagnostico/',
        views.DiagnosticSupportRequestView.as_view(), name='request-diagnostic-support',
    ),
    path(
        '<uuid:encounter_id>/hipoteses/da-ia/',
        views.DiagnosisFromSupportView.as_view(), name='add-diagnosis-from-ai',
    ),
    # Antes da rota com `<uuid:item_id>` nao por ambiguidade -- `aceitar-tudo`
    # nao e UUID e nunca casaria com ela --, mas porque e assim que a lista
    # se le: a acao que vale para todos vem antes da que vale para um.
    path(
        '<uuid:encounter_id>/carry-forward/aceitar-tudo/',
        views.CarryForwardAcceptAllView.as_view(), name='accept-all-carry-forward',
    ),
    path(
        '<uuid:encounter_id>/carry-forward/<uuid:item_id>/review/',
        views.CarryForwardReviewView.as_view(), name='review-carry-forward',
    ),
    path('<uuid:encounter_id>/finalize/', views.FinalizeEncounterView.as_view(), name='finalize'),
    path('<uuid:encounter_id>/descartar/', views.EncounterDiscardView.as_view(), name='discard'),
    path('<uuid:encounter_id>/amendments/', views.AmendmentCreateView.as_view(), name='add-amendment'),
]
