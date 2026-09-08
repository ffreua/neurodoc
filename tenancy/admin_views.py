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

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from accounts.models import PhysicianProfile
from accounts.services import revoke_membership
from audit.services import record_audit_event

from . import branding
from .forms import (
    ClinicProfileForm, CollaboratorInvitationForm, MembershipRolesForm, PhysicianProfileForm,
)
from .invitations import issue_invitation
from .models import (
    ClinicProfile, Invitation, InvitationPurpose, Membership, MembershipStatus, Role, Tenant,
)
from .permissions import Capability, CapabilityRequiredView


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
        invitation, raw_token = issue_invitation(
            InvitationPurpose.COLLABORATOR, issued_by=request.user, target_tenant=tenant,
            email_binding=email, role_grants=form.cleaned_data['roles'],
        )
        record_audit_event(
            request.user, tenant, 'tenancy.collaborator_invited', object_type='invitation',
            object_id=invitation.id, outcome='success',
            integrity_metadata={'roles': form.cleaned_data['roles']},
        )
        return render(request, 'tenancy/collaborator_invited.html', {
            'token': raw_token, 'invitation': invitation,
        })


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
    """

    required_capability = None

    def get(self, request):
        profile = ClinicProfile.objects.filter(
            tenant_id=request.access_context.tenant_id,
        ).first()
        content = branding.read_logo(profile)
        if content is None:
            raise Http404
        response = HttpResponse(content, content_type=profile.logo_mime)
        response['Cache-Control'] = 'private, max-age=300'
        response['X-Content-Type-Options'] = 'nosniff'
        # Impede que a imagem seja interpretada como página caso alguém a
        # abra direto: conteúdo enviado por usuário servido do mesmo domínio.
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'"
        return response
