from django.urls import path

from . import views

app_name = 'patients'

urlpatterns = [
    path('', views.PatientListView.as_view(), name='list'),
    path('new/', views.PatientCreateView.as_view(), name='create'),
    path('autocomplete/', views.PatientAutocompleteView.as_view(), name='autocomplete'),
    # Busca rápida do topo (Ctrl+K). Separada do autocomplete porque
    # responde outra pergunta: aquele preenche um campo de formulário com
    # o paciente escolhido, esta leva a pessoa até a ficha dele.
    path('busca-rapida/', views.PatientGlobalSearchView.as_view(), name='busca-rapida'),
    path('cep-lookup/', views.CepLookupView.as_view(), name='cep-lookup'),
    path('<uuid:patient_id>/', views.PatientDetailView.as_view(), name='detail'),
    path('<uuid:patient_id>/edit/', views.PatientUpdateView.as_view(), name='update'),
    path('<uuid:patient_id>/archive/', views.PatientArchiveView.as_view(), name='archive'),
    path('<uuid:patient_id>/foto/', views.PatientPhotoView.as_view(), name='photo'),
    # `.img` e nao `.jpg`: o formato guardado varia com o que foi enviado,
    # e uma extensao na rota que mentisse sobre o conteudo seria a primeira
    # coisa a confundir quem depurasse um retrato que nao abre.
    path('<uuid:patient_id>/foto.img', views.PatientPhotoFileView.as_view(), name='photo-file'),
    path('<uuid:patient_id>/contacts/', views.PatientContactCreateView.as_view(), name='add-contact'),
    path(
        '<uuid:patient_id>/contacts/<uuid:contact_id>/edit/',
        views.PatientContactUpdateView.as_view(), name='edit-contact',
    ),
    path('<uuid:patient_id>/coverage/', views.PatientCoverageCreateView.as_view(), name='add-coverage'),
    path(
        '<uuid:patient_id>/medidas/',
        views.PatientMeasurementCreateView.as_view(), name='add-measurement',
    ),
]
