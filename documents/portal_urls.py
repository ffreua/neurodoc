"""Endereços públicos do portal de solicitações.

Ficam na raiz, sob o slug da clínica, e não em `/app/`: quem abre esta
página não tem conta neste sistema e nunca terá. O slug no caminho é o que
diz de qual clínica é o portal — a mesma instalação atende várias, e o
paciente da clínica A não pode cair no formulário da clínica B.
"""

from django.urls import path

from . import portal_views

app_name = 'portal'

urlpatterns = [
    path('<slug:slug>/', portal_views.PortalIdentifyView.as_view(), name='identify'),
    path('<slug:slug>/solicitar/', portal_views.PortalRequestView.as_view(), name='request'),
    path('<slug:slug>/enviado/', portal_views.PortalDoneView.as_view(), name='done'),
]
