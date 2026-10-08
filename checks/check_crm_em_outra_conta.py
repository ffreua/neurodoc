"""CRM ja registrado em outra conta: a recusa fica, e passa a ensinar.

Em 2026-10-08 o medico abriu uma segunda clinica (gratuita, para testar)
com outro e-mail e, ao cadastrar o proprio CRM nela, recebeu "Physician
profile com este Crm number e Crm state ja existe." -- em ingles, e sem
dizer o que fazer.

O registro profissional e da PESSOA: mora na conta, e uma conta atende em
quantas clinicas tiver vinculo. O caminho certo ja existia -- convidar a
conta onde o CRM esta --, e a tela nao o dizia.

O que este roteiro tenta quebrar:

1. a recusa: em portugues, com o caminho, e SEM revelar de quem e a outra
   conta (CRM e publico; o e-mail de quem o tem nao e);
2. a variante de quem ja e da equipe: o caminho e dar o papel, nao convidar;
3. que a unicidade NAO afrouxou -- ela e o que impede alguem de cadastrar
   o CRM de outro medico numa clinica gratuita e assinar no nome dele;
4. que editar o proprio registro, com o mesmo CRM, continua passando;
5. que o caminho recomendado funciona: o convite aceito pela conta que ja
   existe cria o vinculo, sem conta duplicada, e o registro vem junto.
"""
import uuid

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.contrib.messages import get_messages
from django.db import IntegrityError, transaction
from django.test import Client

from accounts.models import PhysicianProfile, User
from tenancy.invitations import issue_invitation
from tenancy.models import InvitationPurpose, Membership, MembershipStatus, Role, Tenant
from tenancy.services import accept_collaborator_invitation_for_user

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
dono = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER],
).select_related('user').first()
limite_original = tenant.doctor_limit_override

sufixo = uuid.uuid4().hex[:8]
CRM = str(900000 + int(sufixo[:4], 16) % 99999)
UF = 'SP'

criados_usuarios = []
criados_vinculos = []


def novo_usuario(rotulo):
    u = User.objects.create_user(email=f'crm-{rotulo}-{sufixo}@example.com', password=None)
    criados_usuarios.append(u.id)
    return u


def cliente():
    c = Client()
    c.force_login(dono.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def gravar_registro(vinculo, crm=CRM, nome='DR TESTE CRM'):
    r = cliente().post(f'/app/org/equipe/{vinculo.id}/registro-profissional/', {
        'professional_name': nome, 'crm_number': crm, 'crm_state': UF,
        'rqe': '', 'professional_phone': '', 'professional_email': '',
        'professional_address': '',
    })
    avisos = [str(m) for m in get_messages(r.wsgi_request)]
    return r, (avisos[-1] if avisos else '')


try:
    # Folga de vagas de medico so durante o roteiro: o que se testa aqui e
    # o registro, nao o limite do plano.
    tenant.doctor_limit_override = 999
    tenant.save(update_fields=['doctor_limit_override'])

    titular = novo_usuario('titular')
    PhysicianProfile.objects.create(
        user=titular, professional_name='DR TITULAR', crm_number=CRM, crm_state=UF,
    )

    print('=== 1. outra conta, fora da clinica: recusa em portugues, com o caminho ===')
    outra = novo_usuario('outra')
    v_outra = Membership.objects.create(
        tenant=tenant, user=outra, roles=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
    )
    criados_vinculos.append(v_outra.id)
    r, aviso = gravar_registro(v_outra)
    print('     ->', aviso[:110])
    confere(not PhysicianProfile.objects.filter(user=outra).exists(), 'nada foi gravado')
    confere('Physician' not in aviso and 'Crm number' not in aviso, 'nada em ingles')
    confere('outra conta do NeuroDoc' in aviso, 'diz que o CRM esta em outra conta')
    confere('convide' in aviso, 'diz o caminho: convidar a conta onde ele esta')
    confere(titular.email not in aviso and 'crm-titular' not in aviso,
            'NAO revela o e-mail de quem tem o CRM')

    print('=== 2. a outra conta ja e da equipe: o caminho e dar o papel ===')
    v_titular = Membership.objects.create(
        tenant=tenant, user=titular, roles=[Role.SECRETARY], status=MembershipStatus.ACTIVE,
    )
    criados_vinculos.append(v_titular.id)
    r, aviso = gravar_registro(v_outra)
    print('     ->', aviso[:110])
    confere('desta equipe' in aviso and 'papel de médico' in aviso,
            'aponta o vinculo que ja existe e o papel')
    Membership.objects.filter(id=v_titular.id).delete()
    criados_vinculos.remove(v_titular.id)

    print('=== 3. a unicidade nao afrouxou ===')
    try:
        with transaction.atomic():
            PhysicianProfile.objects.create(
                user=outra, professional_name='IMPOSTOR', crm_number=CRM, crm_state=UF,
            )
        confere(False, 'o banco recusa o segundo registro do mesmo CRM')
    except IntegrityError:
        confere(True, 'o banco recusa o segundo registro do mesmo CRM')

    print('=== 4. editar o proprio registro, com o mesmo CRM, passa ===')
    v_tit = Membership.objects.create(
        tenant=tenant, user=titular, roles=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
    )
    criados_vinculos.append(v_tit.id)
    r, aviso = gravar_registro(v_tit, nome='DR TITULAR RENOMEADO')
    perfil = PhysicianProfile.objects.get(user=titular)
    confere(perfil.professional_name == 'DR TITULAR RENOMEADO', 'o proprio registro e regravado',
            aviso[:80])
    Membership.objects.filter(id=v_tit.id).delete()
    criados_vinculos.remove(v_tit.id)

    print('=== 5. o caminho recomendado: convidar a conta que ja existe ===')
    contas_antes = User.objects.filter(email=titular.email).count()
    _, token = issue_invitation(
        InvitationPurpose.COLLABORATOR, issued_by=dono.user, target_tenant=tenant,
        email_binding=titular.email, role_grants=[Role.DOCTOR],
    )
    vinculo = accept_collaborator_invitation_for_user(token, titular)
    criados_vinculos.append(vinculo.id)
    confere(vinculo.tenant_id == tenant.id and Role.DOCTOR in vinculo.roles,
            'o convite aceito cria o vinculo de medico na clinica')
    confere(User.objects.filter(email=titular.email).count() == contas_antes,
            'sem conta duplicada')
    confere(PhysicianProfile.objects.filter(user=titular, crm_number=CRM).exists(),
            'o registro profissional vem junto, sem cadastrar de novo')
finally:
    Membership.objects.filter(id__in=criados_vinculos).delete()
    PhysicianProfile.objects.filter(user_id__in=criados_usuarios).delete()
    from tenancy.models import Invitation

    Invitation.objects.filter(email_binding__startswith='crm-').filter(
        email_binding__endswith=f'{sufixo}@example.com').delete()
    User.objects.filter(id__in=criados_usuarios).delete()
    tenant.doctor_limit_override = limite_original
    tenant.save(update_fields=['doctor_limit_override'])

print('---')
if failures:
    for linha in failures:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o CRM continua de uma pessoa so, e a tela diz o caminho.')
