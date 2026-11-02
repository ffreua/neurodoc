import re

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .invitations import consume_invitation
from .models import InvitationPurpose, Membership, MembershipStatus, Role, Tenant


class EmailDescartavel(Exception):
    """O e-mail da conta nova é de serviço descartável (`catalogs.descartaveis`).

    Os formulários já recusam com a mensagem da tela; esta é a barreira que
    vale para quem chamar o serviço por outro caminho — o mesmo desenho de
    `PlanLimitReached`, conferido na tela e de novo onde a conta nasce.
    """


class EmailAlreadyRegistered(Exception):
    pass


def _unique_slug(base_text):
    from .models import RESERVED_SLUGS

    # O corte em 55 pode cair logo depois de um hífen ("...-de-tal-"), e
    # `SLUG_RE` recusa hífen nas pontas: o `full_clean` do cadastro subia
    # com erro 500 para razão social longa sem nome fantasia — o caso
    # típico do médico pessoa física, que usa o nome completo (revisão de
    # 2026-11-02).
    base = slugify(base_text)[:55].strip('-') or 'clinica'
    candidate = base
    suffix = 1
    while Tenant.objects.filter(slug=candidate).exists() or candidate in RESERVED_SLUGS:
        suffix += 1
        candidate = f'{base}-{suffix}'
    return candidate


class InvalidInvitation(Exception):
    pass


@transaction.atomic
def accept_platform_invitation(token, email, password, legal_name, documento, trade_name='',
                               contract_ip=None, contract_user_agent='',
                               contract_powers=False):
    """Consumes a platform invitation and creates org+owner atomically.

    If organization creation fails for any reason (duplicate e-mail,
    invalid CNPJ, ...), the invitation consumption rolls back with it, so a
    failed signup never burns a one-time invite.

    `documento` é o CNPJ da clínica ou o CPF do médico que atende como
    pessoa física (2026-11), reconhecido pelo número de dígitos — onze é
    CPF, o resto vai para o CNPJ e é validado como tal por `full_clean`.

    O aceite do contrato entra **aqui dentro**, e nao numa chamada
    seguinte na view: uma clinica criada e um aceite que falhou depois
    seria uma organizacao usando o sistema sem contrato registrado, e
    ninguem descobriria antes de precisar do contrato.
    """
    from accounts.models import User
    from exams.provisioning import ensure_default_template

    from catalogs.descartaveis import e_descartavel

    from .contracts import registrar_aceite

    invitation = consume_invitation(token, consumed_by=None, expected_purpose=InvitationPurpose.PLATFORM)
    if invitation is None:
        raise InvalidInvitation(token)

    email = email.strip().lower()
    if User.objects.filter(email=email).exists():
        raise EmailAlreadyRegistered(email)
    if e_descartavel(email):
        raise EmailDescartavel(email)
    user = User.objects.create_user(email=email, password=password)
    digitos = re.sub(r'\D', '', documento or '')
    pessoa_fisica = len(digitos) == 11
    tenant = Tenant(
        legal_name=legal_name,
        trade_name=trade_name,
        cnpj='' if pessoa_fisica else digitos,
        cpf=digitos if pessoa_fisica else '',
        slug=_unique_slug(trade_name or legal_name),
        # O plano vem do convite, e não escrito aqui. Com `'free'` fixo,
        # quem vendesse o Completo teria de corrigir o plano à mão depois
        # de o cliente entrar — e ninguém saberia dizer se ele está no
        # plano certo sem perguntar a quem vendeu.
        plan=invitation.plan,
        patient_limit_override=invitation.patient_limit_override,
        doctor_limit_override=invitation.doctor_limit_override,
        plan_note=invitation.plan_note,
    )
    tenant.full_clean()
    tenant.save()
    membership = Membership.objects.create(
        tenant=tenant, user=user, roles=[Role.OWNER],
        status=MembershipStatus.ACTIVE, activated_at=timezone.now(),
    )
    invitation.consumed_by = user
    invitation.save(update_fields=['consumed_by'])
    aceite = registrar_aceite(
        tenant, user, plan=invitation.plan,
        ip=contract_ip, user_agent=contract_user_agent,
        poderes_declarados=contract_powers, periodicidade=invitation.periodicidade,
    )
    # A clínica nasce pronta para atender: sem isto, o primeiro exame
    # neurológico abre num aviso pedindo um comando de terminal.
    ensure_default_template(tenant.id)
    return user, tenant, membership, aceite


class InvitationEmailMismatch(Exception):
    pass


def _assert_doctor_vacancy(invitation):
    """O convite traz o papel médico? Então a clínica precisa ter vaga.

    A emissão já conferiu (`tenancy/admin_views.py`), e esta é a
    verificação que vale: entre emitir e aceitar cabem sete dias, e a
    última vaga pode ter sido ocupada nesse meio-tempo. Sem ela, o convite
    emitido sob o limite de ontem entraria acima do limite de hoje.
    """
    from .limits import assert_can_add_doctor

    if Role.DOCTOR in (invitation.role_grants or []):
        assert_can_add_doctor(invitation.target_tenant)


@transaction.atomic
def accept_collaborator_invitation_for_user(token, user):
    """Adds a Membership to an already-authenticated user's own account.

    This is the 'vinculação autorizada' path: an existing account gains a
    new tenant relationship, never a duplicate account.
    """
    invitation = consume_invitation(token, consumed_by=user, expected_purpose=InvitationPurpose.COLLABORATOR)
    if invitation is None:
        raise InvalidInvitation(token)
    if invitation.email_binding and invitation.email_binding != user.email:
        raise InvitationEmailMismatch(token)
    _assert_doctor_vacancy(invitation)
    membership, created = Membership.objects.get_or_create(
        tenant=invitation.target_tenant, user=user,
        defaults={
            'roles': invitation.role_grants, 'status': MembershipStatus.ACTIVE,
            'activated_at': timezone.now(), 'invited_by': invitation.issued_by,
        },
    )
    if not created:
        # A conta e o vínculo continuam sendo os mesmos para preservar
        # autoria e auditoria. O convite novo, porém, é a autorização atual:
        # ele substitui os papéis antigos e encerra a revogação.
        membership.roles = list(invitation.role_grants)
        membership.status = MembershipStatus.ACTIVE
        membership.activated_at = timezone.now()
        membership.revoked_at = None
        membership.invited_by = invitation.issued_by
        membership.row_version += 1
        membership.save(update_fields=[
            'roles', 'status', 'activated_at', 'revoked_at', 'invited_by',
            'row_version', 'updated_at',
        ])
    return membership


@transaction.atomic
def accept_collaborator_invitation_new_user(token, email, password):
    from accounts.models import User

    invitation = consume_invitation(token, consumed_by=None, expected_purpose=InvitationPurpose.COLLABORATOR)
    if invitation is None:
        raise InvalidInvitation(token)
    email = email.strip().lower()
    if invitation.email_binding and invitation.email_binding != email:
        raise InvitationEmailMismatch(token)
    if User.objects.filter(email=email).exists():
        raise EmailAlreadyRegistered(email)
    from catalogs.descartaveis import e_descartavel

    if e_descartavel(email):
        raise EmailDescartavel(email)
    _assert_doctor_vacancy(invitation)
    user = User.objects.create_user(email=email, password=password)
    membership = Membership.objects.create(
        tenant=invitation.target_tenant, user=user, roles=invitation.role_grants,
        status=MembershipStatus.ACTIVE, activated_at=timezone.now(), invited_by=invitation.issued_by,
    )
    invitation.consumed_by = user
    invitation.save(update_fields=['consumed_by'])
    return user, membership
