from django.urls import path

from . import views

app_name = 'crm'

urlpatterns = [
    path('', views.CRMBoardView.as_view(), name='board'),
    path('<uuid:card_id>/move/', views.CRMCardMoveView.as_view(), name='move'),
]
