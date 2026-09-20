from django.urls import path

from . import sse, views

app_name = 'teamchat'

urlpatterns = [
    path('estado/', views.StateView.as_view(), name='state'),
    path('abrir/', views.OpenView.as_view(), name='open'),
    path('stream/', sse.inbox_stream_view, name='stream'),
    # "Marcar como lida" fica num prefixo próprio, e não sob a conversa,
    # para que `tenancy.middleware.ALWAYS_ALLOWED_PREFIXES` possa liberar
    # **só** ela numa clínica suspensa. Estado do usuário, não da clínica:
    # congelar o envio é o ponto; congelar a badge deixaria um número
    # vermelho impossível de baixar no cabeçalho de quem continua
    # trabalhando. Ver o comentário lá.
    path('lida/<uuid:conversation_id>/', views.ReadView.as_view(), name='read'),
    path('<uuid:conversation_id>/', views.ThreadView.as_view(), name='thread'),
    path('<uuid:conversation_id>/enviar/', views.SendView.as_view(), name='send'),
]
