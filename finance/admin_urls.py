"""Rotas da tabela de honorários, na área administrativa (`/app/org/`).

Separadas de `finance/urls.py`, que atende a operação do dia — recebimento,
pagamento, ajuste. Definir quanto custa a consulta é decisão de cadastro,
não lançamento.

Namespace próprio (`fees`), pela razão registrada em
`communications/admin_urls.py`: dois includes com o mesmo `app_name`
deixam o `reverse` ambíguo.
"""
from django.urls import path

from . import fee_views

app_name = 'fees'

urlpatterns = [
    path('valores/', fee_views.FeeScheduleListView.as_view(), name='list'),
    path('valores/novo/', fee_views.FeeScheduleCreateView.as_view(), name='new'),
    path('valores/<uuid:fee_id>/encerrar/', fee_views.FeeScheduleCloseView.as_view(), name='close'),
]
