from django.contrib.auth import login as auth_login
from django.contrib.auth.mixins import LoginRequiredMixin
from django_otp import login as django_otp_login
from django.contrib.auth.views import LoginView
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import FormView

from audit.services import record_audit_event

from . import mfa, services, throttling
from .forms import MFAChallengeForm, ThrottledAuthenticationForm
from .models import User

PENDING_MFA_SESSION_KEY = 'pending_mfa_user_id'


class EmailLoginView(LoginView):
    form_class = ThrottledAuthenticationForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = False

    def form_valid(self, form):
        user = form.get_user()
        client_ip = self.request.META.get('REMOTE_ADDR')
        throttling.clear_failures(user.email, client_ip)
        if mfa.user_has_confirmed_totp(user):
            self.request.session[PENDING_MFA_SESSION_KEY] = str(user.id)
            record_audit_event(
                user, None, 'auth.login_password_ok_mfa_pending', outcome='success',
            )
            return redirect('accounts:mfa-challenge')
        auth_login(self.request, user)
        record_audit_event(user, None, 'auth.login', outcome='success')
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        record_audit_event(None, None, 'auth.login_failed', outcome='denied')
        return super().form_invalid(form)


class MFAChallengeView(FormView):
    form_class = MFAChallengeForm
    template_name = 'accounts/mfa_challenge.html'
    pending_user = None

    def dispatch(self, request, *args, **kwargs):
        self.pending_user = self._get_pending_user(request)
        if self.pending_user is None:
            return redirect('accounts:login')
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _get_pending_user(request):
        user_id = request.session.get(PENDING_MFA_SESSION_KEY)
        if not user_id:
            return None
        return User.objects.filter(id=user_id, is_active=True).first()

    def form_valid(self, form):
        code = form.cleaned_data['code'].strip()
        user = self.pending_user
        ok = mfa.verify_totp_token(user, code) or mfa.consume_recovery_code(user, code)
        if not ok:
            record_audit_event(user, None, 'auth.mfa_challenge_failed', outcome='denied')
            form.add_error('code', 'Invalid code.')
            return self.form_invalid(form)
        del self.request.session[PENDING_MFA_SESSION_KEY]
        auth_login(self.request, user)
        django_otp_login(self.request, mfa.get_confirmed_device(user))
        mfa.mark_recent_mfa(self.request)
        record_audit_event(
            user, None, 'auth.login', outcome='success', integrity_metadata={'mfa': True},
        )
        return redirect(self.request.GET.get('next') or 'accounts:tenant-picker')


class VerifyEmailView(View):
    def get(self, request, token):
        user = services.confirm_email_verification(token)
        if user is None:
            return render(request, 'accounts/email_verification_invalid.html', status=400)
        return render(request, 'accounts/email_verification_success.html')


class ResendVerificationEmailView(LoginRequiredMixin, View):
    def post(self, request):
        if request.user.email_verified_at is None:
            services.send_email_verification(request.user, request)
        return render(request, 'accounts/email_verification_sent.html')


def _safe_next(request):
    from django.utils.http import url_has_allowed_host_and_scheme

    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return None


class SwitchTenantView(LoginRequiredMixin, View):
    def post(self, request):
        tenant_id = request.POST.get('tenant_id')
        if services.switch_tenant(request, tenant_id):
            return redirect(_safe_next(request) or 'reporting:dashboard')
        return HttpResponseForbidden('No active membership for that organization.')


class TenantPickerView(LoginRequiredMixin, View):
    """LOGIN_REDIRECT_URL lands here, not directly on /app/ -- a fresh
    login carries no `tenant_id` in session yet, and TenantMiddleware
    redirects any /app/ path without one back to this same picker
    (preserving where the user meant to go via `next`). A user with
    exactly one active membership skips straight through; anyone in more
    than one organization picks explicitly, every time, since the session
    never remembers a previous choice across logins on purpose (a revoked
    membership must never be silently reused from a stale session).
    """

    def get(self, request):
        from tenancy.models import Membership, MembershipStatus

        memberships = Membership.objects.filter(
            user=request.user, status=MembershipStatus.ACTIVE,
        ).select_related('tenant').order_by('tenant__legal_name')
        next_url = _safe_next(request)
        if memberships.count() == 1:
            if services.switch_tenant(request, memberships.first().tenant_id):
                return redirect(next_url or 'reporting:dashboard')
        if not memberships:
            return render(request, 'accounts/no_organizations.html')
        return render(request, 'accounts/tenant_picker.html', {'memberships': memberships, 'next': next_url})


class MFASetupView(LoginRequiredMixin, View):
    def get(self, request):
        device = mfa.get_or_create_pending_device(request.user)
        return render(request, 'accounts/mfa_setup.html', {'otpauth_url': device.config_url})

    def post(self, request):
        device = mfa.get_or_create_pending_device(request.user)
        code = request.POST.get('code', '').strip()
        if mfa.confirm_device(device, code):
            codes = mfa.generate_recovery_codes(request.user)
            record_audit_event(request.user, None, 'accounts.mfa_enabled', outcome='success')
            return render(request, 'accounts/mfa_recovery_codes.html', {'codes': codes})
        return render(request, 'accounts/mfa_setup.html', {
            'otpauth_url': device.config_url, 'error': 'Invalid code.',
        })
