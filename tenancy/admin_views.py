"""Área do responsável pela clínica: equipe, convites e identidade.

Quem entra aqui tem `MANAGE_ORGANIZATION` — hoje só o `owner`. É a tela em
que se decide quem tem acesso e a quê, e por isso ela é a única que
concede papel: as demais consomem a matriz de `tenancy.permissions`, esta
a alimenta.

Separada de `views.py` porque aquele arquivo atende o outro lado do mesmo
assunto — a página pública em que a pessoa convidada aceita o convite, sem
sessão e sem organização escolhida. Misturar as duas num arquivo só
misturaria a tela que exige ser dono com a tela que qualquer um abre.
"""

import logging

from django.contrib import messages
from django.conf import settings
from django.core.mail import send_mail
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import get_conditional_response
from django.views import View

from accounts import mfa
from accounts.models import PhysicianProfile, RecoveryCode
from accounts.services import invalidate_user_sessions, revoke_membership, send_password_reset
from django_otp.plugins.otp_totp.models import TOTPDevice
from audit.services import record_audit_event

from . import branding, clinic_messages
from .forms import (
    ClinicMessageForm, ClinicPortalForm, ClinicProfileForm, CollaboratorInvitationForm,
    MembershipRolesForm, PhysicianProfileForm,
)
from .invitations import (
    collaborator_invitation_url, issue_invitation, send_collaborator_invitation,
)
from .limits import PlanLimitReached, assert_can_add_doctor
from .models import (
    ClinicMessageKind, ClinicProfile, Invitation, InvitationPurpose, Membership,
    MembershipStatus, Role, Tenant,
)
from .permissions import Capability, CapabilityRequiredView

logger = logging.getLogger(__name__)


class OrgAdminView(CapabilityRequiredView):
    required_capability = Capability.MANAGE_ORGANIZATION

    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        self.membership = Membership.objects.filter(
            id=request.access_context.membership_id,
        ).select_related('user', 'tenant').first()
        if self.membership is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    @property
    def tenant_id(self):
        return self.request.access_context.tenant_id


def clinic_profile_for(tenant_id):
    profile, _ = ClinicProfile.objects.get_or_create(tenant_id=tenant_id)
    return profile


def _team_rows(tenant_id):
    """A equipe com o que cada vínculo de fato consegue fazer.

    A tela antiga listava e-mail, papéis e estado. Faltava a informação que
    mais causa dúvida: por que aquele médico não consegue assinar. O papel
    `doctor` aparecia igual para quem assina e para quem não assina, e a
    diferença — `PhysicianProfile` verificado — não estava em lugar nenhum
    do sistema. Quem administra ficava sem resposta e sem caminho.
    """
    memberships = list(
        Membership.objects.filter(tenant_id=tenant_id)
        .select_related('user').order_by('user__first_name', 'user__email')
    )
    profiles = {
        profile.user_id: profile
        for profile in PhysicianProfile.objects.filter(
            user_id__in=[m.user_id for m in memberships],
        )
    }
    mfa_user_ids = set(
        TOTPDevice.objects.filter(
            user_id__in=[m.user_id for m in memberships], confirmed=True,
        ).values_list('user_id', flat=True)
    )
    rows = []
    for membership in memberships:
        profile = profiles.get(membership.user_id)
        is_doctor = Role.DOCTOR in (membership.roles or [])
        blocker = ''
        if is_doctor:
            # O vínculo vem primeiro: revogado ou suspenso, nada mais
            # importa. Sem esta linha a tela anunciava "Assina documento"
            # ao lado de um vínculo revogado — dizendo a quem administra
            # exatamente o contrário do que o sistema faz.
            if not membership.is_active():
                blocker = f'Vínculo {membership.get_status_display().lower()}.'
            elif profile is None:
                blocker = 'Sem registro profissional cadastrado.'
            elif profile.verification_status == PhysicianProfile.VerificationStatus.PENDING:
                blocker = 'Registro profissional aguardando validação.'
            elif profile.verification_status == PhysicianProfile.VerificationStatus.REJECTED:
                blocker = 'Registro profissional recusado na validação.'
        rows.append({
            'membership': membership,
            'profile': profile,
            'is_doctor': is_doctor,
            'can_sign': is_doctor and not blocker,
            'signing_blocker': blocker,
            'has_mfa': membership.user_id in mfa_user_ids,
            'roles_form': MembershipRolesForm(initial={'roles': membership.roles or []}),
            # Formulário do registro profissional só para quem tem o papel:
            # instanciar para toda a equipe montaria um formulário por
            # secretária, que a tela não usa.
            'profile_form': PhysicianProfileForm(
                instance=profile,
                initial=None if profile else {
                    # O nome que já se conhece, para não redigitar. O médico
                    # corrige se assina de outro jeito.
                    'professional_name': membership.user.get_full_name(),
                    'professional_email': membership.user.email,
                },
            ) if is_doctor else None,
        })
    return rows


def _pending_invitations(tenant_id):
    """Convites emitidos e ainda não usados.

    Eram invisíveis: o token aparecia uma vez na tela e sumia. Quem
    administra não tinha como saber que já havia convidado alguém, nem
    cancelar um convite emitido por engano — e o convite continuava válido
    por sete dias.
    """
    now = timezone.now()
    return list(
        Invitation.objects.filter(
            target_tenant_id=tenant_id, purpose=InvitationPurpose.COLLABORATOR,
            consumed_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now,
        ).select_related('issued_by').order_by('-created_at')
    )


class TeamView(OrgAdminView):
    """Equipe, convites pendentes e concessão de papel."""

    def _context(self, request, **overrides):
        context = {
            'rows': _team_rows(self.tenant_id),
            'invitations': _pending_invitations(self.tenant_id),
            'invite_form': CollaboratorInvitationForm(),
            'tenant': self.membership.tenant,
        }
        context.update(overrides)
        return context

    def get(self, request):
        return render(request, 'tenancy/team.html', self._context(request))

    def post(self, request):
        form = CollaboratorInvitationForm(request.POST)
        if not form.is_valid():
            return render(request, 'tenancy/team.html', self._context(request, invite_form=form))
        email = form.cleaned_data['email']
        existing = Membership.objects.filter(
            tenant_id=self.tenant_id, user__email__iexact=email,
        ).exclude(status=MembershipStatus.REVOKED).first()
        if existing is not None:
            # Convidar quem já está dentro cria um segundo vínculo que a
            # restrição de banco recusa depois da pessoa clicar no link —
            # ou seja, o erro apareceria para o convidado, não para quem
            # convidou. Melhor recusar aqui, onde dá para corrigir.
            form.add_error(
                'email',
                'Esta pessoa já tem vínculo nesta organização. '
                'Use "Alterar papéis" na lista da equipe.',
            )
            return render(request, 'tenancy/team.html', self._context(request, invite_form=form))

        tenant = Tenant.objects.get(id=self.tenant_id)
        if Role.DOCTOR in form.cleaned_data['roles']:
            # Conferido aqui, e de novo no aceite. Esta é a que evita o
            # constrangimento: sem ela, o convidado descobriria o limite
            # depois de clicar no link, e quem pode resolvê-lo é o dono da
            # clínica, não ele. A do aceite continua sendo a autoritativa —
            # a última vaga pode ter sido tomada nesse meio-tempo.
            try:
                assert_can_add_doctor(tenant)
            except PlanLimitReached as limite:
                form.add_error('roles', limite.message())
                return render(request, 'tenancy/team.html',
                              self._context(request, invite_form=form))
        invitation, raw_token = issue_invitation(
            InvitationPurpose.COLLABORATOR, issued_by=request.user, target_tenant=tenant,
            email_binding=email, role_grants=form.cleaned_data['roles'],
        )
        record_audit_event(
            request.user, tenant, 'tenancy.collaborator_invited', object_type='invitation',
            object_id=invitation.id, outcome='success',
            integrity_metadata={'roles': form.cleaned_data['roles']},
        )
        invitation_url = collaborator_invitation_url(request, raw_token)
        email_sent = True
        try:
            send_collaborator_invitation(invitation, raw_token, request)
        except Exception:
            logger.exception(
                'Falha ao enviar convite de colaborador',
                extra={'invitation_id': str(invitation.id), 'tenant_id': str(tenant.id)},
            )
            email_sent = False
        return render(request, 'tenancy/collaborator_invited.html', {
            'token': raw_token, 'invitation': invitation,
            'invitation_url': invitation_url, 'email_sent': email_sent,
        })


class MembershipPasswordResetView(OrgAdminView):
    def post(self, request, membership_id):
        membership = get_object_or_404(
            Membership.objects.select_related('user', 'tenant'),
            id=membership_id, tenant_id=self.tenant_id, status=MembershipStatus.ACTIVE,
        )
        sent = send_password_reset(membership.user, request)
        record_audit_event(
            request.user, membership.tenant, 'accounts.password_reset_requested_by_owner',
            object_type='membership', object_id=membership.id,
            outcome='success' if sent else 'failure',
        )
        if sent:
            messages.success(request, f'Redefinição de senha enviada para {membership.user.email}.')
        else:
            messages.error(request, 'Não foi possível iniciar a redefinição de senha.')
        return redirect('tenancy:team')


class MembershipMFAResetView(OrgAdminView):
    def post(self, request, membership_id):
        membership = get_object_or_404(
            Membership.objects.select_related('user', 'tenant'),
            id=membership_id, tenant_id=self.tenant_id, status=MembershipStatus.ACTIVE,
        )
        if membership.id == self.membership.id:
            messages.error(request, 'O responsável não pode resetar o próprio MFA por esta tela.')
            return redirect('tenancy:team')
        code = request.POST.get('code', '').strip()
        if not (mfa.verify_totp_token(request.user, code) or mfa.consume_recovery_code(request.user, code)):
            record_audit_event(
                request.user, membership.tenant, 'accounts.mfa_reset_by_owner',
                object_type='membership', object_id=membership.id, outcome='denied',
            )
            messages.error(request, 'Código MFA do responsável inválido.')
            return redirect('tenancy:team')

        TOTPDevice.objects.filter(user=membership.user).delete()
        RecoveryCode.objects.filter(user=membership.user).delete()
        invalidate_user_sessions(membership.user)
        record_audit_event(
            request.user, membership.tenant, 'accounts.mfa_reset_by_owner',
            object_type='membership', object_id=membership.id, outcome='success',
        )
        send_mail(
            subject='Seu MFA foi resetado — NeuroDoc',
            message=(
                f'O responsável por {membership.tenant.legal_name} resetou seu segundo fator. '
                'Entre novamente e configure um novo autenticador. Se você não reconhece esta ação, '
                'contate a clínica imediatamente.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[membership.user.email],
        )
        messages.success(request, f'MFA de {membership.user.email} resetado; sessões encerradas.')
        return redirect('tenancy:team')


class MembershipRolesView(OrgAdminView):
    """Altera os papéis de um vínculo existente."""

    def post(self, request, membership_id):
        membership = get_object_or_404(
            Membership, id=membership_id, tenant_id=self.tenant_id,
        )
        form = MembershipRolesForm(request.POST)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('tenancy:team')

        previous = list(membership.roles or [])
        # Ganhar o papel de médico ocupa vaga do plano; perdê-lo, libera.
        # A conta é sobre o **ganho**: um vínculo que já era médico e está
        # só trocando de secretaria para gestora não deve ser recusado por
        # uma cota que ele próprio já ocupa.
        if Role.DOCTOR in form.cleaned_data['roles'] and Role.DOCTOR not in previous:
            try:
                assert_can_add_doctor(self.tenant_id)
            except PlanLimitReached as limite:
                messages.error(request, limite.message())
                return redirect('tenancy:team')
        membership.roles = form.cleaned_data['roles']
        membership.row_version += 1
        membership.save(update_fields=['roles', 'row_version', 'updated_at'])
        record_audit_event(
            request.user, membership.tenant, 'tenancy.membership_roles_changed',
            object_type='membership', object_id=membership.id, outcome='success',
            integrity_metadata={'from': previous, 'to': membership.roles},
        )
        name = membership.user.get_full_name() or membership.user.email
        gained_doctor = Role.DOCTOR in membership.roles and Role.DOCTOR not in previous
        note = ''
        if gained_doctor and not membership.can_practice_clinically():
            # Conceder o papel não habilita a assinar, e quem acabou de
            # concedê-lo precisa saber disso agora — não quando o médico
            # tentar emitir a primeira receita.
            note = (
                ' O papel de médico foi concedido, mas a assinatura de documento '
                'só é liberada depois do registro profissional validado.'
            )
        messages.success(request, f'Papéis de {name} atualizados.{note}')
        return redirect('tenancy:team')


class MembershipStatusView(OrgAdminView):
    """Suspende, reativa ou revoga um vínculo.

    Suspender é diferente de revogar, e a distinção é prática: férias,
    afastamento e licença tiram o acesso por um tempo e o devolvem depois.
    Só revogar obrigaria a convidar a pessoa de novo — e o vínculo novo não
    é o mesmo vínculo, o que quebra a leitura de quem assinou o quê.
    """

    ACTIONS = {'suspend', 'reactivate', 'revoke'}

    def post(self, request, membership_id, action):
        if action not in self.ACTIONS:
            raise Http404
        membership = get_object_or_404(
            Membership, id=membership_id, tenant_id=self.tenant_id,
        )
        name = membership.user.get_full_name() or membership.user.email

        if membership.id == self.membership.id:
            # Quem administra não pode se derrubar: um dono que revoga o
            # próprio vínculo deixa a clínica sem ninguém para conceder
            # papel, e a saída passa a ser mexer no banco.
            messages.error(
                request,
                'Você não pode alterar o próprio vínculo. Peça a outro '
                'responsável, para a organização não ficar sem administração.',
            )
            return redirect('tenancy:team')

        if action == 'revoke':
            revoke_membership(membership, request.user)
            messages.success(request, f'Vínculo de {name} revogado.')
            return redirect('tenancy:team')

        target = (
            MembershipStatus.SUSPENDED if action == 'suspend' else MembershipStatus.ACTIVE
        )
        if membership.status == MembershipStatus.REVOKED:
            messages.error(
                request,
                f'O vínculo de {name} está revogado. Para devolver o acesso, '
                'envie um convite novo.',
            )
            return redirect('tenancy:team')
        # Reativar um vínculo médico volta a ocupar vaga. Suspender libera
        # — é o que permite a clínica no limite acomodar quem volta de
        # férias sem revogar o vínculo de ninguém, que apagaria a trilha.
        if target == MembershipStatus.ACTIVE and Role.DOCTOR in (membership.roles or []):
            try:
                assert_can_add_doctor(self.tenant_id)
            except PlanLimitReached as limite:
                messages.error(request, limite.message())
                return redirect('tenancy:team')
        membership.status = target
        if target == MembershipStatus.ACTIVE and membership.activated_at is None:
            membership.activated_at = timezone.now()
        membership.row_version += 1
        membership.save(update_fields=['status', 'activated_at', 'row_version', 'updated_at'])
        record_audit_event(
            request.user, membership.tenant, f'tenancy.membership_{action}d',
            object_type='membership', object_id=membership.id, outcome='success',
        )
        messages.success(
            request,
            f'Acesso de {name} suspenso.' if action == 'suspend'
            else f'Acesso de {name} reativado.',
        )
        return redirect('tenancy:team')


class InvitationRevokeView(OrgAdminView):
    def post(self, request, invitation_id):
        invitation = get_object_or_404(
            Invitation, id=invitation_id, target_tenant_id=self.tenant_id,
            purpose=InvitationPurpose.COLLABORATOR, consumed_at__isnull=True,
        )
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=['revoked_at', 'updated_at'])
        record_audit_event(
            request.user, invitation.target_tenant, 'tenancy.invitation_revoked',
            object_type='invitation', object_id=invitation.id, outcome='success',
        )
        messages.success(
            request, f'Convite para {invitation.email_binding} cancelado. O link parou de valer.',
        )
        return redirect('tenancy:team')


class PhysicianProfileView(OrgAdminView):
    """Registro profissional do médico, cadastrado por quem administra.

    Cadastrar e validar são ações separadas, e de propósito: gravar corrige
    um dado digitado errado, validar afirma que o CRM foi conferido junto ao
    conselho e libera a assinatura de receita. Juntas num botão só, a
    segunda aconteceria por efeito colateral da primeira — bastaria corrigir
    um telefone para reafirmar uma conferência que ninguém refez.

    Mudar CRM ou UF de um registro já validado devolve o estado para
    pendente: o que foi conferido é o número, não a pessoa.
    """

    def post(self, request, membership_id):
        membership = get_object_or_404(
            Membership, id=membership_id, tenant_id=self.tenant_id,
        )
        if Role.DOCTOR not in (membership.roles or []):
            messages.error(
                request,
                'Registro profissional só se aplica a quem tem o papel de médico.',
            )
            return redirect('tenancy:team')

        profile = PhysicianProfile.objects.filter(user_id=membership.user_id).first()
        # O CRM de antes é lido agora, antes de validar.
        #
        # `ModelForm` com `instance` escreve os dados enviados **no próprio
        # objeto** durante `is_valid()` — `form.instance` e `profile` são o
        # mesmo objeto em memória. Comparar depois compararia o valor novo
        # com ele mesmo: a troca de CRM passava despercebida e o registro
        # continuava valendo como verificado para um número que ninguém
        # conferiu.
        previous_identity = (
            (profile.crm_number, profile.crm_state) if profile is not None else None
        )
        form = PhysicianProfileForm(request.POST, instance=profile)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('tenancy:team')

        identity_changed = previous_identity is not None and previous_identity != (
            form.cleaned_data['crm_number'], form.cleaned_data['crm_state'],
        )
        saved = form.save(commit=False)
        saved.user_id = membership.user_id
        if profile is None or identity_changed:
            saved.verification_status = PhysicianProfile.VerificationStatus.PENDING
        saved.full_clean()
        saved.save()
        record_audit_event(
            request.user, membership.tenant, 'accounts.physician_profile_saved',
            object_type='membership', object_id=membership.id, outcome='success',
            integrity_metadata={
                'crm': f'{saved.crm_number}/{saved.crm_state}',
                'reset_to_pending': profile is None or identity_changed,
            },
        )
        name = membership.user.get_full_name() or membership.user.email
        if saved.verification_status == PhysicianProfile.VerificationStatus.VERIFIED:
            messages.success(request, f'Registro profissional de {name} atualizado.')
        else:
            messages.success(
                request,
                f'Registro profissional de {name} gravado. Falta validar: '
                'abra "Registro" na linha dele e confirme a conferência do CRM '
                'para liberar a assinatura de documento.',
            )
        return redirect('tenancy:team')


class PhysicianVerificationView(OrgAdminView):
    """Libera (ou recusa) a assinatura de documento por um médico.

    Quem decide é o responsável pela clínica. É ele quem tem a carteira do
    CRM na mão, quem contratou e quem responde pela equipe — e num
    consultório com um médico só não há a quem delegar: o médico é o
    responsável e valida o próprio registro.

    O que sustenta a decisão, então, não é separar quem faz de quem
    confere: é o registro de quem liberou. Fica em `verified_by` e
    `verified_at`, à vista na tela da equipe, e no log de auditoria.
    """

    DECISIONS = {
        'validar': PhysicianProfile.VerificationStatus.VERIFIED,
        'recusar': PhysicianProfile.VerificationStatus.REJECTED,
    }

    def post(self, request, membership_id, decision):
        target = self.DECISIONS.get(decision)
        if target is None:
            raise Http404
        membership = get_object_or_404(
            Membership, id=membership_id, tenant_id=self.tenant_id,
        )
        profile = PhysicianProfile.objects.filter(user_id=membership.user_id).first()
        if profile is None:
            messages.error(
                request,
                'Cadastre o registro profissional antes de validá-lo.',
            )
            return redirect('tenancy:team')

        previous = profile.verification_status
        profile.verification_status = target
        profile.verified_by = request.user
        profile.verified_at = timezone.now()
        profile.verification_note = (request.POST.get('note') or '')[:255]
        profile.save(update_fields=[
            'verification_status', 'verified_by', 'verified_at', 'verification_note',
        ])
        record_audit_event(
            request.user, membership.tenant, 'accounts.physician_verification_changed',
            object_type='membership', object_id=membership.id, outcome='success',
            integrity_metadata={
                'crm': f'{profile.crm_number}/{profile.crm_state}',
                'from': previous, 'to': target,
                # Autovalidação é o caso que se quer poder encontrar depois.
                'self_verified': str(membership.user_id) == str(request.user.id),
            },
        )
        name = membership.user.get_full_name() or membership.user.email
        if target == PhysicianProfile.VerificationStatus.VERIFIED:
            messages.success(
                request,
                f'CRM {profile.crm_number}/{profile.crm_state} validado. '
                f'{name} já assina documento.',
            )
        else:
            messages.success(
                request,
                f'Registro de {name} recusado. A emissão de documento assinado '
                'fica bloqueada até uma nova validação.',
            )
        return redirect('tenancy:team')


# --------------------------------------------------------------------------
# Identidade da clínica
# --------------------------------------------------------------------------

class ClinicProfileView(OrgAdminView):
    """Endereço, contato e logotipo — o cabeçalho do documento."""

    def _context(self, request, **overrides):
        profile = clinic_profile_for(self.tenant_id)
        context = {
            'tenant': self.membership.tenant,
            'profile': profile,
            'form': ClinicProfileForm(instance=profile),
            'portal_form': ClinicPortalForm(instance=profile),
            'portal_url': request.build_absolute_uri(
                reverse('portal:identify', args=[self.membership.tenant.slug])
            ),
            'max_logo_mb': branding.MAX_LOGO_BYTES // (1024 * 1024),
            'accepted_logo': ', '.join(
                mime.split('/')[1].upper() for mime in branding.ALLOWED_LOGO_MIMES
            ),
        }
        context.update(overrides)
        return context

    def get(self, request):
        return render(request, 'tenancy/clinic.html', self._context(request))

    def post(self, request):
        profile = clinic_profile_for(self.tenant_id)
        form = ClinicProfileForm(request.POST, instance=profile)
        if not form.is_valid():
            return render(request, 'tenancy/clinic.html', self._context(request, form=form))
        saved = form.save(commit=False)
        saved.tenant_id = self.tenant_id
        saved.updated_by = self.membership
        saved.full_clean()
        saved.save()
        record_audit_event(
            request.user, self.membership.tenant, 'tenancy.clinic_profile_updated',
            object_type='tenant', object_id=self.tenant_id, outcome='success',
        )
        messages.success(request, 'Identidade da clínica salva.')
        return redirect('tenancy:clinic')


class ClinicPortalView(ClinicProfileView):
    """Liga e desliga o portal público de solicitações.

    Ação própria, com registro próprio na auditoria: publicar o portal é
    abrir um endereço na internet que aceita CPF e data de nascimento de
    pacientes, e quem responde por isso precisa aparecer na trilha com
    nome e data.
    """

    def post(self, request):
        profile = clinic_profile_for(self.tenant_id)
        antes = profile.patient_portal_enabled
        form = ClinicPortalForm(request.POST, instance=profile)
        if not form.is_valid():
            return render(request, 'tenancy/clinic.html',
                          self._context(request, portal_form=form))
        saved = form.save(commit=False)
        saved.tenant_id = self.tenant_id
        saved.updated_by = self.membership
        saved.full_clean()
        saved.save()
        record_audit_event(
            request.user, self.membership.tenant,
            'tenancy.patient_portal_enabled' if saved.patient_portal_enabled
            else 'tenancy.patient_portal_disabled',
            object_type='tenant', object_id=self.tenant_id, outcome='success',
            integrity_metadata={'was_enabled': antes},
        )
        if saved.patient_portal_enabled and not antes:
            messages.success(
                request,
                'Portal publicado. O endereço já responde a qualquer pessoa — divulgue-o '
                'aos pacientes e acompanhe a fila em Solicitações do portal.',
            )
        elif antes and not saved.patient_portal_enabled:
            messages.success(
                request,
                'Portal despublicado. Os pedidos já recebidos continuam na fila; o '
                'endereço deixa de aceitar novos.',
            )
        else:
            messages.success(request, 'Configuração do portal salva.')
        return redirect('tenancy:clinic')


class ClinicLogoView(OrgAdminView):
    """Envia ou remove o logotipo."""

    def post(self, request):
        profile = clinic_profile_for(self.tenant_id)
        if request.POST.get('action') == 'remove':
            branding.discard_logo(profile)
            profile.updated_by = self.membership
            profile.save()
            record_audit_event(
                request.user, self.membership.tenant, 'tenancy.clinic_logo_removed',
                object_type='tenant', object_id=self.tenant_id, outcome='success',
            )
            messages.success(
                request,
                'Logotipo removido. Os documentos já emitidos continuam como estão — '
                'a mudança vale para os próximos.',
            )
            return redirect('tenancy:clinic')

        uploaded = request.FILES.get('logo')
        if uploaded is None:
            messages.error(request, 'Escolha um arquivo de imagem.')
            return redirect('tenancy:clinic')
        try:
            branding.store_logo(profile, uploaded.read())
        except branding.LogoRejected as exc:
            messages.error(request, str(exc))
            return redirect('tenancy:clinic')
        profile.updated_by = self.membership
        profile.save()
        record_audit_event(
            request.user, self.membership.tenant, 'tenancy.clinic_logo_updated',
            object_type='tenant', object_id=self.tenant_id, outcome='success',
            integrity_metadata={'mime': profile.logo_mime, 'bytes': profile.logo_bytes},
        )
        messages.success(request, 'Logotipo atualizado.')
        return redirect('tenancy:clinic')


class ClinicLogoFileView(CapabilityRequiredView):
    """Serve o logotipo do inquilino da requisição.

    Não recebe id de organização: o arquivo servido é o da organização da
    sessão. Um endpoint que aceitasse `tenant_id` na URL seria um caminho
    para enumerar e baixar o logotipo de qualquer clínica da instalação —
    e `/data/media` não é servido pelo servidor web justamente por isso.

    Qualquer vínculo ativo pode ver: o logotipo aparece no cabeçalho das
    telas e nos documentos que a própria recepção imprime.

    **O cache é revalidado sempre, e isso é a decisão.** Um endereço só
    pode ficar guardado por tempo fixo no navegador quando a URL diz o que
    ele devolve; esta não diz — o que ela devolve depende do `tenant_id`
    da sessão, que o cache não enxerga. Com `max-age=300`, que foi o que
    esteve no ar, quem atende em duas clínicas trocava de organização e
    via o logotipo da anterior: o nome da clínica no menu mudava (vem do
    HTML, que não é cacheado) e a imagem não (vinha do cache do
    navegador, pela mesma URL e pelo mesmo cookie). Parecia vazamento
    entre inquilinos e não era — o servidor sempre mandou a imagem certa,
    o navegador é que não perguntava.

    `no-cache` não é `no-store`: a imagem continua guardada, só que o
    navegador pergunta antes de usar. Quando nada mudou, a resposta é um
    304 de algumas dezenas de bytes — contra 680 KB de um logotipo real,
    é o mesmo ganho de antes, sem a janela de cinco minutos mostrando a
    clínica errada.

    A alternativa recusada foi pôr um `?v=` com o inquilino na URL do
    menu, que é o que a tela de identidade já fazia com a data do envio.
    Resolve, e foi exatamente o que falhou: a correção mora no template,
    e quem desenhar a próxima tela com o logotipo não tem como saber que
    precisa lembrar dela. Aqui não há o que lembrar.
    """

    required_capability = None

    def get(self, request):
        profile = ClinicProfile.objects.filter(
            tenant_id=request.access_context.tenant_id,
        ).first()
        etag = branding.logo_etag(profile)
        if etag is None:
            raise Http404
        response = get_conditional_response(request, etag=etag)
        if response is None:
            content = branding.read_logo(profile)
            if content is None:
                raise Http404
            response = HttpResponse(content, content_type=profile.logo_mime)
        response['ETag'] = etag
        response['Cache-Control'] = 'private, no-cache'
        response['X-Content-Type-Options'] = 'nosniff'
        # Impede que a imagem seja interpretada como página caso alguém a
        # abra direto: conteúdo enviado por usuário servido do mesmo domínio.
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'"
        return response


class ClinicMessageView(CapabilityRequiredView):
    """Fale com a NeuroDoc, e Envie sugestões.

    Sem capacidade exigida: pedir ajuda e sugerir melhoria são de quem
    usa, e a secretária que passa o dia na agenda costuma ter mais o que
    dizer sobre a agenda do que quem administra a clínica. `None` aqui é
    decisão, não esquecimento (ver `CapabilityRequiredView`).

    Uma view para as duas portas, com o tipo na URL. O que muda entre elas
    é o rótulo, o texto de ajuda e o `kind` gravado — separar em duas
    classes duplicaria o limite, a trilha e o aviso por e-mail para trocar
    duas frases.
    """

    required_capability = None

    #: O que cada porta diz de si. Fica aqui, e não no template, para a
    #: tela e o que se grava não poderem divergir: o rótulo mostrado é o
    #: mesmo `get_kind_display()` que vai no e-mail do console.
    PORTAS = {
        ClinicMessageKind.SUPPORT: {
            'titulo': 'Fale com a NeuroDoc',
            'ajuda': 'Algo não está funcionando, ou você precisa de ajuda para usar '
                     'alguma parte do sistema. Respondemos no e-mail da sua conta.',
            'acao': 'Enviar mensagem',
        },
        ClinicMessageKind.SUGGESTION: {
            'titulo': 'Envie sugestões',
            'ajuda': 'O que faria diferença na sua rotina: um campo que falta, um '
                     'caminho que dá voltas, um relatório que você monta na mão.',
            'acao': 'Enviar sugestão',
        },
    }

    def _porta(self, kind):
        if kind not in self.PORTAS:
            raise Http404
        return self.PORTAS[kind]

    def _membership(self, request):
        from .models import Membership

        return Membership.objects.filter(id=request.access_context.membership_id).first()

    def get(self, request, kind):
        return render(request, 'tenancy/clinic_message.html', {
            'form': ClinicMessageForm(),
            'kind': kind,
            **self._porta(kind),
        })

    def post(self, request, kind):
        porta = self._porta(kind)
        form = ClinicMessageForm(request.POST)
        membership = self._membership(request)
        if membership is None:
            raise Http404

        if not form.is_valid():
            return render(request, 'tenancy/clinic_message.html', {
                'form': form, 'kind': kind, **porta,
            }, status=400)

        # O limite é conferido **depois** da validação, e não antes: quem
        # erra o assunto quatro vezes não mandou mensagem nenhuma, e
        # gastar a cota com tentativa recusada trancaria justamente quem
        # está tendo dificuldade — que é quem mais precisa escrever.
        if clinic_messages.rate_limited(membership.id):
            messages.warning(
                request,
                'Você já mandou algumas mensagens na última hora. Se for urgente, '
                'responda ao e-mail da última que enviamos.',
            )
            return redirect('reporting:dashboard')

        clinic_messages.create(
            request.access_context, membership, kind,
            form.cleaned_data['subject'], form.cleaned_data['body'],
        )
        # Sucesso mesmo quando o aviso por e-mail falha: do ponto de vista
        # de quem escreveu, a mensagem **foi** recebida -- está no banco, e
        # aparece no console. É a mesma escolha do pedido de contato.
        messages.success(
            request,
            'Mensagem enviada. Obrigado — ela chega a quem cuida do sistema.',
        )
        return redirect('reporting:dashboard')
