from django.urls import path

from . import help_views, views

app_name = 'onboarding'

urlpatterns = [
    path('', views.LandingView.as_view(), name='landing'),
    path('signup/<str:token>/', views.OrganizationSignupView.as_view(), name='signup'),
    # O contrato de adesao, aberto e sem convite. Quem vai aderir precisa
    # poder ler -- e mandar ao advogado da clinica -- antes de decidir; um
    # contrato que so aparece na hora de clicar em "aceito" e um contrato
    # que ninguem teve como avaliar.
    path('contrato/', views.ContractView.as_view(), name='contrato'),
    # O termo de consentimento do teleatendimento, aberto: o paciente recebe
    # o link por e-mail e precisa poder lê-lo sem conta. Participar da
    # teleconsulta implica concordar com ele (sem assinatura por paciente).
    path('termo-teleconsulta/', views.TermoTeleconsultaView.as_view(), name='termo-teleconsulta'),
    # Páginas de entrada da busca (2026-11-18, `base/paginas_seo.py`).
    path('neurologia/<slug:slug>/', views.TematicaView.as_view(tipo='area'), name='area'),
    path('recursos/<slug:slug>/', views.TematicaView.as_view(tipo='recurso'), name='recurso'),
    # Plano Gratuito sem intermediário: o botão do cartão posta aqui, o
    # convite é emitido na hora e a pessoa segue para `signup`. Os planos
    # pagos continuam indo ao formulário de contato, onde a conversa
    # comercial é o ponto.
    path('comecar-gratis/', views.StartFreePlanView.as_view(), name='start-free'),
    # Sete dias do Completo (1.35, `tenancy/degustacao.py`).
    path('degustacao/', views.StartTrialView.as_view(), name='start-trial'),
    # Ajuda pública, sem login: quem avalia o sistema precisa ver como ele
    # funciona antes de ter conta, e quem já usa costuma procurar ajuda no
    # celular, fora da sessão aberta no consultório.
    path('ajuda/', help_views.HelpIndexView.as_view(), name='help'),
    path('ajuda/perguntas/', help_views.HelpFaqView.as_view(), name='help-faq'),
    path('ajuda/<slug:slug>/', help_views.HelpArticleView.as_view(), name='help-article'),
]
