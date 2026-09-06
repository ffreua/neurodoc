from django.urls import path

from . import views

app_name = 'tenancy'

urlpatterns = [
    path('app/org/collaborators/', views.CollaboratorListView.as_view(), name='collaborators'),
    path(
        'app/org/collaborators/<uuid:membership_id>/revoke/',
        views.RevokeCollaboratorView.as_view(), name='revoke-collaborator',
    ),
    path('invite/<str:token>/', views.AcceptCollaboratorInvitationView.as_view(), name='accept-invite'),
]
