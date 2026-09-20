from django.urls import path

from . import admin_views, views

app_name = 'tenancy'

urlpatterns = [
    # Equipe e concessão de papel.
    path('app/org/equipe/', admin_views.TeamView.as_view(), name='team'),
    path(
        'app/org/equipe/<uuid:membership_id>/papeis/',
        admin_views.MembershipRolesView.as_view(), name='membership-roles',
    ),
    path(
        'app/org/equipe/<uuid:membership_id>/registro-profissional/',
        admin_views.PhysicianProfileView.as_view(), name='physician-profile',
    ),
    path(
        'app/org/equipe/<uuid:membership_id>/registro-profissional/<str:decision>/',
        admin_views.PhysicianVerificationView.as_view(), name='physician-verification',
    ),
    # Genérica por último, de propósito: `<str:action>` casa com qualquer
    # segmento, inclusive `papeis` e `registro-profissional`. Declarada
    # antes delas, engoliria as duas e devolveria 404 por ação inválida.
    path(
        'app/org/equipe/<uuid:membership_id>/<str:action>/',
        admin_views.MembershipStatusView.as_view(), name='membership-status',
    ),
    path(
        'app/org/convites/<uuid:invitation_id>/cancelar/',
        admin_views.InvitationRevokeView.as_view(), name='revoke-invitation',
    ),

    # Identidade da clínica.
    # Fale com a NeuroDoc / Envie sugestões. Fora de `org/` porque não é
    # administração da clínica: qualquer vínculo ativo escreve, inclusive
    # quem não administra nada.
    path(
        'app/mensagem/<str:kind>/',
        admin_views.ClinicMessageView.as_view(), name='clinic-message',
    ),
    path('app/org/clinica/', admin_views.ClinicProfileView.as_view(), name='clinic'),
    path('app/org/clinica/portal/', admin_views.ClinicPortalView.as_view(), name='clinic-portal'),
    path('app/org/clinica/logotipo/', admin_views.ClinicLogoView.as_view(), name='clinic-logo'),
    path(
        'app/org/clinica/logotipo.img',
        admin_views.ClinicLogoFileView.as_view(), name='clinic-logo-file',
    ),

    # Rotas antigas. `collaborators` continua respondendo porque estava no
    # menu, em breadcrumb e possivelmente em link salvo por quem usa; a
    # tela virou "equipe" e um 404 aqui seria a primeira coisa que quem
    # administra encontraria depois da atualização.
    path('app/org/collaborators/', admin_views.TeamView.as_view(), name='collaborators'),
    path(
        'app/org/collaborators/<uuid:membership_id>/revoke/',
        admin_views.MembershipStatusView.as_view(), {'action': 'revoke'},
        name='revoke-collaborator',
    ),

    path('invite/<str:token>/', views.AcceptCollaboratorInvitationView.as_view(), name='accept-invite'),
]
