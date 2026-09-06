from django.urls import path

from . import views

app_name = 'patients'

urlpatterns = [
    path('', views.PatientListView.as_view(), name='list'),
    path('new/', views.PatientCreateView.as_view(), name='create'),
    path('autocomplete/', views.PatientAutocompleteView.as_view(), name='autocomplete'),
    path('cep-lookup/', views.CepLookupView.as_view(), name='cep-lookup'),
    path('<uuid:patient_id>/', views.PatientDetailView.as_view(), name='detail'),
    path('<uuid:patient_id>/edit/', views.PatientUpdateView.as_view(), name='update'),
    path('<uuid:patient_id>/archive/', views.PatientArchiveView.as_view(), name='archive'),
    path('<uuid:patient_id>/contacts/', views.PatientContactCreateView.as_view(), name='add-contact'),
    path('<uuid:patient_id>/coverage/', views.PatientCoverageCreateView.as_view(), name='add-coverage'),
]
