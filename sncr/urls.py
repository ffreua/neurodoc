from django.urls import path

from . import views

app_name = 'sncr'

urlpatterns = [
    path('', views.PainelView.as_view(), name='painel'),
    path('pedir/<str:tipo>/', views.PedirView.as_view(), name='pedir'),
    path('retorno/', views.RetornoView.as_view(), name='retorno'),
]
