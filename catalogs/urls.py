"""Rotas da busca de códigos.

Montadas sob `/app/codigos/`, e não dentro de `ai/`: procurar um código no
CID-10 ou na TUSS não é inteligência artificial nenhuma — é consulta a
catálogo. Ficam ao alcance da área de apoio porque é de lá que se procura,
mas pertencem ao domínio de catálogos.
"""
from django.urls import path

from . import views

app_name = 'catalogs'

urlpatterns = [
    path('', views.CodeSearchView.as_view(), name='search'),
    path('cid/buscar/', views.DiagnosisSearchAPI.as_view(), name='cid-search'),
    path('tuss/buscar/', views.ProcedureSearchAPI.as_view(), name='tuss-search'),
    path('medicamentos/buscar/', views.MedicationSearchAPI.as_view(), name='medicamento-search'),
    path('municipios/buscar/', views.MunicipalitySearchAPI.as_view(), name='municipio-search'),
]
