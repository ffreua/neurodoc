from django.urls import path

from . import views

app_name = 'communications'

urlpatterns = [
    path('<str:raw_token>/', views.DocumentAccessLandingView.as_view(), name='document-access'),
    path('<str:raw_token>/request-code/', views.DocumentAccessRequestOtpView.as_view(), name='request-otp'),
    path('<str:raw_token>/verify-code/', views.DocumentAccessVerifyOtpView.as_view(), name='verify-otp'),
]
