"""Instalacao limpa: o caminho que a producao vive no primeiro dia.

Banco vazio, um superadministrador, e dai em diante tudo pela tela: emitir
convite, criar a clinica, entrar, habilitar o medico, cadastrar paciente.

E o caminho que mais esconde defeito, porque no dia a dia ninguem o
percorre -- o banco de trabalho ja tem tudo o que falta numa instalacao
nova. Tres defeitos sairam daqui:

- a clinica nascia **sem roteiro de exame**, e a aba do exame neurologico
  abria pedindo um comando de terminal ao medico;
- a instalacao subia **sem CID-10**, e a busca de diagnostico vinha vazia;
- a agenda semanal dava **500** enquanto nao houvesse medico habilitado --
  o estado de toda clinica recem-criada -- porque o modal de marcacao
  ficava fora da guarda de "ha medico?" e a etiqueta de URL do
  template recebia vazio.

**Exige banco vazio**, ao contrario dos outros roteiros, que rodam contra
o banco de demonstracao. Com dado dentro ele diz o que falta e sai sem
falhar: nao ha instalacao nova para verificar num banco povoado.
"""

from django.conf import settings as dj
from django.test import Client

dj.ALLOWED_HOSTS = list(dj.ALLOWED_HOSTS) + ['testserver']
dj.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from accounts.models import User
from catalogs.models import CatalogRelease, DiagnosisCode
from exams.models import ExamScale, ExamTemplate
from patients.models import Patient
from tenancy.models import InvitationPurpose, Membership, Tenant
from tenancy.plans import PlanCode

falhas = []

#: Como se reconhece o que **este** roteiro criou.
#:
#: Existe porque a limpeza precisa distinguir "sobra da minha execucao
#: anterior" de "o banco de demonstracao". Sem essa distincao, a limpeza
#: apagava tudo -- ver o comentario de `banco_povoado`.
MARCA_LEGAL = 'Clinica Nova Neurologia Ltda'


def residuo():
    return Tenant.objects.filter(legal_name=MARCA_LEGAL)


def banco_povoado():
    """Ha dado que nao e deste roteiro?

    A ordem entre esta pergunta e a limpeza foi invertida, e era um defeito
    grave: `limpar_residuo()` rodava **antes** da guarda e apagava toda
    organizacao do banco -- inclusive as duas da demonstracao -- para so
    entao o roteiro dizer "PULADO: exige banco vazio". Rodar a suite
    inteira destruia a demonstracao no meio do caminho, e os roteiros
    seguintes falhavam procurando paciente que tinha acabado de ser
    apagado por este aqui. O sintoma aparecia longe da causa: `check_
    isolation` e `check_prontuario` acusavam defeito de produto que nao
    existia.
    """
    return (Tenant.objects.exclude(legal_name=MARCA_LEGAL).exists()
            or Patient.objects.exclude(tenant__legal_name=MARCA_LEGAL).exists())


def limpar_residuo():
    """Apaga o que uma execucao interrompida **deste roteiro** deixou.

    Limpar so no fim nao basta: a execucao que aborta no meio deixa a
    clinica e o usuario para tras, e a proxima falha em
    `EmailAlreadyRegistered` -- uma mensagem que nao tem relacao nenhuma
    com o que se esta verificando.

    So alcanca a organizacao marcada por `MARCA_LEGAL`. Apagar por
    `Tenant.objects.all()` era o caminho para destruir o banco de quem
    rodasse isto sem ler.
    """
    from audit.models import AuditEvent
    from exams.models import ExamNode, ExamScale, ExamScaleItem, ExamTemplate
    from scheduling.models import AvailabilityRule, Appointment, ScheduleBlock
    from tenancy.models import Invitation

    from patients.models import PatientNumberSequence

    for t in residuo():
        # Agenda primeiro: `AvailabilityRule.physician_membership` e
        # PROTECT, entao apagar o vinculo antes levanta ProtectedError e
        # deixa a limpeza pela metade.
        Appointment.objects.filter(tenant=t).delete()
        ScheduleBlock.objects.filter(tenant=t).delete()
        AvailabilityRule.objects.filter(tenant=t).delete()
        Patient.objects.filter(tenant=t).delete()
        PatientNumberSequence.objects.filter(tenant=t).delete()
        ExamNode.objects.filter(tenant=t).delete()
        ExamTemplate.objects.filter(tenant=t).delete()
        ExamScaleItem.objects.filter(tenant=t).delete()
        ExamScale.objects.filter(tenant=t).delete()
        AuditEvent.objects.filter(tenant=t).delete()
        Membership.objects.filter(tenant=t).delete()
        t.delete()
    # Estas duas continuam amplas, e agora podem ser: so se chega aqui
    # depois de `banco_povoado()` ter dito que nao ha organizacao nem
    # paciente alheio. O convite de plataforma nasce sem vinculo de
    # e-mail, entao filtra-lo por endereco nao acharia nada.
    Invitation.objects.all().delete()
    User.objects.filter(is_superuser=False).delete()


# A guarda vem **antes** da limpeza. Ver `banco_povoado`.
if banco_povoado():
    print('PULADO: este roteiro exige banco vazio (instalacao nova), e ha dado '
          'no banco. Os demais roteiros e que rodam contra a demonstracao. '
          'Nada foi apagado.')
    raise SystemExit(0)

limpar_residuo()

print('=== 0. ponto de partida ===')
print(f'  organizacoes={Tenant.objects.count()}  pacientes={Patient.objects.count()}  '
      f'usuarios={User.objects.count()}')
print(f'  CID-10 ativo={CatalogRelease.objects.filter(system="CID10", status="active").exists()} '
      f'({DiagnosisCode.objects.count()} codigos)')
if not DiagnosisCode.objects.exists():
    falhas.append('instalacao nova subiu sem CID-10')

print('=== 1. o superadministrador existe e o console exige MFA ===')
su = User.objects.filter(is_superuser=True).first()
print(f'  conta={su.email if su else None}  e-mail confirmado={bool(su and su.email_verified_at)}')
if su is None:
    falhas.append('nao ha superadministrador na instalacao nova')
else:
    c = Client()
    c.force_login(su)
    sem_mfa = c.get('/instalacao/').status_code
    print(f'  console sem MFA -> {sem_mfa} (404 esperado)')
    if sem_mfa != 404:
        falhas.append(f'o console abriu sem MFA (HTTP {sem_mfa})')

    from django_otp import login as otp_login
    from django_otp.plugins.otp_totp.models import TOTPDevice

    aparelho = TOTPDevice.objects.create(user=su, name='instalacao', confirmed=True)
    c = Client()
    c.force_login(su)
    pedido = type('R', (), {'session': c.session, 'user': su})()
    otp_login(pedido, aparelho)
    pedido.session.save()
    c.cookies['sessionid'] = pedido.session.session_key
    com_mfa = c.get('/instalacao/').status_code
    print(f'  console com MFA -> {com_mfa} (200 esperado)')
    if com_mfa != 200:
        falhas.append(f'o console nao abriu com MFA (HTTP {com_mfa})')

print('=== 2. emitir convite de plataforma pelo console ===')
r = c.post('/instalacao/convites/', {
    'purpose': 'platform', 'plan': str(PlanCode.BASIC),
    'note': 'primeira clinica da instalacao',
})
corpo = r.content.decode()
import re

achado = re.search(r'[A-Za-z0-9_\-]{20,}', corpo)
from tenancy.models import Invitation

convite = Invitation.objects.order_by('-created_at').first()
print(f'  HTTP={r.status_code}  convite criado={convite is not None}  '
      f'plano={convite.plan if convite else None}')
if convite is None:
    falhas.append('o console nao conseguiu emitir o convite de plataforma')

print('=== 3. criar a clinica pelo convite (o caminho do cliente) ===')
# O codigo em claro so existe no momento da emissao; o console o mostra na
# tela. Aqui o roteiro emite de novo pelo servico, para ter o codigo.
from tenancy.invitations import issue_invitation
from tenancy.services import accept_platform_invitation


def cnpj(base):
    def dv(nums, pesos):
        resto = sum(n * p for n, p in zip(nums, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    n = [int(x) for x in base]
    d1 = dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


retorno = issue_invitation(
    purpose=InvitationPurpose.PLATFORM, issued_by=su, plan=PlanCode.BASIC,
)
token = next(x for x in retorno if isinstance(x, str))

publico = Client()
pagina = publico.get(f'/signup/{token}/')
print(f'  a pagina de cadastro do convite abre -> {pagina.status_code}')

usuario, clinica, vinculo = accept_platform_invitation(
    token, 'dono@clinica-nova.example', 'S3nhaF0rteDeVerdade!2026',
    'Clinica Nova Neurologia Ltda', cnpj('112223330001'), trade_name='Clinica Nova',
)
print(f'  clinica={clinica.slug}  plano={clinica.plan}  dono={usuario.email}')
print(f'  papeis do dono={vinculo.roles}')

print('=== 4. a clinica nasce pronta para atender ===')
roteiros = ExamTemplate.objects.filter(tenant=clinica, status='published').count()
padrao = ExamTemplate.objects.filter(tenant=clinica, is_default=True).first()
escalas = ExamScale.objects.filter(tenant=clinica).count()
print(f'  roteiros publicados={roteiros}  nos do padrao={padrao.nodes.count() if padrao else 0}  '
      f'escalas={escalas}')
if not roteiros or padrao is None:
    falhas.append('a clinica nova nasceu sem roteiro de exame')
if escalas < 10:
    falhas.append(f'a clinica nova nasceu com apenas {escalas} escalas')

print('=== 5. o dono entra e usa o sistema ===')
usuario.email_verified_at = usuario.email_verified_at or __import__(
    'django.utils.timezone', fromlist=['now']).now()
usuario.save(update_fields=['email_verified_at'])
dono = Client()
dono.force_login(usuario)
s = dono.session
s['tenant_id'] = str(clinica.id)
s.save()
for rotulo, caminho in [
    ('painel', '/app/reporting/'), ('pacientes', '/app/patients/'),
    ('agenda (sem medico)', '/app/scheduling/'), ('codigos', '/app/codigos/'),
    ('equipe', '/app/org/equipe/'),
]:
    codigo = dono.get(caminho).status_code
    marca = 'ok' if codigo == 200 else 'ERRO'
    print(f'  {marca:4} {codigo}  {rotulo}')
    if codigo != 200:
        falhas.append(f'a tela "{rotulo}" respondeu {codigo} numa clinica recem-criada')

# O dono que nao e medico **nao** alcanca o chat de apoio, e isso esta
# certo: a IA clinica le prontuario, e ler prontuario e do papel medico.
chat_sem_medico = dono.get('/app/ai/chat/').status_code
print(f'  ok   {chat_sem_medico}  chat de apoio para dono nao-medico (404 esperado)')
if chat_sem_medico != 404:
    falhas.append(f'o dono nao-medico alcancou o chat clinico (HTTP {chat_sem_medico})')

print('=== 5b. o dono vira medico habilitado ===')
# E o caso comum de consultorio: o dono atende. E e o estado em que a
# agenda semanal quebrava -- o modal de marcacao ficava fora da guarda de
# "ha medico?" e o `{% url %}` recebia vazio.
from tenancy.models import Role

vinculo.roles = [Role.OWNER, Role.DOCTOR]
vinculo.save(update_fields=['roles'])
from accounts.models import PhysicianProfile

PhysicianProfile.objects.update_or_create(
    user=usuario,
    defaults={
        'professional_name': 'Dr. Dono da Clinica', 'crm_number': '99999',
        'crm_state': 'SP',
        'verification_status': PhysicianProfile.VerificationStatus.VERIFIED,
    },
)
for rotulo, caminho in [
    ('agenda (com medico)', '/app/scheduling/'),
    ('agenda do dia', '/app/scheduling/dia/'),
    ('chat de apoio', '/app/ai/chat/'),
]:
    codigo = dono.get(caminho).status_code
    marca = 'ok' if codigo == 200 else 'ERRO'
    print(f'  {marca:4} {codigo}  {rotulo}')
    if codigo != 200:
        falhas.append(f'a tela "{rotulo}" respondeu {codigo} com medico habilitado')

print('=== 6. cadastrar o primeiro paciente ===')
r = dono.post('/app/patients/new/', {
    'full_name': 'Paciente Um da Instalacao', 'birth_date': '1980-01-01',
    'sex_at_registration': 'male', 'cpf': '111.444.777-35',
    'payment_category': 'private', 'country': 'BR',
    'referral_source': 'other', 'marital_status': 'single',
})
if r.status_code == 200:
    # Formulario devolvido: mostra por que, em vez de so dizer que falhou.
    contexto = getattr(r, 'context', None)
    formulario = contexto.get('form') if contexto else None
    if formulario is not None and formulario.errors:
        print(f'  erros do formulario: {dict(formulario.errors)}')
paciente = Patient.objects.filter(tenant=clinica).first()
print(f'  HTTP={r.status_code}  paciente criado={paciente is not None}  '
      f'numero={paciente.record_number if paciente else None}')
if paciente is None:
    falhas.append('nao foi possivel cadastrar o primeiro paciente da clinica nova')

print('=== 7. a busca de CID-10 responde ===')
r = dono.get('/app/codigos/?q=enxaqueca')
corpo = r.content.decode()
tem = 'G43' in corpo or 'nxaqueca' in corpo
print(f'  HTTP={r.status_code}  encontra enxaqueca={tem}')
if not tem:
    falhas.append('a busca de CID-10 nao encontra nada numa instalacao nova')

print('=== 8. o limite do plano vale desde o primeiro dia ===')
from tenancy import limits

estado = limits.patient_status(clinica)
print(f'  plano={clinica.plan}  uso={estado.usage}/{estado.limit}  bloqueado={estado.blocked}')
if estado.limit != 3500:
    falhas.append(f'o limite do plano Basico saiu {estado.limit}, esperado 3500')

print()
print('--- limpeza: a instalacao volta a ficar vazia ---')
limpar_residuo()
TOTPDevice.objects.filter(name='instalacao').delete()
print(f'  organizacoes={Tenant.objects.count()}  pacientes={Patient.objects.count()}  '
      f'usuarios={User.objects.count()}')

print()
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: a instalacao limpa vai do zero ao primeiro paciente sem comando de terminal.')
