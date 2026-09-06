from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from accounts.services import revoke_membership
from audit.services import record_audit_event

from .forms import AcceptInvitationAccountForm, CollaboratorInvitationForm
from .invitations import issue_invitation, peek_invitation
from .models import InvitationPurpose, Membership, Role
from .services import (
    EmailAlreadyRegistered,
    InvalidInvitation,
    InvitationEmailMismatch,
    accept_collaborator_invitation_for_user,
    accept_collaborator_invitation_new_user,
)


class OwnerRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        context = request.access_context
        if context is None or not context.has_role(Role.OWNER):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class CollaboratorListView(LoginRequiredMixin, OwnerRequiredMixin, View):
    def get(self, request):
        memberships = (
            Membership.objects
            .filter(tenant_id=request.access_context.tenant_id)
            .select_related('user')
            .order_by('user__email')
        )
        return render(request, 'tenancy/collaborators.html', {
            'memberships': memberships, 'form': CollaboratorInvitationForm(),
        })

    def post(self, request):
        form = CollaboratorInvitationForm(request.POST)
        if not form.is_valid():
            memberships = Membership.objects.filter(tenant_id=request.access_context.tenant_id).select_related('user')
            return render(request, 'tenancy/collaborators.html', {'memberships': memberships, 'form': form})
        from .models import Tenant

        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        invitation, raw_token = issue_invitation(
            InvitationPurpose.COLLABORATOR,
            issued_by=request.user,
            target_tenant=tenant,
            email_binding=form.cleaned_data['email'],
            role_grants=form.cleaned_data['roles'],
        )
        record_audit_event(
            request.user, tenant, 'tenancy.collaborator_invited', object_type='invitation',
            object_id=invitation.id, outcome='success',
        )
        return render(request, 'tenancy/collaborator_invited.html', {'token': raw_token, 'invitation': invitation})


class RevokeCollaboratorView(LoginRequiredMixin, OwnerRequiredMixin, View):
    def post(self, request, membership_id):
        membership = get_object_or_404(
            Membership, id=membership_id, tenant_id=request.access_context.tenant_id,
        )
        revoke_membership(membership, request.user)
        return redirect('tenancy:collaborators')


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
            return redirect('accounts:login')
        form = AcceptInvitationAccountForm(request.POST)
        if not form.is_valid():
            return render(request, 'tenancy/accept_invitation_signup.html', {'invitation': invitation, 'form': form})
        try:
            accept_collaborator_invitation_new_user(
                token, form.cleaned_data['email'], form.cleaned_data['password'],
            )
        except InvalidInvitation:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        except InvitationEmailMismatch:
            form.add_error('email', 'Este convite é vinculado a outro e-mail.')
            return render(request, 'tenancy/accept_invitation_signup.html', {'invitation': invitation, 'form': form})
        except EmailAlreadyRegistered:
            form.add_error('email', 'Este e-mail já possui conta. Faça login para aceitar o convite.')
            return render(request, 'tenancy/accept_invitation_signup.html', {'invitation': invitation, 'form': form})
        return redirect('accounts:login')
