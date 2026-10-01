from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    # A semana é a tela principal: é nela que se vê o que está livre.
    path('', views.AgendaWeekView.as_view(), name='week'),
    path('dia/', views.AgendaDayView.as_view(), name='day'),
    path('mes/', views.AgendaMonthView.as_view(), name='month'),
    path('balcao/', views.SecretaryDeskView.as_view(), name='desk'),
    # A fila de retornos fica ao lado do balcão, e não dentro do prontuário:
    # quem a trabalha é a recepção.
    path('retornos/', views.ReturnQueueView.as_view(), name='returns'),
    # Estatísticas do mês. Sob a agenda, e com a capacidade dela: são
    # contagens de operação do consultório, não indicadores de gestão.
    path('estatisticas/', views.MonthStatisticsView.as_view(), name='estatisticas'),
    path(
        'retornos/<uuid:return_id>/baixa/',
        views.ReturnResolveView.as_view(), name='resolve-return',
    ),

    # Configuração da grade pelo médico.
    path('configurar/', views.ScheduleSettingsView.as_view(), name='settings'),
    path(
        'configurar/<uuid:membership_id>/grade/',
        views.ScheduleSettingsSaveView.as_view(), name='publish-schedule',
    ),
    path(
        'configurar/<uuid:membership_id>/duracoes/',
        views.TypeDurationSaveView.as_view(), name='save-durations',
    ),
    path(
        'configurar/<uuid:membership_id>/grade/<uuid:rule_id>/remover/',
        views.RuleDeleteView.as_view(), name='delete-rule',
    ),
    path(
        'configurar/<uuid:membership_id>/bloqueios/',
        views.BlockCreateView.as_view(), name='add-block',
    ),
    path(
        'configurar/<uuid:membership_id>/bloqueios/<uuid:block_id>/remover/',
        views.BlockDeleteView.as_view(), name='delete-block',
    ),
    path(
        'configurar/<uuid:membership_id>/feriados/',
        views.HolidayReviewView.as_view(), name='review-holidays',
    ),
    path(
        'configurar/<uuid:membership_id>/feriados/locais/',
        views.LocalHolidayCreateView.as_view(), name='add-local-holiday',
    ),
    path(
        'configurar/<uuid:membership_id>/feriados/locais/<uuid:holiday_id>/remover/',
        views.LocalHolidayDeleteView.as_view(), name='delete-local-holiday',
    ),

    # Reservas.
    path('<uuid:membership_id>/marcar/', views.QuickBookingView.as_view(), name='quick-book'),
    path('reservar/', views.ReserveAppointmentView.as_view(), name='reserve'),
    # Declaração de comparecimento: sai do menu do horário, na agenda, e
    # imprime direto. Não gera arquivo guardado — só o registro do ato.
    path(
        '<uuid:appointment_id>/declaracao/',
        views.AttendanceStatementView.as_view(), name='declaracao',
    ),
    path('horarios/', views.AvailabilitySlotsView.as_view(), name='availability'),
    path(
        '<uuid:appointment_id>/remarcar/',
        views.RescheduleAppointmentView.as_view(), name='reschedule',
    ),
    path(
        '<uuid:appointment_id>/trocar-paciente/',
        views.ChangePatientView.as_view(), name='change-patient',
    ),
    path(
        '<uuid:appointment_id>/confirmar-por/<str:channel>/',
        views.SendConfirmationView.as_view(), name='send-confirmation',
    ),
    path('<uuid:appointment_id>/<str:action>/', views.AppointmentActionView.as_view(), name='action'),
]
