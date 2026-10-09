from django.contrib.auth import login as auth_login
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django_otp import login as django_otp_login
from django.contrib.auth.views import LoginView
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views import View
from django.views.generic import FormView

from audit.services import record_audit_event

from . import mfa, services, throttling
from .forms import MFAChallengeForm, ThrottledAuthenticationForm
from .models import User
from base.net import client_ip

PENDING_MFA_SESSION_KEY = 'pending_mfa_user_id'


class EmailLoginView(LoginView):
    form_class = ThrottledAuthenticationForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = False

    def form_valid(self, form):
        user = form.get_user()
        ip_do_cliente = client_ip(self.request)
        throttling.clear_failures(user.email, ip_do_cliente)
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
            form.add_error('code', 'Código inválido.')
            return self.form_invalid(form)
        del self.request.session[PENDING_MFA_SESSION_KEY]
        auth_login(self.request, user)
        django_otp_login(self.request, mfa.get_confirmed_device(user))
        mfa.mark_recent_mfa(self.request)
        record_audit_event(
            user, None, 'auth.login', outcome='success', integrity_metadata={'mfa': True},
        )
        # `_safe_next`, como o resto do login: o `next` cru mandava quem
        # acabou de provar o segundo fator para qualquer domínio escrito na
        # URL -- o golpe de phishing perfeito, porque começa no endereço
        # verdadeiro (auditoria de 2026-10-09, ND-1121-010).
        return redirect(_safe_next(self.request) or 'accounts:tenant-picker')


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
        return HttpResponseForbidden('Você não tem vínculo ativo com essa organização.')


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



class MFAConfirmView(LoginRequiredMixin, FormView):
    """Reconfirmar o segundo fator sem sair da sessão.

    Faltava, e a falta aparecia como página em branco. Operações
    privilegiadas — abrir sessão de assinatura, enviar certificado, o
    console de instalação — exigem MFA **recente** (trinta minutos); a
    verificação do login envelhece, e quando envelhecia não havia para
    onde mandar o médico. O que havia eram duas saídas ruins:
    `HttpResponseForbidden` com o texto cru numa tela branca, e uma
    mensagem pedindo para **sair e entrar de novo** — derrubar a sessão
    inteira para reconfirmar um código de seis dígitos.

    Não se confunde com `MFAChallengeView`, e as duas não dão para unir:
    aquela atende quem **ainda não entrou** (há um usuário pendente na
    sessão, e o sucesso faz o login); esta atende quem já está dentro, e o
    sucesso só carimba a hora. Unir as duas significaria uma view onde o
    estado de autenticação do visitante é condicional — exatamente o lugar
    onde um erro vira falha de autenticação.

    O `next` é validado contra o próprio host: um destino solto aqui
    transformaria a confirmação de MFA em trampolim para fora do domínio,
    que é o formato clássico do phishing de redirecionamento.
    """

    form_class = MFAChallengeForm
    template_name = 'accounts/mfa_confirm.html'

    def _destino(self):
        candidato = self.request.POST.get('next') or self.request.GET.get('next')
        if candidato and url_has_allowed_host_and_scheme(
            candidato, allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return candidato
        return reverse('reporting:dashboard')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not mfa.user_has_confirmed_totp(request.user):
            # Sem segundo fator configurado nao ha o que reconfirmar; o
            # caminho util e o de configurar, levando o destino junto.
            messages.warning(
                request, 'Configure a verificação em duas etapas para continuar.',
            )
            setup = reverse('accounts:mfa-setup')
            return redirect(f'{setup}?{urlencode({"next": self._destino()})}')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        dados = super().get_context_data(**kwargs)
        dados['next'] = self._destino()
        dados['minutos'] = mfa.RECENT_MFA_MAX_AGE_SECONDS // 60
        return dados

    def form_valid(self, form):
        user = self.request.user
        code = form.cleaned_data['code'].strip()
        if not (mfa.verify_totp_token(user, code) or mfa.consume_recovery_code(user, code)):
            record_audit_event(user, None, 'auth.mfa_reconfirm_failed', outcome='denied')
            form.add_error('code', 'Código inválido. Confira no aplicativo e tente de novo.')
            return self.form_invalid(form)
        mfa.mark_recent_mfa(self.request)
        record_audit_event(user, None, 'auth.mfa_reconfirmed', outcome='success')
        return redirect(self._destino())


class MinhaContaView(LoginRequiredMixin, View):
    """O nome da própria conta, editável pela própria pessoa.

    Fora de `/app/` de propósito. Aquele prefixo significa "dentro de uma
    clínica", e `TenantMiddleware` manda escolher uma antes de deixar
    entrar — mas quem opera o servidor não tem vínculo com clínica
    nenhuma, e também precisa de nome. Aqui, ao lado da MFA, a tela
    responde para todo mundo que tem conta.

    Sem verificação de papel: cada um edita o próprio nome, e `request.user`
    é a garantia disso. Não há `<id>` na rota justamente para que não
    exista o caminho de editar o de outro — a alternativa seria uma
    verificação de dono em cada requisição, e a que fosse esquecida seria a
    que ninguém testaria.
    """

    @staticmethod
    def _fragmento(request):
        return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _render(self, request, *, form=None, status=200, salvo=False):
        template = (
            'accounts/_minha_conta_panel.html'
            if self._fragmento(request)
            else 'accounts/minha_conta.html'
        )
        contexto = self._contexto(request, form=form)
        contexto['conta_salva'] = salvo
        return render(request, template, contexto, status=status)

    def get(self, request):
        return self._render(request)

    def post(self, request):
        from .forms import MinhaContaForm

        form = MinhaContaForm(request.POST, instance=request.user)
        if not form.is_valid():
            return self._render(request, form=form, status=400)
        form.save()
        record_audit_event(
            request.user, getattr(request.access_context, 'tenant_id', None),
            'accounts.profile_updated', outcome='success',
        )
        if self._fragmento(request):
            return self._render(request, salvo=True)
        messages.success(request, 'Nome atualizado.')
        return redirect('accounts:minha-conta')

    @staticmethod
    def _contexto(request, form=None):
        from .forms import MinhaContaForm

        return {
            'form': form or MinhaContaForm(instance=request.user),
            # A tela diz de onde vem o nome que aparece hoje. Sem isso, o
            # médico que ja preencheu o perfil profissional nao entende por
            # que este campo esta vazio se a agenda ja o chama pelo nome.
            'nome_em_uso': request.user.get_full_name(),
            'perfil_medico': getattr(request.user, 'physician_profile', None),
            'mfa_ativa': mfa.user_has_confirmed_totp(request.user),
        }


class MFASetupView(LoginRequiredMixin, View):
    @staticmethod
    def _context(request, device, error=None):
        return {
            'otpauth_url': device.config_url,
            'qr_code_data_uri': mfa.qr_code_data_uri(device.config_url),
            'next': _safe_next(request),
            'error': error,
        }

    def get(self, request):
        device = mfa.get_or_create_pending_device(request.user)
        return render(request, 'accounts/mfa_setup.html', self._context(request, device))

    def post(self, request):
        device = mfa.get_or_create_pending_device(request.user)
        code = request.POST.get('code', '').strip()
        if mfa.confirm_device(device, code):
            codes = mfa.generate_recovery_codes(request.user)
            # A sessão passa a valer como verificada aqui mesmo.
            #
            # O código que a pessoa acabou de digitar **é** o segundo fator:
            # ela provou a posse do dispositivo neste mesmo pedido. Sem esta
            # linha, a sessão continuava sem `is_verified()` e tudo o que
            # exige MFA — o console da instalação, os painéis técnicos, o
            # admin — seguia devolvendo 404 até um novo login. O efeito para
            # quem acabou de configurar o segundo fator é a coisa que ele
            # existe para abrir continuar fechada, sem dizer por quê.
            django_otp_login(request, device)
            mfa.mark_recent_mfa(request)
            record_audit_event(request.user, None, 'accounts.mfa_enabled', outcome='success')
            return render(request, 'accounts/mfa_recovery_codes.html', {
                'codes': codes, 'next': _safe_next(request),
            })
        return render(
            request, 'accounts/mfa_setup.html',
            self._context(request, device, error='Código inválido.'),
        )
