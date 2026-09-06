from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.EmailLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('mfa/challenge/', views.MFAChallengeView.as_view(), name='mfa-challenge'),
    path('mfa/setup/', views.MFASetupView.as_view(), name='mfa-setup'),
    path('switch-tenant/', views.SwitchTenantView.as_view(), name='switch-tenant'),
    path('select-organization/', views.TenantPickerView.as_view(), name='tenant-picker'),
    path('verify-email/<str:token>/', views.VerifyEmailView.as_view(), name='verify-email'),
    path('verify-email/resend/', views.ResendVerificationEmailView.as_view(), name='verify-email-resend'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(template_name='accounts/password_reset.html'),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='accounts/password_reset_done.html'),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(template_name='accounts/password_reset_confirm.html'),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='accounts/password_reset_complete.html'),
        name='password_reset_complete',
    ),
]
