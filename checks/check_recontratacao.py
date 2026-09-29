"""Recontratar preserva a conta e devolve o acesso com o convite novo."""
import re
import uuid

from django.conf import settings
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from tenancy.models import Invitation, Membership, MembershipStatus, Role, Tenant


falhas = []
tenant = Tenant.objects.get(slug='demo-clinica-a')
owner = (
    Membership.objects
    .filter(tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER])
    .select_related('user')
    .first()
)
if owner is None:
    print('PULADO: demonstração sem responsável ativo')
    raise SystemExit(0)

email = f'recontratacao-{uuid.uuid4().hex[:10]}@example.invalid'
user = User.objects.create_user(email=email, password='Senha-forte-123!')
membership = Membership.objects.create(
    tenant=tenant,
    user=user,
    # O papel antigo não pode sobreviver escondido ao convite novo.
    roles=[Role.DOCTOR],
    status=MembershipStatus.REVOKED,
    activated_at=timezone.now() - timezone.timedelta(days=30),
    revoked_at=timezone.now() - timezone.timedelta(days=2),
)
membership_id = membership.id
invitation = None

try:
    with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
        mail.get_connection()
        mail.outbox.clear()

        print('=== 1. o responsável consegue convidar novamente o e-mail revogado ===')
        admin = Client()
        admin.force_login(owner.user)
        session = admin.session
        session['tenant_id'] = str(tenant.id)
        session.save()
        response = admin.post(
            '/app/org/equipe/',
            {'email': email, 'roles': [Role.SECRETARY, Role.MANAGER, Role.OWNER]},
            secure=True,
        )
        body = response.content.decode('utf-8', 'replace')
        invitation = Invitation.objects.filter(
            target_tenant=tenant, email_binding=email,
        ).latest('created_at')
        match = re.search(r'https://testserver/invite/([^/]+)/', body)
        invite_sent = bool(mail.outbox and mail.outbox[-1].to == [email])
        print(f'  HTTP={response.status_code}  link={bool(match)}  e-mail={invite_sent}')
        if response.status_code != 200 or not match:
            falhas.append('o responsável não conseguiu emitir o novo convite completo')
            token = 'inexistente'
        else:
            token = match.group(1)
        if not invite_sent:
            falhas.append('o novo convite não foi enfileirado para o colaborador')

        print('=== 2. conta existente não recebe formulário para criar outra conta ===')
        public_page = Client().get(f'/invite/{token}/')
        public_body = public_page.content.decode('utf-8', 'replace')
        offers_login = 'Entrar e aceitar' in public_body
        asks_new_password = 'name="password1"' in public_body
        print(f'  oferece login={offers_login}  pede senha nova={asks_new_password}')
        if not offers_login or asks_new_password:
            falhas.append('a recontratação tenta criar outra conta em vez de autenticar a existente')

        print('=== 3. aceitar reativa a mesma linha com exatamente os papéis do convite ===')
        collaborator = Client()
        collaborator.force_login(user)
        mail.outbox.clear()
        accepted = collaborator.post(f'/invite/{token}/')
        membership.refresh_from_db()
        exact_roles = set(membership.roles) == {Role.SECRETARY, Role.MANAGER, Role.OWNER}
        one_membership = Membership.objects.filter(tenant=tenant, user=user).count() == 1
        verification_sent = bool(
            mail.outbox
            and mail.outbox[-1].to == [email]
            and '/accounts/verify-email/' in mail.outbox[-1].body
        )
        print(
            f'  HTTP={accepted.status_code}  mesmo vínculo={membership.id == membership_id} '
            f'ativo={membership.status}  papéis exatos={exact_roles}  confirmação={verification_sent}'
        )
        if membership.id != membership_id or not one_membership:
            falhas.append('a recontratação duplicou o vínculo em vez de preservar a identidade')
        if membership.status != MembershipStatus.ACTIVE or membership.revoked_at is not None:
            falhas.append('o convite consumido não reativou completamente o vínculo revogado')
        if not exact_roles:
            falhas.append(f'a recontratação deixou papéis antigos ou perdeu os novos: {membership.roles}')
        if not verification_sent:
            falhas.append('a conta ainda não confirmada não recebeu nova confirmação no aceite')
finally:
    Membership.objects.filter(id=membership_id).delete()
    if invitation is not None:
        Invitation.objects.filter(id=invitation.id).delete()
    User.objects.filter(id=user.id).delete()

print('---')
if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)
print('OK: convite novo reativa a conta existente com os papéis escolhidos e nova confirmação.')
