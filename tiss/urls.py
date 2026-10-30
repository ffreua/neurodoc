from django.urls import path

from . import views

app_name = 'tiss'

urlpatterns = [
    path('', views.InicioView.as_view(), name='inicio'),
    path('prestadores/novo/', views.PrestadorView.as_view(), name='prestador-novo'),
    path('prestadores/<uuid:pk>/', views.PrestadorView.as_view(), name='prestador'),
    path('credenciamentos/novo/', views.CredenciamentoView.as_view(), name='credenciamento-novo'),
    path('credenciamentos/<uuid:pk>/', views.CredenciamentoView.as_view(), name='credenciamento'),
    path('profissionais/novo/', views.ProfissionalView.as_view(), name='profissional-novo'),
    path('profissionais/<uuid:pk>/', views.ProfissionalView.as_view(), name='profissional'),
]
