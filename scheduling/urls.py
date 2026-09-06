from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.DayView.as_view(), name='day'),
    path('week/', views.WeekView.as_view(), name='week'),
    path('month/', views.MonthView.as_view(), name='month'),
    path('desk/', views.SecretaryDeskView.as_view(), name='desk'),
    path('reserve/', views.ReserveAppointmentView.as_view(), name='reserve'),
    path('availability/', views.AvailabilitySlotsView.as_view(), name='availability'),
    path('<uuid:appointment_id>/reschedule/', views.RescheduleAppointmentView.as_view(), name='reschedule'),
    path('<uuid:appointment_id>/<str:action>/', views.AppointmentActionView.as_view(), name='action'),
]
