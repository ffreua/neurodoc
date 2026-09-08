"""Rotas da configuração de IA, na área do gestor (`/app/org/`).

Namespace próprio (`ai-admin`), separado de `ai`: dois includes com o mesmo
`app_name` deixam o `reverse` ambíguo — só o último registrado resolve, e o
outro passa a exigir `current_app`. É a mesma razão pela qual a mensageria
usa `messaging` em vez de `communications`.
"""
from django.urls import path

from . import admin_views

app_name = 'ai-admin'

urlpatterns = [
    path('ia/', admin_views.AISettingsView.as_view(), name='settings'),
    path('ia/salvar/', admin_views.AISettingsSaveView.as_view(), name='save'),
    path('ia/modelos/', admin_views.AIModelsRefreshView.as_view(), name='refresh-models'),
    path('ia/testar/', admin_views.AITestView.as_view(), name='test'),
]
