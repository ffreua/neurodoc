from django.urls import path

from . import help_views, views

app_name = 'onboarding'

urlpatterns = [
    path('', views.LandingView.as_view(), name='landing'),
    path('signup/<str:token>/', views.OrganizationSignupView.as_view(), name='signup'),
    # Ajuda pública, sem login: quem avalia o sistema precisa ver como ele
    # funciona antes de ter conta, e quem já usa costuma procurar ajuda no
    # celular, fora da sessão aberta no consultório.
    path('ajuda/', help_views.HelpIndexView.as_view(), name='help'),
    path('ajuda/perguntas/', help_views.HelpFaqView.as_view(), name='help-faq'),
    path('ajuda/<slug:slug>/', help_views.HelpArticleView.as_view(), name='help-article'),
]
