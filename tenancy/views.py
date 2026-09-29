"""Aceite de convite — a única tela de `tenancy` que não exige sessão.

A administração da organização (equipe, papéis, identidade da clínica)
mora em `admin_views.py`. Aqui fica o outro lado: a página que a pessoa
convidada abre a partir do link, antes de ter vínculo, e às vezes antes de
ter conta.
"""

from django.shortcuts import redirect, render
from django.views import View

from accounts.services import send_email_verification
from .forms import AcceptInvitationAccountForm
from .invitations import peek_invitation
from .limits import PlanLimitReached
from .models import InvitationPurpose
from .services import (
    EmailAlreadyRegistered,
    InvalidInvitation,
    InvitationEmailMismatch,
    accept_collaborator_invitation_for_user,
    accept_collaborator_invitation_new_user,
)


class AcceptCollaboratorInvitationView(View):
    def _invitation_or_404(self, token):
        invitation = peek_invitation(token)
        if invitation is None or invitation.purpose != InvitationPurpose.COLLABORATOR:
            return None
        return invitation

    def get(self, request, token):
        invitation = self._invitation_or_404(token)
        if invitation is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        if request.user.is_authenticated:
            return render(request, 'tenancy/accept_invitation_confirm.html', {'invitation': invitation})
        return render(request, 'tenancy/accept_invitation_signup.html', {
            'invitation': invitation, 'form': AcceptInvitationAccountForm(initial={'email': invitation.email_binding}),
        })

    def post(self, request, token):
        invitation = self._invitation_or_404(token)
        if invitation is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        if request.user.is_authenticated:
            try:
                accept_collaborator_invitation_for_user(token, request.user)
            except (InvalidInvitation, InvitationEmailMismatch):
                return render(request, 'onboarding/invitation_invalid.html', status=400)
            except PlanLimitReached as limite:
                # A clínica encheu entre a emissão e o aceite. Quem está na
                # tela não pode resolver isso, então a mensagem manda falar
                # com a clínica em vez de sugerir uma ação que não existe.
                return render(request, 'tenancy/invitation_limit_reached.html',
                              {'limite': limite, 'invitation': invitation}, status=409)
            return redirect('accounts:login')
        form = AcceptInvitationAccountForm(request.POST)
        if not form.is_valid():
            return render(request, 'tenancy/accept_invitation_signup.html', {'invitation': invitation, 'form': form})
        try:
            user, _membership = accept_collaborator_invitation_new_user(
                token, form.cleaned_data['email'], form.cleaned_data['password1'],
            )
        except InvalidInvitation:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        except InvitationEmailMismatch:
            form.add_error('email', 'Este convite é vinculado a outro e-mail.')
            return render(request, 'tenancy/accept_invitation_signup.html', {'invitation': invitation, 'form': form})
        except EmailAlreadyRegistered:
            form.add_error('email', 'Este e-mail já possui conta. Faça login para aceitar o convite.')
            return render(request, 'tenancy/accept_invitation_signup.html', {'invitation': invitation, 'form': form})
        except PlanLimitReached as limite:
            return render(request, 'tenancy/invitation_limit_reached.html',
                          {'limite': limite, 'invitation': invitation}, status=409)
        send_email_verification(user, request)
        return redirect('accounts:login')
