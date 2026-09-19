"""Inativar uma organizacao desliga mesmo -- e nao apaga nada?

O campo `TenantStatus.SUSPENDED` existia desde o comeco e **nao fazia
nada** fora do portal do paciente: `build_access_context` nunca olhava o
estado, entao marcar uma clinica como suspensa nao mudava coisa alguma
para quem ja tinha vinculo. Faltava a regra, nao o campo.

Sao dois desligamentos diferentes, e a diferenca e o que se verifica aqui:

- suspensa congela: le, imprime e exporta; nao cria nem altera;
- encerrada fecha a porta, e a tela explica a quem recorrer;
- nenhuma das duas apaga registro nenhum;
- reativar devolve tudo;
- clinica desligada nao fala com paciente em nome dela;
- a outra clinica nao sente nada.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import Encounter
from patients.models import Patient
from tenancy.models import Tenant, TenantStatus

falhas = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
paciente = Patient.objects.filter(tenant=tenant_a).first()

# Quanto dado existe antes de tudo. A promessa central e que estes numeros
# nao mudem em nenhum momento deste roteiro.
ANTES = {
    'pacientes': Patient.objects.filter(tenant=tenant_a).count(),
    'atendimentos': Encounter.objects.filter(tenant=tenant_a).count(),
}

AVISO_FAIXA = 'Organização suspensa'
NAO_APAGADOS = 'não foram apagados'
SUPORTE = 'contato@neurodoc.app.br'


def sessao(tenant):
    c = Client()
    c.force_login(medico)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def estado(tenant, novo, motivo='roteiro de verificacao'):
    from django.utils import timezone

    tenant.status = novo
    tenant.status_note = motivo
    tenant.status_changed_at = timezone.now()
    tenant.save(update_fields=['status', 'status_note', 'status_changed_at', 'updated_at'])


print('=== 1. ativa: tudo funciona (linha de base) ===')
c = sessao(tenant_a)
leitura = c.get('/app/patients/').status_code
escrita = c.post(f'/app/patients/{paciente.id}/edit/', {})
print(f'  lista de pacientes={leitura}  POST de edicao={escrita.status_code} (nao 403)')
if leitura != 200:
    falhas.append('a clinica ativa nao abre a lista de pacientes')
if escrita.status_code == 403:
    falhas.append('a clinica ativa recusou escrita')

print('=== 2. suspensa: le, mas nao escreve ===')
estado(tenant_a, TenantStatus.SUSPENDED, 'fatura em aberto')
c = sessao(tenant_a)
r_lista = c.get('/app/patients/')
r_ficha = c.get(f'/app/patients/{paciente.id}/')
r_post = c.post(f'/app/patients/{paciente.id}/edit/', {'full_name': 'NOME TROCADO'})
print(f'  lista={r_lista.status_code}  ficha={r_ficha.status_code}  '
      f'POST={r_post.status_code} (403 esperado)')
if r_lista.status_code != 200 or r_ficha.status_code != 200:
    falhas.append('a clinica suspensa perdeu a leitura -- era para congelar, nao fechar')
if r_post.status_code != 403:
    falhas.append(f'a clinica suspensa aceitou escrita (HTTP {r_post.status_code})')
paciente.refresh_from_db()
if paciente.full_name == 'NOME TROCADO':
    falhas.append('a escrita recusada mesmo assim alterou o registro')

print('=== 3. suspensa: a tela avisa, e avisa em toda tela ===')
corpo = r_lista.content.decode()
avisa = AVISO_FAIXA in corpo
explica = 'Nada foi apagado' in corpo
print(f'  faixa presente={avisa}  diz que nada foi apagado={explica}')
if not avisa or not explica:
    falhas.append('a clinica suspensa nao avisa o usuario do estado em que esta')
if 'suspensa' not in r_post.content.decode().lower():
    falhas.append('a tela de recusa nao explica por que a alteracao nao foi salva')

print('=== 4. encerrada: ninguem entra, e a tela explica ===')
estado(tenant_a, TenantStatus.CLOSED, 'rescisao contratual')
c = sessao(tenant_a)
r = c.get('/app/patients/')
corpo = r.content.decode()
print(f'  HTTP={r.status_code} (403 esperado)')
print(f'  diz que o registro nao foi apagado={NAO_APAGADOS in corpo}')
print(f'  diz a quem recorrer={SUPORTE in corpo}')
if r.status_code != 403:
    falhas.append(f'a clinica encerrada continuou aberta (HTTP {r.status_code})')
if NAO_APAGADOS not in corpo or SUPORTE not in corpo:
    falhas.append('a tela de encerramento nao explica o que houve nem a quem recorrer')

print('=== 5. nada foi apagado, em nenhum dos dois estados ===')
depois = {
    'pacientes': Patient.objects.filter(tenant=tenant_a).count(),
    'atendimentos': Encounter.objects.filter(tenant=tenant_a).count(),
}
print(f'  antes={ANTES}  depois={depois}')
if depois != ANTES:
    falhas.append(f'inativar apagou registro: {ANTES} -> {depois}')

print('=== 6. a outra clinica nao sente nada ===')
codigo_b = sessao(tenant_b).get('/app/patients/').status_code
print(f'  clinica B com a A encerrada: HTTP={codigo_b}')
if codigo_b != 200:
    falhas.append('desligar uma clinica afetou a outra')

print('=== 7. clinica desligada nao fala com paciente em nome dela ===')
# O middleware ja recusa POST, mas o que foi enfileirado **antes** do
# desligamento continuaria saindo por dias. A verificacao e no ponto de
# envio, por onde os dois canais passam.
from communications.models import Delivery, DeliveryStatus
from communications.services import _send

from communications.models import DeliveryChannel
from patients.models import PatientContact
from scheduling.models import Appointment

estado(tenant_a, TenantStatus.SUSPENDED, 'fatura em aberto')
consulta = Appointment.objects.filter(tenant=tenant_a).first()
contato = PatientContact.objects.filter(tenant=tenant_a).first()
if consulta is None or contato is None:
    falhas.append('sem consulta ou contato no banco: a secao 7 nao pode afirmar nada')
    print('  FALTA DADO: sem consulta ou contato para exercitar o envio')
else:
    entrega = Delivery.objects.create(
        tenant=tenant_a, appointment=consulta, contact=contato,
        channel=DeliveryChannel.EMAIL, event_version=1,
        status=DeliveryStatus.PENDING, idempotency_key='check-inativacao',
    )
    _send(entrega, 'mensagem que nao deve sair')
    entrega.refresh_from_db()
    barrou = entrega.status == DeliveryStatus.NO_CONTACT
    tentativa = entrega.attempts.order_by('-created_at').first()
    motivo = getattr(tentativa, 'sanitized_error', '')
    print(f'  envio barrado={barrou}  motivo registrado={motivo!r}')
    if not barrou or motivo != 'tenant_inactive':
        falhas.append('clinica desligada continuou enviando mensagem ao paciente')

    # E com a clinica ativa o mesmo envio passa -- senao esta secao estaria
    # verificando apenas que `_send` falha sempre.
    estado(tenant_a, TenantStatus.ACTIVE, 'roteiro de verificacao')
    entrega.status = DeliveryStatus.PENDING
    entrega.save(update_fields=['status'])
    _send(entrega, 'mensagem de controle')
    entrega.refresh_from_db()
    passou = entrega.status != DeliveryStatus.NO_CONTACT
    print(f'  com a clinica ativa o mesmo envio segue={passou}')
    if not passou:
        falhas.append('a verificacao de clinica desligada barra tambem a clinica ativa')

    entrega.attempts.all().delete()
    entrega.delete()

print('=== 8. reativar devolve tudo ===')
estado(tenant_a, TenantStatus.ACTIVE, 'pagamento regularizado')
c = sessao(tenant_a)
r_lista = c.get('/app/patients/')
r_post = c.post(f'/app/patients/{paciente.id}/edit/', {})
sem_faixa = AVISO_FAIXA not in r_lista.content.decode()
print(f'  lista={r_lista.status_code}  POST={r_post.status_code} (nao 403)  '
      f'faixa sumiu={sem_faixa}')
if r_lista.status_code != 200 or r_post.status_code == 403 or not sem_faixa:
    falhas.append('reativar nao devolveu a clinica ao normal')

print('=== 9. o console do superadmin muda o estado, com motivo e trilha ===')
# `is_active=True`: conta de superusuario desligada nao autentica, e
# `force_login` com ela produziria um 404 no console que se leria como
# falha do console, nao da conta escolhida aqui.
superadmin = User.objects.filter(is_superuser=True, is_active=True).first()
if superadmin is None:
    print('  (sem superusuario -- secao pulada)')
else:
    # O console exige segundo fator verificado na sessao: `force_login`
    # sozinho nao marca `is_verified()`, e a tela responderia 404.
    from django_otp import login as otp_login
    from django_otp.plugins.otp_totp.models import TOTPDevice

    aparelho = TOTPDevice.objects.filter(user=superadmin, confirmed=True).first()
    descartavel = aparelho is None
    if descartavel:
        aparelho = TOTPDevice.objects.create(user=superadmin, name='roteiro', confirmed=True)

    sc = Client()
    sc.force_login(superadmin)
    pedido = type('R', (), {'session': sc.session, 'user': superadmin})()
    otp_login(pedido, aparelho)
    pedido.session.save()
    sc.cookies['sessionid'] = pedido.session.session_key
    rota = f'/instalacao/organizacoes/{tenant_a.id}/estado/'

    sc.post(rota, {'status': 'suspended', 'status_note': ''})
    tenant_a.refresh_from_db()
    print(f'  sem motivo -> estado continua {tenant_a.status} (active esperado)')
    if tenant_a.status != TenantStatus.ACTIVE:
        falhas.append('o console suspendeu a clinica sem motivo escrito')

    sc.post(rota, {'status': 'suspended', 'status_note': 'fatura de 08/2026 em aberto'})
    tenant_a.refresh_from_db()
    print(f'  com motivo -> estado={tenant_a.status}  nota={tenant_a.status_note!r}')
    if tenant_a.status != TenantStatus.SUSPENDED:
        falhas.append('o console nao conseguiu suspender a clinica')

    evento = (
        AuditEvent.objects
        .filter(action='tenancy.tenant_status_changed').order_by('-created_at').first()
    )
    meta = evento.integrity_metadata if evento else {}
    print(f'  trilha registrou={evento is not None}  '
          f'de-para={meta.get("from")} -> {meta.get("to")}')
    if evento is None or meta.get('to') != 'suspended':
        falhas.append('a mudanca de estado nao foi para a trilha com o de-para')

    # E volta ao normal: o banco de demonstracao nao pode ficar desligado.
    sc.post(rota, {'status': 'active', 'status_note': 'roteiro de verificacao'})
    tenant_a.refresh_from_db()
    print(f'  reativada pelo console -> {tenant_a.status}')
    if tenant_a.status != TenantStatus.ACTIVE:
        falhas.append('o roteiro deixou a clinica de demonstracao desligada')

    if descartavel:
        aparelho.delete()

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: suspensa congela, encerrada fecha, nada e apagado e reativar devolve.')
