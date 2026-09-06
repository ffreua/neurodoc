from django.urls import path

from . import views

app_name = 'onboarding'

urlpatterns = [
    path('', views.LandingView.as_view(), name='landing'),
    path('signup/<str:token>/', views.OrganizationSignupView.as_view(), name='signup'),
]
