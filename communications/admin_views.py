"""Configurações de mensageria — área do gestor da clínica.

Quem entra aqui é `owner` ou `manager`. Não é tela de médico nem de
secretaria: a chave da API de SMS e a senha do servidor de e-mail são
credenciais da organização, e quem responde por elas é quem administra a
clínica (matriz de permissões, PRD seção 4).

Segredo nunca volta para a tela. O que se mostra é a máscara — os últimos
caracteres — para o gestor conferir que a chave gravada é a que ele acha que
é, sem que a tela exiba a credencial.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from audit.services import record_audit_event
from base.crypto import SecretUnavailable, encrypt_secret, mask_secret, master_key_available, master_key_is_shared

from .email import EmailSendFailed, verify_sender
from .forms import DoctorEmailSettingsForm, SmsSettingsForm
from .models import DoctorEmailSettings, MessagingSettings
from .smsdev import SmsChannelDisabled, SmsSendFailed, check_balance


class ManagerRequiredView(LoginRequiredMixin, View):
    """Só `owner` e `manager` passam.

    A verificação é por papel no vínculo ativo, consultado no banco a cada
    requisição — e não por algo carregado na sessão no login: um papel
    revogado tem de deixar de valer imediatamente.
    """

    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        from tenancy.models import Membership, MembershipStatus, Role

        self.membership = Membership.objects.filter(
            id=request.access_context.membership_id,
            tenant_id=request.access_context.tenant_id,
            status=MembershipStatus.ACTIVE,
        ).select_related('tenant', 'user').first()
        if self.membership is None:
            raise Http404
        roles = set(self.membership.roles or [])
        if not roles & {Role.OWNER, Role.MANAGER}:
            # 404 e não 403: quem não administra a clínica não precisa saber
            # que esta tela existe.
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _doctors(tenant_id):
    from tenancy.models import Membership, MembershipStatus, Role

    return list(
        Membership.objects.filter(
            tenant_id=tenant_id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
        ).select_related('user', 'email_settings').order_by('user__first_name', 'user__email')
    )


def _sms_settings(tenant_id):
    row, _ = MessagingSettings.objects.get_or_create(tenant_id=tenant_id)
    return row


def _email_settings(tenant_id, membership):
    row, _ = DoctorEmailSettings.objects.get_or_create(
        tenant_id=tenant_id, physician_membership=membership,
    )
    return row


class MessagingSettingsView(ManagerRequiredView):
    def _context(self, request, **overrides):
        from django.conf import settings as django_settings

        tenant_id = request.access_context.tenant_id
        sms = _sms_settings(tenant_id)
        doctors = _doctors(tenant_id)

        # Um formulário por médico, montado aqui: o template não instancia
        # formulário, e sem isso a tela precisaria de um partial por caso.
        # O médico cujo envio falhou recebe o formulário vinculado, com os
        # erros e o que ele digitou.
        failed = overrides.pop('email_form_membership', None)
        bound = overrides.pop('email_form', None)
        rows = []
        for doctor in doctors:
            row = getattr(doctor, 'email_settings', None)
            if failed is not None and doctor.id == failed.id and bound is not None:
                form = bound
            else:
                form = DoctorEmailSettingsForm(instance=row)
            rows.append({'doctor': doctor, 'settings': row, 'form': form})
        context = {
            'email_form_membership': failed,
            'sms': sms,
            'sms_form': SmsSettingsForm(instance=sms),
            'doctor_rows': rows,
            'sms_globally_enabled': django_settings.SMS_ENABLED,
            'email_globally_enabled': django_settings.EMAIL_ENABLED,
            'default_from_email': django_settings.DEFAULT_FROM_EMAIL,
            'has_master_key': master_key_available(),
            'shared_master_key': master_key_is_shared(),
        }
        context.update(overrides)
        return context

    def get(self, request):
        return render(request, 'communications/settings.html', self._context(request))


class SmsSettingsSaveView(ManagerRequiredView):
    def post(self, request):
        tenant_id = request.access_context.tenant_id
        sms = _sms_settings(tenant_id)
        form = SmsSettingsForm(request.POST, instance=sms)
        if not form.is_valid():
            return render(
                request, 'communications/settings.html',
                MessagingSettingsView()._context(request, sms_form=form),
            )
        entered = (form.cleaned_data.get('api_key') or '').strip()
        row = form.save(commit=False)
        if entered:
            if not master_key_available():
                messages.error(
                    request,
                    'Não há chave-mestra configurada (SECRETS_MASTER_KEY), então a chave '
                    'do SMSDEV não pode ser guardada cifrada. Configure-a antes.',
                )
                return redirect('messaging:settings')
            row.sms_api_key_ciphertext, row.sms_api_key_metadata = encrypt_secret(entered)
            row.sms_api_key_hint = mask_secret(entered)
        row.updated_by = self.membership
        row.save()
        record_audit_event(
            request.user, tenant_id, 'communications.sms_settings_updated',
            object_type='tenant', object_id=tenant_id, outcome='success',
            # A chave **não** entra no log, nem mascarada: log é para saber
            # que mudou e quem mudou.
            integrity_metadata={'sms_enabled': row.sms_enabled, 'key_changed': bool(entered)},
        )
        messages.success(request, 'Configuração de SMS salva.')
        return redirect('messaging:settings')


class SmsTestView(ManagerRequiredView):
    """Testa a chave consultando o saldo — sem enviar SMS a ninguém."""

    def post(self, request):
        tenant_id = request.access_context.tenant_id
        try:
            result = check_balance(tenant_id)
        except SmsChannelDisabled as exc:
            messages.warning(request, str(exc))
            return redirect('messaging:settings')
        except (SmsSendFailed, SecretUnavailable) as exc:
            messages.error(request, f'A chave não foi aceita: {exc}')
            return redirect('messaging:settings')
        saldo = result.get('saldo_sms') or result.get('qt_saldo') or result.get('descricao') or '—'
        messages.success(
            request,
            f'Chave aceita pelo SMSDEV. Saldo informado pelo provedor: {saldo}. '
            'Nenhuma mensagem foi enviada neste teste.',
        )
        record_audit_event(
            request.user, tenant_id, 'communications.sms_key_tested',
            object_type='tenant', object_id=tenant_id, outcome='success',
        )
        return redirect('messaging:settings')


class DoctorEmailSettingsSaveView(ManagerRequiredView):
    def post(self, request, membership_id):
        from tenancy.models import Membership, MembershipStatus, Role

        tenant_id = request.access_context.tenant_id
        doctor = get_object_or_404(
            Membership, id=membership_id, tenant_id=tenant_id,
            status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
        )
        row = _email_settings(tenant_id, doctor)
        form = DoctorEmailSettingsForm(request.POST, instance=row)
        if not form.is_valid():
            return render(
                request, 'communications/settings.html',
                MessagingSettingsView()._context(
                    request, email_form=form, email_form_membership=doctor,
                ),
            )
        entered = (form.cleaned_data.get('smtp_password') or '').strip()
        saved = form.save(commit=False)
        if entered:
            if not master_key_available():
                messages.error(
                    request,
                    'Não há chave-mestra configurada (SECRETS_MASTER_KEY), então a senha '
                    'do SMTP não pode ser guardada cifrada. Configure-a antes.',
                )
                return redirect('messaging:settings')
            saved.smtp_password_ciphertext, saved.smtp_password_metadata = encrypt_secret(entered)
            saved.smtp_password_hint = mask_secret(entered)
        saved.tenant_id = tenant_id
        saved.physician_membership = doctor
        saved.updated_by = self.membership
        saved.full_clean()
        saved.save()
        record_audit_event(
            request.user, tenant_id, 'communications.doctor_email_settings_updated',
            object_type='membership', object_id=doctor.id, outcome='success',
            integrity_metadata={
                'enabled': saved.enabled, 'from_email': saved.from_email,
                'own_server': saved.uses_own_server, 'password_changed': bool(entered),
            },
        )
        name = doctor.user.get_full_name() or doctor.user.email
        messages.success(request, f'Remetente de e-mail de {name} salvo.')
        return redirect('messaging:settings')


class DoctorEmailTestView(ManagerRequiredView):
    """Abre a conexão SMTP do médico só para ver se ela funciona."""

    def post(self, request, membership_id):
        from tenancy.models import Membership, MembershipStatus, Role

        tenant_id = request.access_context.tenant_id
        doctor = get_object_or_404(
            Membership, id=membership_id, tenant_id=tenant_id,
            status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
        )
        row = DoctorEmailSettings.objects.filter(
            tenant_id=tenant_id, physician_membership=doctor,
        ).first()
        if row is None:
            messages.warning(request, 'Este médico ainda não tem remetente configurado.')
            return redirect('messaging:settings')
        try:
            verify_sender(row)
        except EmailSendFailed as exc:
            messages.error(request, f'A conexão SMTP falhou: {exc}')
            return redirect('messaging:settings')
        messages.success(
            request,
            'Conexão SMTP aceita. Nenhum e-mail foi enviado neste teste.',
        )
        record_audit_event(
            request.user, tenant_id, 'communications.doctor_smtp_tested',
            object_type='membership', object_id=doctor.id, outcome='success',
        )
        return redirect('messaging:settings')


class DeliveryLogView(ManagerRequiredView):
    """As últimas entregas, para o gestor ver se as mensagens estão saindo.

    Sem conteúdo da mensagem: o log mostra canal, destino, estado e quando —
    o suficiente para diagnosticar "o SMS não chegou" sem transformar a tela
    num arquivo de mensagens do paciente.
    """

    def get(self, request):
        from .models import Delivery

        deliveries = list(
            Delivery.objects.filter(tenant_id=request.access_context.tenant_id)
            .select_related('contact__patient', 'appointment__physician_membership__user')
            .order_by('-created_at')[:100]
        )
        return render(request, 'communications/deliveries.html', {
            'deliveries': deliveries,
            'settings_url': reverse('messaging:settings'),
        })
