from django.urls import path

from . import views

app_name = 'contratacao'

urlpatterns = [
    path('contratar/pedido/<uuid:pedido_id>/', views.PedidoView.as_view(), name='pedido'),
    path('contratar/<slug:plano>/', views.ContratarView.as_view(), name='contratar'),
    # O aviso da Asaas. Fora de `/app/` e sem sessão: quem posta é o servidor dela.
    path('asaas/webhook/', views.WebhookAsaasView.as_view(), name='webhook'),
]
