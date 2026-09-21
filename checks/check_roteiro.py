"""Toda clinica nasce com o roteiro de exame -- ou nasce quebrada?

O exame neurologico estruturado e a razao de o produto existir para um
neurologista, e ate aqui ele dependia de alguem lembrar de rodar
`manage.py install_exam_template` depois de criar a organizacao.

Ninguem lembrava. A clinica entrava, atendia o primeiro paciente, abria o
exame e lia um aviso pedindo um comando de terminal que o dono do
consultorio nao tem como executar. O defeito chegou ate as capturas do
manual publico, que e onde ele foi finalmente visto.

As perguntas sao:

- as clinicas que existem tem roteiro publicado e padrao?
- a tela de atendimento ainda pede o comando de terminal?
- uma clinica criada agora, por convite, ja nasce com roteiro?
- provisionar duas vezes versiona o roteiro sem necessidade?
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from clinical.models import Encounter
from exams.models import (
    ExamNode, ExamScale, ExamScaleItem, ExamTemplate, ExamTemplateStatus,
)
from exams.provisioning import ensure_default_template
from tenancy.invitations import issue_invitation
from tenancy.models import InvitationPurpose, Membership, Tenant
from tenancy.plans import PlanCode
from tenancy.services import accept_platform_invitation

falhas = []


def _oficiais(tenant_id):
    return ExamTemplate.objects.filter(
        tenant_id=tenant_id, owner_membership__isnull=True,
        status=ExamTemplateStatus.PUBLISHED,
    )


def _cnpj(base):
    def dv(nums, pesos):
        resto = sum(n * p for n, p in zip(nums, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    numeros = [int(x) for x in base]
    d1 = dv(numeros, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(numeros + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


def limpar_residuo():
    """Desfaz o que uma execucao interrompida **deste roteiro** deixou.

    Limpar so no fim nao basta: a execucao que aborta no meio deixa a
    clinica e o usuario para tras, e a proxima morre em
    `EmailAlreadyRegistered` -- uma mensagem que nao tem relacao nenhuma
    com o que se esta verificando. Foi exatamente o que aconteceu quando o
    aceite de contrato passou a segurar a clinica por PROTECT.

    So alcanca o CNPJ e o e-mail usados aqui.
    """
    from tenancy.models import ContractAcceptance

    velhas = list(Tenant.objects.filter(cnpj=_cnpj('987654320001')))
    if velhas:
        ContractAcceptance.objects.filter(tenant__in=velhas).delete()
        for velha in velhas:
            ExamNode.objects.filter(tenant=velha).delete()
            ExamTemplate.objects.filter(tenant=velha).delete()
            ExamScaleItem.objects.filter(tenant=velha).delete()
            ExamScale.objects.filter(tenant=velha).delete()
            Membership.objects.filter(tenant=velha).delete()
            velha.delete()
    User.objects.filter(email='check-roteiro@example.invalid').delete()


limpar_residuo()

print('=== 1. as clinicas existentes tem roteiro publicado e padrao ===')
for tenant in Tenant.objects.all():
    publicados = _oficiais(tenant.id).count()
    padrao = ExamTemplate.objects.filter(tenant=tenant, is_default=True).first()
    nos = padrao.nodes.count() if padrao else 0
    print(f'  {tenant.slug:18} publicados={publicados}  padrao={bool(padrao)}  nos={nos}')
    if not publicados:
        falhas.append(f'{tenant.slug} nao tem roteiro de exame publicado')
    if padrao is None:
        falhas.append(f'{tenant.slug} nao tem roteiro padrao')
    elif nos < 100:
        # O roteiro de neurologia tem centenas de nos; um punhado significa
        # carga interrompida no meio, que e pior do que nao ter.
        falhas.append(f'{tenant.slug} tem roteiro padrao com apenas {nos} nos')

print('=== 2. a tela de atendimento nao pede comando de terminal ===')
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
atendimento = Encounter.objects.filter(tenant=tenant_a).first()
c = Client()
c.force_login(medico)
s = c.session
s['tenant_id'] = str(tenant_a.id)
s.save()
corpo = c.get(f'/app/clinical/encounters/{atendimento.id}/').content.decode()
pede_comando = 'install_exam_template' in corpo
sem_roteiro = 'Nenhum roteiro de exame publicado' in corpo
print(f'  cita install_exam_template={pede_comando}  avisa sem roteiro={sem_roteiro}')
if pede_comando or sem_roteiro:
    falhas.append('a tela de atendimento manda o usuario rodar um comando de terminal')

print('=== 3. clinica criada por convite ja nasce com roteiro ===')




emissor = User.objects.filter(is_superuser=True).first()
retorno = issue_invitation(
    purpose=InvitationPurpose.PLATFORM, issued_by=emissor, plan=PlanCode.BASIC,
)
token = next(x for x in retorno if isinstance(x, str))
usuario, nova, _vinculo, _aceite = accept_platform_invitation(
    token, 'check-roteiro@example.invalid', 'S3nhaF0rte!123',
    'Clinica Do Roteiro Ltda', _cnpj('987654320001'),
)
publicados = _oficiais(nova.id).count()
padrao = ExamTemplate.objects.filter(tenant=nova, is_default=True).first()
escalas = ExamScale.objects.filter(tenant=nova).count()
print(f'  {nova.slug}: publicados={publicados}  padrao={bool(padrao)} '
      f'nos={padrao.nodes.count() if padrao else 0}  escalas={escalas}')
if not publicados or padrao is None:
    falhas.append('clinica criada por convite nasceu sem roteiro de exame')
if not escalas:
    falhas.append('clinica criada por convite nasceu sem as escalas')

print('=== 4. provisionar de novo nao versiona a toa ===')
# Reinstalar deliberadamente versiona, e esta certo -- e assim que uma
# atualizacao do roteiro preserva o atendimento antigo. O que nao pode e a
# clinica ganhar uma versao nova a cada vez que o provisionamento roda.
antes = _oficiais(nova.id).count()
repetido = ensure_default_template(nova.id)
depois = _oficiais(nova.id).count()
print(f'  chamou de novo -> devolveu={repetido}  publicados {antes} -> {depois}')
if repetido is not None or depois != antes:
    falhas.append('provisionar duas vezes criou uma versao nova do roteiro sem necessidade')

# limpeza: a clinica de teste nao fica no banco
#
# O aceite de contrato sai antes de tudo: `ContractAcceptance.tenant` e
# PROTECT, como todo `TenantModel`, e a clinica criada pelo caminho do
# cliente agora nasce com um.
from tenancy.models import ContractAcceptance
ContractAcceptance.objects.filter(tenant=nova).delete()
ExamNode.objects.filter(tenant=nova).delete()
ExamTemplate.objects.filter(tenant=nova).delete()
ExamScaleItem.objects.filter(tenant=nova).delete()
ExamScale.objects.filter(tenant=nova).delete()
Membership.objects.filter(tenant=nova).delete()
nova.delete()
usuario.delete()

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: a clinica nasce com o roteiro de exame, e a tela nao pede terminal.')
