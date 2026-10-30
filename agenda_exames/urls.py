from django.urls import path

from . import views

app_name = 'agenda_exames'

urlpatterns = [
    path('', views.AgendaView.as_view(), name='agenda'),
    path('agendas/', views.RecursosView.as_view(), name='recursos'),
    path('agendas/nova/', views.RecursoView.as_view(), name='recurso-novo'),
    path('agendas/<uuid:pk>/', views.RecursoView.as_view(), name='recurso'),
    path('agendas/<uuid:pk>/marcar/', views.ReservaNovaView.as_view(), name='reservar'),
    path('reservas/<uuid:pk>/', views.ReservaView.as_view(), name='reserva'),
]
