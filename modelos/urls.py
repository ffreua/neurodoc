from django.urls import path

from . import views

app_name = 'modelos'

urlpatterns = [
    path('', views.ListaView.as_view(), name='lista'),
    path('ver/<str:chave>/', views.VerView.as_view(), name='ver'),
    path('novo/<str:tipo>/', views.NovoView.as_view(), name='novo'),
    path('copiar/', views.CopiarView.as_view(), name='copiar'),
    path('<uuid:modelo_id>/editar/', views.EditarView.as_view(), name='editar'),
    path('<uuid:modelo_id>/excluir/', views.ExcluirView.as_view(), name='excluir'),
    path('atendimento/<uuid:encounter_id>/', views.EmitirView.as_view(), name='emitir'),
]
