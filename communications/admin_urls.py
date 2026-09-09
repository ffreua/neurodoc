"""Rotas da área do gestor. Montadas sob `/app/org/`, separadas das rotas
públicas de acesso a documento (`communications/urls.py`, em `/d/`) porque
são coisas distintas: uma exige sessão de gestor, a outra é o link que o
paciente recebe.

O namespace é `messaging`, e não `communications`: dois includes com o mesmo
`app_name` deixam o `reverse` ambíguo — só o último registrado resolve, e o
outro passa a exigir `current_app`. Namespace distinto é o que faz
`{% url %}` significar sempre a mesma rota.
"""
from django.urls import path

from . import admin_views

app_name = 'messaging'

urlpatterns = [
    path('mensageria/', admin_views.MessagingSettingsView.as_view(), name='settings'),
    path('mensageria/sms/', admin_views.SmsSettingsSaveView.as_view(), name='save-sms'),
    path('mensageria/sms/testar/', admin_views.SmsTestView.as_view(), name='test-sms'),
    path(
        'mensageria/email/<uuid:membership_id>/',
        admin_views.DoctorEmailSettingsSaveView.as_view(), name='save-doctor-email',
    ),
    path(
        'mensageria/email/<uuid:membership_id>/testar/',
        admin_views.DoctorEmailTestView.as_view(), name='test-doctor-email',
    ),
    path(
        'mensageria/email-da-clinica/',
        admin_views.ClinicEmailSaveView.as_view(), name='save-clinic-email',
    ),
    path(
        'mensageria/email-da-clinica/testar/',
        admin_views.ClinicEmailTestView.as_view(), name='test-clinic-email',
    ),
    path('mensageria/entregas/', admin_views.DeliveryLogView.as_view(), name='deliveries'),

    # Comunicação em massa.
    path('campanhas/', admin_views.CampaignListView.as_view(), name='campaigns'),
    path('campanhas/nova/', admin_views.CampaignCreateView.as_view(), name='campaign-new'),
    path('campanhas/<uuid:campaign_id>/', admin_views.CampaignDetailView.as_view(), name='campaign-detail'),
    path('campanhas/<uuid:campaign_id>/testar/', admin_views.CampaignTestView.as_view(), name='campaign-test'),
    path(
        'campanhas/<uuid:campaign_id>/<str:action>/',
        admin_views.CampaignActionView.as_view(), name='campaign-action',
    ),
]
