from django.contrib.auth import login as auth_login
from django.shortcuts import redirect, render
from django.views import View

from accounts.services import send_email_verification
from audit.services import record_audit_event
from tenancy.invitations import peek_invitation
from tenancy.models import InvitationPurpose
from tenancy.services import EmailAlreadyRegistered, InvalidInvitation, accept_platform_invitation

from .forms import InvitationCodeForm, OrganizationSignupForm


class LandingView(View):
    def get(self, request):
        return render(request, 'onboarding/landing.html', {'form': InvitationCodeForm()})

    def post(self, request):
        form = InvitationCodeForm(request.POST)
        if not form.is_valid():
            return render(request, 'onboarding/landing.html', {'form': form})
        code = form.cleaned_data['code'].strip()
        invitation = peek_invitation(code)
        if invitation is None or invitation.purpose != InvitationPurpose.PLATFORM:
            form.add_error('code', 'Convite inválido, expirado ou já utilizado.')
            return render(request, 'onboarding/landing.html', {'form': form})
        return redirect('onboarding:signup', token=code)


class OrganizationSignupView(View):
    def _invitation_or_none(self, token):
        invitation = peek_invitation(token)
        if invitation is None or invitation.purpose != InvitationPurpose.PLATFORM:
            return None
        return invitation

    def get(self, request, token):
        if self._invitation_or_none(token) is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        return render(request, 'onboarding/signup.html', {'form': OrganizationSignupForm()})

    def post(self, request, token):
        if self._invitation_or_none(token) is None:
            return render(request, 'onboarding/invitation_invalid.html', status=400)
        form = OrganizationSignupForm(request.POST)
        if not form.is_valid():
            return render(request, 'onboarding/signup.html', {'form': form})
        try:
            user, tenant, membership = accept_platform_invitation(
                token,
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                legal_name=form.cleaned_data['legal_name'],
                trade_name=form.cleaned_data['trade_name'],
                cnpj=form.cleaned_data['cnpj'],
            )
        except InvalidInvitation:
            form.add_error(None, 'Convite inválido, expirado ou já utilizado.')
            return render(request, 'onboarding/signup.html', {'form': form})
        except EmailAlreadyRegistered:
            form.add_error('email', 'Este e-mail já possui conta. Faça login para vincular uma organização.')
            return render(request, 'onboarding/signup.html', {'form': form})
        record_audit_event(
            user, tenant, 'tenancy.organization_created',
            object_type='tenant', object_id=tenant.id, outcome='success',
        )
        auth_login(request, user)
        send_email_verification(user, request)
        return render(request, 'accounts/email_verification_sent.html')
