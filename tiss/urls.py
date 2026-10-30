from django.urls import path

from . import views, views_guia

app_name = 'tiss'

urlpatterns = [
    path('', views.InicioView.as_view(), name='inicio'),
    path('prestadores/novo/', views.PrestadorView.as_view(), name='prestador-novo'),
    path('prestadores/<uuid:pk>/', views.PrestadorView.as_view(), name='prestador'),
    path('credenciamentos/novo/', views.CredenciamentoView.as_view(), name='credenciamento-novo'),
    path('credenciamentos/<uuid:pk>/', views.CredenciamentoView.as_view(), name='credenciamento'),
    path('profissionais/novo/', views.ProfissionalView.as_view(), name='profissional-novo'),
    path('profissionais/<uuid:pk>/', views.ProfissionalView.as_view(), name='profissional'),
    path('guias/', views_guia.GuiaListaView.as_view(), name='guias'),
    path('guias/nova/', views_guia.GuiaNovaView.as_view(), name='guia-nova'),
    path('guias/<uuid:pk>/', views_guia.GuiaView.as_view(), name='guia'),
    path('guias/<uuid:pk>/itens/', views_guia.ItemView.as_view(), name='guia-item-novo'),
    path('guias/<uuid:pk>/itens/<uuid:item_id>/', views_guia.ItemView.as_view(), name='guia-item'),
    path('guias/<uuid:pk>/indicacao/', views_guia.IndicacaoView.as_view(), name='guia-indicacao'),
    path('guias/<uuid:pk>/imprimir/', views_guia.ImprimirView.as_view(), name='guia-imprimir'),
    path('guias/<uuid:pk>/<str:acao>/', views_guia.TransicaoView.as_view(), name='guia-transicao'),
]
