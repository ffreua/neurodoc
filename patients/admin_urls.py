"""Rotas do cadastro de convênios e planos, na área administrativa.

Montadas sob `/app/org/`, e não sob `/app/patients/`: quem entra aqui está
administrando a clínica, não atendendo um paciente.

Namespace próprio (`health-plans`), separado de `patients`, pela razão já
registrada em `communications/admin_urls.py`: dois includes com o mesmo
`app_name` deixam o `reverse` ambíguo.
"""
from django.urls import path

from . import plan_views

app_name = 'health-plans'

urlpatterns = [
    path('convenios/', plan_views.HealthPlanListView.as_view(), name='list'),
    path('convenios/novo/', plan_views.InsurerCreateView.as_view(), name='insurer-new'),
    path(
        'convenios/<uuid:insurer_id>/salvar/',
        plan_views.InsurerUpdateView.as_view(), name='insurer-save',
    ),
    path('convenios/planos/novo/', plan_views.HealthPlanCreateView.as_view(), name='plan-new'),
    path(
        'convenios/planos/<uuid:plan_id>/salvar/',
        plan_views.HealthPlanUpdateView.as_view(), name='plan-save',
    ),
]
