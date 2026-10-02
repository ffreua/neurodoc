from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.EmailLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('mfa/challenge/', views.MFAChallengeView.as_view(), name='mfa-challenge'),
    path('minha-conta/', views.MinhaContaView.as_view(), name='minha-conta'),
    path('mfa/setup/', views.MFASetupView.as_view(), name='mfa-setup'),
    path('mfa/confirmar/', views.MFAConfirmView.as_view(), name='mfa-confirm'),
    path('switch-tenant/', views.SwitchTenantView.as_view(), name='switch-tenant'),
    path('select-organization/', views.TenantPickerView.as_view(), name='tenant-picker'),
    path('verify-email/resend/', views.ResendVerificationEmailView.as_view(), name='verify-email-resend'),
    path('verify-email/<str:token>/', views.VerifyEmailView.as_view(), name='verify-email'),
    # `success_url` explícito nas duas views abaixo.
    #
    # As views prontas do Django apontam para `password_reset_done` e
    # `password_reset_complete` **sem namespace**, e estas rotas vivem sob
    # `app_name = 'accounts'`. O `reverse` interno então não resolve, e o
    # erro só aparece depois de a pessoa enviar o formulário — com a senha
    # já gravada, no caso do `confirm`: a redefinição funcionava e
    # terminava em 500, o que é indistinguível de ter falhado.
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset.html',
            email_template_name='accounts/email/password_reset_email.txt',
            subject_template_name='accounts/email/password_reset_subject.txt',
            success_url=reverse_lazy('accounts:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='accounts/password_reset_done.html'),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='accounts/password_reset_complete.html'),
        name='password_reset_complete',
    ),
]
