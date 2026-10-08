from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.NotificationListView.as_view(), name='list'),
    path('marcar-todas/', views.NotificationMarkAllReadView.as_view(), name='mark-all-read'),
    path('limpar/', views.NotificationClearAllView.as_view(), name='clear-all'),
    path('<uuid:notification_id>/read/', views.NotificationMarkReadView.as_view(), name='mark-read'),
    path('<uuid:notification_id>/abrir/', views.NotificationOpenView.as_view(), name='open'),
]
