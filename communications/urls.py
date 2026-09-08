from django.urls import path

from . import views

app_name = 'communications'

urlpatterns = [
    path('<str:raw_token>/', views.DocumentAccessLandingView.as_view(), name='document-access'),
    path('<str:raw_token>/arquivo/', views.DocumentAccessFileView.as_view(), name='document-file'),
]
