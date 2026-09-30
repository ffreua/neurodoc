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
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from audit.services import record_audit_event
from base.crypto import SecretUnavailable, encrypt_secret, mask_secret, master_key_available, master_key_is_shared
from tenancy.permissions import Capability, CapabilityRequiredView

from .email import EmailSendFailed, verify_sender
from .forms import DoctorEmailSettingsForm, SmsSettingsForm
from .models import DoctorEmailSettings, MessagingSettings
from .smsdev import SmsChannelDisabled, SmsSendFailed, check_balance


class ManagerRequiredView(CapabilityRequiredView):
    """Credenciais de provedor — só quem administra a operação da clínica.

    A capacidade é `MANAGE_INTEGRATIONS` (`tenancy.permissions`), concedida
    a `owner` e `manager`. Antes a verificação de papel estava escrita aqui
    dentro, e era a única do sistema fora de colaboradores: o resultado é a
    matriz do PRD valendo em duas telas e em nenhuma outra.

    `self.membership` continua carregado porque as gravações registram
    quem alterou (`updated_by`), o que a capacidade não diz.
    """

    required_capability = Capability.MANAGE_INTEGRATIONS

    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        from tenancy.models import Membership, MembershipStatus

        self.membership = Membership.objects.filter(
            id=request.access_context.membership_id,
            tenant_id=request.access_context.tenant_id,
            status=MembershipStatus.ACTIVE,
        ).select_related('tenant', 'user').first()
        if self.membership is None:
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
    @staticmethod
    def _context(request, manager_membership, **overrides):
        """Monta a tela inclusive quando quem recebeu o POST e outra view.

        As views de salvamento precisam redesenhar esta tela com o formulario
        invalido. Criar `MessagingSettingsView()` ali nao executa `dispatch`,
        portanto nunca cria `self.membership`; quando o contexto passou a
        consultar o plano, qualquer erro de validacao virou um 500. O vinculo
        entra agora como dependencia explicita, ja validada pelo `dispatch`
        da view que esta atendendo a requisicao.
        """
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
        from .forms import ClinicEmailSettingsForm, EmailTestForm
        from tenancy.plans import has_sms, plan_label

        context = {
            'email_form_membership': failed,
            'sms': sms,
            'sms_form': SmsSettingsForm(instance=sms),
            'clinic_email_form': ClinicEmailSettingsForm(instance=sms),
            'email_test_form': EmailTestForm(),
            'doctor_rows': rows,
            'sms_globally_enabled': django_settings.SMS_ENABLED,
            # Duas coisas diferentes, e a tela distingue as duas: o
            # interruptor da instalacao inteira (acima) e o que ESTE plano
            # contratou (abaixo). Juntar as duas numa mensagem so mandaria
            # a clinica do Gratuito esperar uma liberacao que nunca vem.
            'sms_contratado': has_sms(manager_membership.tenant.plan),
            'plano_da_clinica': plan_label(manager_membership.tenant.plan),
            'email_globally_enabled': django_settings.EMAIL_ENABLED,
            'default_from_email': django_settings.DEFAULT_FROM_EMAIL,
            'has_master_key': master_key_available(),
            'shared_master_key': master_key_is_shared(),
        }
        context.update(overrides)
        return context

    def get(self, request):
        return render(
            request, 'communications/settings.html',
            self._context(request, self.membership),
        )


class SmsSettingsSaveView(ManagerRequiredView):
    def post(self, request):
        # O plano, antes de qualquer coisa. O gate de verdade esta em
        # `smsdev.resolve_api_key`, por onde todo envio passa; este aqui
        # existe para a clinica nao cadastrar uma chave, apertar "testar" e
        # ficar procurando defeito no proprio celular. O nome do plano vai
        # na mensagem porque "nao incluido" sem dizer em que plano manda a
        # pessoa adivinhar.
        from tenancy.plans import has_sms, plan_label

        tenant = self.membership.tenant
        if not has_sms(tenant.plan):
            messages.error(
                request,
                f'O plano {plan_label(tenant.plan)} nao inclui envio de SMS. '
                f'O aviso por e-mail continua funcionando normalmente.',
            )
            return redirect('messaging:settings')
        tenant_id = request.access_context.tenant_id
        sms = _sms_settings(tenant_id)
        form = SmsSettingsForm(request.POST, instance=sms)
        if not form.is_valid():
            return render(
                request, 'communications/settings.html',
                MessagingSettingsView._context(request, self.membership, sms_form=form),
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
                MessagingSettingsView._context(
                    request, self.membership,
                    email_form=form, email_form_membership=doctor,
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
            .select_related(
                'contact__patient', 'appointment__physician_membership__user',
                'scheduled_return',
            )
            .order_by('-created_at')[:100]
        )
        return render(request, 'communications/deliveries.html', {
            'deliveries': deliveries,
            'settings_url': reverse('messaging:settings'),
        })


# --------------------------------------------------------------------------
# Servidor de e-mail da clínica
# --------------------------------------------------------------------------

class ClinicEmailSaveView(ManagerRequiredView):
    """Grava o SMTP da clínica — o remetente padrão de todos os envios."""

    def post(self, request):
        from .forms import ClinicEmailSettingsForm

        tenant_id = request.access_context.tenant_id
        row = _sms_settings(tenant_id)
        form = ClinicEmailSettingsForm(request.POST, instance=row)
        if not form.is_valid():
            return render(
                request, 'communications/settings.html',
                MessagingSettingsView._context(
                    request, self.membership, clinic_email_form=form,
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
        saved.updated_by = self.membership
        saved.full_clean()
        saved.save()
        record_audit_event(
            request.user, tenant_id, 'communications.clinic_email_settings_updated',
            object_type='tenant', object_id=tenant_id, outcome='success',
            integrity_metadata={
                'enabled': saved.email_enabled, 'from_email': saved.email_from_address,
                'own_server': saved.uses_own_smtp, 'password_changed': bool(entered),
            },
        )
        messages.success(request, 'Servidor de e-mail da clínica salvo.')
        return redirect('messaging:settings')


class ClinicEmailTestView(ManagerRequiredView):
    """Testa a conexão e, se pedido, manda um e-mail de verdade.

    São duas provas diferentes e a distinção importa. Abrir a conexão prova
    que o servidor aceita a senha. Só o envio real revela remetente recusado
    por SPF, domínio sem DKIM e caixa que joga tudo em spam — e é aí que o
    paciente deixa de receber a receita.
    """

    def post(self, request):
        from .email import EmailSendFailed, send_test_email, verify_connection
        from .email import resolve_sender
        from .forms import EmailTestForm

        tenant_id = request.access_context.tenant_id
        row = _sms_settings(tenant_id)
        if not row.email_enabled or not row.email_from_address:
            messages.warning(
                request,
                'Configure e ative o servidor de e-mail da clínica antes de testar.',
            )
            return redirect('messaging:settings')

        sender = resolve_sender(tenant_id=tenant_id)
        if row.uses_own_smtp:
            try:
                verify_connection(sender)
            except EmailSendFailed as exc:
                messages.error(request, f'A conexão SMTP falhou: {exc}')
                return redirect('messaging:settings')

        form = EmailTestForm(request.POST)
        if not form.is_valid():
            messages.error(
                request,
                'Informe um endereço válido para receber o e-mail de teste.',
            )
            return redirect('messaging:settings')

        destino = form.cleaned_data['to_email']
        try:
            send_test_email(destino, tenant_id=tenant_id, label='da clínica')
        except EmailSendFailed as exc:
            messages.error(request, f'O envio falhou: {exc}')
            return redirect('messaging:settings')

        record_audit_event(
            request.user, tenant_id, 'communications.clinic_email_tested',
            object_type='tenant', object_id=tenant_id, outcome='success',
        )
        messages.success(
            request,
            f'E-mail de teste enviado para {destino}. Confira a caixa de entrada — '
            'e a de spam, que é onde remetente novo costuma cair.',
        )
        return redirect('messaging:settings')


# --------------------------------------------------------------------------
# Comunicação em massa
# --------------------------------------------------------------------------

class CampaignListView(ManagerRequiredView):
    """Campanhas da clínica e o tamanho da base que consentiu."""

    def get(self, request):
        from .marketing import eligible_contacts
        from .models import MarketingCampaign

        tenant_id = request.access_context.tenant_id
        campanhas = list(
            MarketingCampaign.objects.filter(tenant_id=tenant_id)
            .select_related('created_by__user')
            .order_by('-created_at')[:50]
        )
        from patients.models import PatientContact

        consentiram = eligible_contacts(tenant_id).count()
        descadastrados = PatientContact.objects.filter(
            tenant_id=tenant_id, marketing_opt_out_at__isnull=False,
        ).count()
        com_email = PatientContact.objects.filter(
            tenant_id=tenant_id,
        ).exclude(email='').count()
        return render(request, 'communications/campaigns.html', {
            'campaigns': campanhas,
            'consented': consentiram,
            'unsubscribed': descadastrados,
            'with_email': com_email,
            'without_consent': max(0, com_email - consentiram - descadastrados),
        })


class CampaignCreateView(ManagerRequiredView):
    def get(self, request):
        from .forms import MarketingCampaignForm

        return render(request, 'communications/campaign_form.html', {
            'form': MarketingCampaignForm(),
        })

    def post(self, request):
        from .forms import MarketingCampaignForm
        from .marketing import build_recipients

        form = MarketingCampaignForm(request.POST)
        if not form.is_valid():
            return render(request, 'communications/campaign_form.html', {'form': form})
        campaign = form.save(commit=False)
        campaign.tenant_id = request.access_context.tenant_id
        campaign.created_by = self.membership
        campaign.save()
        total = build_recipients(campaign)
        record_audit_event(
            request.user, campaign.tenant_id, 'communications.campaign_created',
            object_type='marketing_campaign', object_id=campaign.id, outcome='success',
            integrity_metadata={'recipients': total},
        )
        if not total:
            messages.warning(
                request,
                'A campanha foi criada, mas nenhum contato consentiu em receber '
                'comunicação em massa. Registre o consentimento na ficha do paciente '
                'antes de disparar.',
            )
        else:
            messages.success(request, f'Campanha criada com {total} destinatário(s).')
        return redirect('messaging:campaign-detail', campaign_id=campaign.id)


class CampaignDetailView(ManagerRequiredView):
    def _campaign(self, request, campaign_id):
        from .models import MarketingCampaign

        return get_object_or_404(
            MarketingCampaign, id=campaign_id, tenant_id=request.access_context.tenant_id,
        )

    def get(self, request, campaign_id):
        from .models import RecipientStatus

        campaign = self._campaign(request, campaign_id)
        falhas = list(
            campaign.recipients.filter(status=RecipientStatus.FAILED)
            .select_related('contact__patient')[:50]
        )
        pulados = list(
            campaign.recipients.filter(status=RecipientStatus.SKIPPED)
            .select_related('contact__patient')[:50]
        )
        return render(request, 'communications/campaign_detail.html', {
            'campaign': campaign, 'counts': campaign.counts,
            'delivery_rate': campaign.delivery_rate,
            'failed': falhas, 'skipped': pulados,
        })


class CampaignActionView(ManagerRequiredView):
    """Disparar, pausar e retomar."""

    def post(self, request, campaign_id, action):
        from .marketing import CampaignBlocked, pause, start
        from .models import CampaignStatus, MarketingCampaign

        campaign = get_object_or_404(
            MarketingCampaign, id=campaign_id, tenant_id=request.access_context.tenant_id,
        )
        if action == 'pausar':
            pause(campaign, request.user)
            messages.success(
                request,
                'Campanha pausada. Quem já recebeu não recebe de novo ao retomar.',
            )
            return redirect('messaging:campaign-detail', campaign_id=campaign.id)

        if action not in ('disparar', 'retomar'):
            raise Http404
        try:
            start(campaign, request.user)
        except CampaignBlocked as exc:
            messages.error(request, str(exc))
            return redirect('messaging:campaign-detail', campaign_id=campaign.id)
        messages.success(
            request,
            f'Envio iniciado, {campaign.per_minute} mensagem(ns) por minuto. '
            'Acompanhe a taxa de entrega nesta tela.',
        )
        return redirect('messaging:campaign-detail', campaign_id=campaign.id)


class CampaignTestView(ManagerRequiredView):
    """Manda a campanha para um endereço só, antes do disparo.

    Ver a mensagem como ela chega é a única forma de perceber o assunto
    cortado, o link quebrado e o rodapé duplicado — e, depois de mil
    pessoas receberem, não há como desfazer.
    """

    def post(self, request, campaign_id):
        from .email import EmailSendFailed, send_email
        from .forms import EmailTestForm
        from .models import MarketingCampaign

        campaign = get_object_or_404(
            MarketingCampaign, id=campaign_id, tenant_id=request.access_context.tenant_id,
        )
        form = EmailTestForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Informe um endereço válido para o teste.')
            return redirect('messaging:campaign-detail', campaign_id=campaign.id)

        destino = form.cleaned_data['to_email']
        tenant = self.membership.tenant
        nome = tenant.trade_name or tenant.legal_name
        corpo = (
            f'{campaign.body_text}\n\n'
            '---\n'
            f'Você recebeu esta mensagem porque autorizou {nome} a enviar comunicações.\n'
            'Para não receber mais, acesse: (link de descadastro, individual por contato)\n'
            'Esta é uma mensagem de divulgação. Para assuntos do seu atendimento, '
            'use os canais de sempre da clínica.\n'
        )
        try:
            send_email(destino, f'[TESTE] {campaign.subject}', corpo,
                       tenant_id=campaign.tenant_id)
        except EmailSendFailed as exc:
            messages.error(request, f'O envio de teste falhou: {exc}')
            return redirect('messaging:campaign-detail', campaign_id=campaign.id)
        messages.success(
            request,
            f'Teste enviado para {destino}. O rodapé real traz o link de descadastro '
            'próprio de cada contato.',
        )
        return redirect('messaging:campaign-detail', campaign_id=campaign.id)
