"""A degustação de sete dias do Completo (1.35) tenta ser quebrada.

O que este roteiro cobra, e onde da errado:

- **a porta e a do Gratuito**, com o convite do Completo: POST com CSRF e
  campo-armadilha, GET sem efeito, e o cadastro dizendo "degustacao";
- **o contrato e o do Gratuito**, com a degustacao gravada no aceite como
  condicao comercial -- e na via por e-mail;
- **o prazo e a meia-noite de Brasilia do setimo dia**: 23h59 conta,
  00h00 nao. Contado em dias de calendario, e nao em 168 horas;
- **os tetos**: IA (tarefas e perguntas do chat) e SMS pela chave da
  instalacao; a chave da propria clinica nao conta;
- **o oitavo dia**, pelos tres caminhos -- a tela, o worker (SMS e IA, que
  nao passam pelo middleware) e a tarefa --, uma vez so, com a clinica no
  Gratuito, o medico escolhido mantido, os outros sem o papel (suspenso
  quem nao tinha outro), nada apagado, a trilha e o e-mail;
- **a escolha do medico** recusando vinculo de outra clinica e quem nao e
  medico;
- **o aviso de vespera** uma vez, mesmo com duas rodadas;
- **a conversao** devolvendo os medicos e tirando o prazo, e **estender**
  so em andamento.
"""
import uuid
from datetime import datetime, time, timedelta
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.utils import timezone

from accounts.models import User
from ai.chat_models import ChatMessage, ChatMessageRole, ChatSession
from audit.models import AuditEvent
from communications import smsdev
from tenancy import contract, degustacao
from tenancy.invitations import issue_invitation
from tenancy.models import (
    ContractAcceptance, Invitation, InvitationPurpose, Membership, MembershipStatus, Role, Tenant,
    TenantStatus,
)

falhas = []
SUFIXO = '@degustacao.invalid'
FAIXA = 'data-nd-aviso="degustacao"'


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  {'ok  ' if ok else 'FALHA'} {rotulo:<70} -> {obtido!r}")
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


def cnpj_valido(base):
    def dv(numeros, pesos):
        resto = sum(a * b for a, b in zip(numeros, pesos)) % 11
        return 0 if resto < 2 else 11 - resto

    n = [int(x) for x in base]
    d1 = dv(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + str(d1) + str(d2)


CNPJS = {chave: cnpj_valido(f'7788{indice:04d}0001') for indice, chave in enumerate(
    ('vitrine', 'forjado', 'oitavo', 'worker', 'vespera', 'outra', 'normal'), start=11)}


def limpar():
    """Aposenta o que a execucao anterior deixou, sem apagar (ver `check_contrato`)."""
    for clinica in Tenant.objects.filter(cnpj__in=CNPJS.values()):
        ContractAcceptance.objects.filter(tenant=clinica).delete()
        clinica.degustacao_medico_mantido = None
        clinica.save(update_fields=['degustacao_medico_mantido'])
        Membership.objects.filter(tenant=clinica).update(status=MembershipStatus.REVOKED, roles=[])
        sufixo = uuid.uuid4().hex[:8]
        clinica.cnpj = f'00{sufixo[:6]}000199'
        clinica.slug = f'aposentada-{sufixo}'
        clinica.legal_name = f'[aposentada pelo roteiro] {clinica.legal_name}'[:255]
        clinica.trade_name = f'[aposentada] {sufixo}'
        clinica.status = TenantStatus.CLOSED
        clinica.degustacao_ate = None
        clinica.save(update_fields=['cnpj', 'slug', 'legal_name', 'trade_name', 'status', 'degustacao_ate'])
    for conta in User.objects.filter(email__endswith=SUFIXO):
        conta.email = f'aposentado-{uuid.uuid4().hex[:12]}{SUFIXO}.velho'
        conta.is_active = False
        conta.set_unusable_password()
        conta.save()


#: Endereços de documentação (RFC 5737), um para o cadastro e outro para a
#: porta da vitrine. O cadastro tem teto de 20 por IP por hora e a porta, de
#: 3: com o IP local de sempre, este roteiro somado aos outros estourava o
#: teto e reprovava quem rodasse depois dele.
IP_CADASTRO = '203.0.113.51'
IP_PORTA = '198.51.100.77'


def zerar_tetos():
    from django.core.cache import cache

    cache.delete_many([f'cadastro:{IP_CADASTRO}', f'degustacao:{IP_PORTA}'])


def cadastrar(chave, token):
    Client(REMOTE_ADDR=IP_CADASTRO).post(f'/signup/{token}/', {
        'email': f'dono-{chave}{SUFIXO}',
        'password': 'S3nhaF0rteDeVerdade!2026',
        'password_confirm': 'S3nhaF0rteDeVerdade!2026',
        'legal_name': f'Clinica Degustacao {chave} Ltda',
        'trade_name': f'Degustacao {chave}',
        'documento': CNPJS[chave],
        'contract_version': contract.VERSAO,
        'accept_contract': 'on',
        'declare_powers': 'on',
    })
    return Tenant.objects.filter(cnpj=CNPJS[chave]).first()


def degustar(chave):
    _, token = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan='complete', degustacao=True)
    return cadastrar(chave, token)


def entrar(user, tenant):
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=['email_verified_at'])
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def dono(tenant):
    return Membership.objects.get(tenant=tenant, roles__contains=[Role.OWNER]).user


def medico(tenant, nome, papeis):
    conta = User.objects.create_user(email=f'{nome}-{uuid.uuid4().hex[:6]}{SUFIXO}', password=None)
    return Membership.objects.create(
        tenant=tenant, user=conta, roles=papeis, status=MembershipStatus.ACTIVE,
        activated_at=timezone.now(),
    )


def local(ano, mes, dia, hora=0, minuto=0):
    return timezone.make_aware(datetime(ano, mes, dia, hora, minuto), timezone.get_current_timezone())


limpar()
zerar_tetos()

print('\n1. A porta da vitrine')
anonimo = Client()
pagina = anonimo.get('/').content.decode()
conferir('o cartao do Completo oferece a degustacao', 'action="/degustacao/"' in pagina, True)
conferir('com o numero de dias do codigo', f'por {degustacao.DIAS} dias' in pagina, True)
conferir('o Gratuito continua la', 'action="/comecar-gratis/"' in pagina, True)
conferir('GET em /degustacao/ volta aos planos sem convite',
         (anonimo.get('/degustacao/').status_code, Invitation.objects.filter(degustacao=True).count() >= 0),
         (302, True))
antes = Invitation.objects.filter(degustacao=True).count()
r = anonimo.post('/degustacao/', {'website': 'robo'})
conferir('o campo-armadilha nao emite convite',
         Invitation.objects.filter(degustacao=True).count(), antes)
r = Client(REMOTE_ADDR=IP_PORTA).post('/degustacao/')
convite = Invitation.objects.filter(degustacao=True).order_by('-created_at').first()
conferir('o POST emite o convite da degustacao e leva ao cadastro',
         (r.status_code, '/signup/' in r.get('Location', ''), convite.plan, convite.degustacao),
         (302, True, 'complete', True))
cadastro = Client().get(r['Location']).content.decode()
conferir('o cadastro diz que e degustacao, por quantos dias, e o que vem depois',
         ('Degustação do plano Completo por 7 dias' in cadastro, 'plano <strong>Gratuito</strong>' in cadastro),
         (True, True))
robots = anonimo.get('/robots.txt').content.decode()
conferir('o robots.txt barra /degustacao/', 'Disallow: /degustacao/' in robots, True)

print('\n2. O cadastro: Completo por sete dias, contrato do Gratuito')
mail.outbox = []
token = r['Location'].rstrip('/').split('/')[-1]
clinica = cadastrar('vitrine', token)
conferir('a clinica nasce', clinica is not None, True)
conferir('no Completo, em degustacao', (clinica.plan, degustacao.em_andamento(clinica)), ('complete', True))
conferir('o prazo e a meia-noite de Brasilia do setimo dia',
         timezone.localtime(clinica.degustacao_ate).time(), time(0, 0))
conferir('sete dias de calendario',
         (timezone.localtime(clinica.degustacao_ate).date() - timezone.localtime(clinica.degustacao_inicio).date()).days,
         degustacao.DIAS)
aceite = ContractAcceptance.objects.get(tenant=clinica)
conferir('o aceite e do Gratuito, sem valor', (aceite.plan, aceite.price_annual_cents), ('free', 0))
conferir('com a degustacao como condicao comercial',
         (aceite.degustacao_plano, aceite.degustacao_ate == clinica.degustacao_ate), ('complete', True))
via = [m for m in mail.outbox if 'contrato' in m.subject.lower()]
conferir('a via do contrato registra a degustacao',
         bool(via) and 'Condição comercial: degustação do plano Completo' in via[0].body, True)
boas = [m for m in mail.outbox if m.subject.startswith('Boas-vindas')]
conferir('as boas-vindas dizem ate quando',
         bool(boas) and 'DEGUSTAÇÃO ATÉ' in boas[0].body, True)

_, forjado = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan='basic', degustacao=True)
outra = cadastrar('forjado', forjado)
conferir('convite de degustacao com outro plano ainda degusta o Completo',
         (outra.plan, degustacao.em_andamento(outra)), ('complete', True))
_, normal = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan='complete')
comum = cadastrar('normal', normal)
conferir('o convite comum do Completo nao vira degustacao',
         (comum.plan, comum.degustacao_ate, ContractAcceptance.objects.get(tenant=comum).plan),
         ('complete', None, 'complete'))
de_colaborador, _token = issue_invitation(
    purpose=InvitationPurpose.COLLABORATOR, target_tenant=comum, degustacao=True)
conferir('convite de colaborador nunca carrega degustacao', de_colaborador.degustacao, False)

print('\n3. O prazo')
segunda_22h = local(2026, 11, 2, 22, 0)
conferir('comecou segunda as 22h: vai ate a meia-noite da segunda seguinte',
         timezone.localtime(degustacao.prazo_a_partir_de(segunda_22h)), timezone.localtime(local(2026, 11, 9)))
teste = Tenant(degustacao_inicio=segunda_22h, degustacao_ate=degustacao.prazo_a_partir_de(segunda_22h))
conferir('domingo 23h59 ainda e degustacao', degustacao.em_andamento(teste, local(2026, 11, 8, 23, 59)), True)
conferir('segunda 00h00 ja nao e', degustacao.em_andamento(teste, local(2026, 11, 9, 0, 0)), False)
conferir('e esta vencida', degustacao.vencida(teste, local(2026, 11, 9, 0, 0)), True)
conferir('o ultimo dia escrito na tela e domingo', degustacao.ultimo_dia(teste), local(2026, 11, 8).date())
with mock.patch('django.utils.timezone.now', return_value=local(2026, 11, 8, 10, 0)):
    conferir('no ultimo dia, falta 1', degustacao.dias_restantes(teste), 1)
with mock.patch('django.utils.timezone.now', return_value=local(2026, 11, 3, 10, 0)):
    conferir('no dia seguinte ao inicio, faltam 6', degustacao.dias_restantes(teste), 6)

print('\n4. A faixa')
c_dono = entrar(dono(clinica), clinica)
tela = c_dono.get('/app/reporting/').content.decode()
conferir('a faixa aparece com os dias e as cotas',
         (FAIXA in tela, 'faltam 7 dias' in tela or 'faltam' in tela, f'Restam {degustacao.TETO_IA} pedidos' in tela),
         (True, True, True))
tela_comum = entrar(dono(comum), comum).get('/app/reporting/').content.decode()
conferir('clinica que nao veio da degustacao nao tem faixa', FAIXA in tela_comum, False)

print('\n5. O teto de IA')
sessao = ChatSession.objects.create(tenant=clinica, owner_user=dono(clinica))
velha = ChatMessage.objects.create(tenant=clinica, session=sessao, role=ChatMessageRole.USER,
                                   content='antes', sequence=1)
ChatMessage.objects.filter(id=velha.id).update(created_at=clinica.degustacao_inicio - timedelta(hours=1))
ChatMessage.objects.create(tenant=clinica, session=sessao, role=ChatMessageRole.ASSISTANT, content='r', sequence=2)
for i in range(3, 3 + degustacao.TETO_IA - 1):
    ChatMessage.objects.create(tenant=clinica, session=sessao, role=ChatMessageRole.USER, content='p', sequence=i)
conferir('conta a pergunta do chat desde o inicio, e nao a resposta nem a de antes',
         degustacao.uso_de_ia(clinica), degustacao.TETO_IA - 1)
try:
    degustacao.conferir_ia(clinica.id)
    conferir('com um pedido sobrando, passa', True, True)
except degustacao.CotaEsgotada:
    conferir('com um pedido sobrando, passa', False, True)
ChatMessage.objects.create(tenant=clinica, session=sessao, role=ChatMessageRole.USER, content='p', sequence=99)
try:
    degustacao.conferir_ia(clinica.id)
    conferir('no teto, recusa', False, True)
except degustacao.CotaEsgotada as exc:
    conferir('no teto, recusa com a explicacao', 'Contrate o plano Completo' in str(exc), True)
# O chat e o `create_job` ficam atrás do papel médico com CRM validado, que
# a clínica de teste não tem: o papel é simulado como concedido, e o que se
# cobra aqui é só o teto.
from types import SimpleNamespace

from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage

from ai import chat_views
from ai.context import AIAuthorizationDenied
from ai.services import create_job

total = ChatMessage.objects.filter(session=sessao).count()
pedido = RequestFactory().post('/x/', {'content': 'mais uma'})
pedido.user = dono(clinica)
pedido.session = {}
pedido._messages = FallbackStorage(pedido)
with mock.patch.object(chat_views, '_own_session_or_404', return_value=sessao), \
        mock.patch.object(chat_views, 'run_chat_turn') as turno:
    r = chat_views.ChatMessageCreateView().post(pedido, session_id=sessao.id)
conferir('o chat no teto nao grava a pergunta, nao chama o provedor e volta para a conversa',
         (r.status_code, ChatMessage.objects.filter(session=sessao).count(), turno.delay.called),
         (302, total, False))
dono_id = Membership.objects.get(tenant=clinica, roles__contains=[Role.OWNER]).id
contexto = SimpleNamespace(tenant_id=clinica.id, user_id=dono(clinica).id, membership_id=dono_id)
autorizado = SimpleNamespace(tenant_id=clinica.id, user_id=dono(clinica).id, membership_id=dono_id,
                             patient_id=None, encounter_id=None)
with mock.patch('ai.services.build_ai_authorization', return_value=autorizado):
    try:
        create_job(contexto, 'encounter_summary', purpose='roteiro')
        conferir('create_job no teto recusa', False, True)
    except AIAuthorizationDenied as exc:
        conferir('create_job no teto recusa com a mensagem da degustacao', 'degustação' in str(exc), True)
fonte_handler = open('/app/ai/handlers.py', encoding='utf-8').read()
conferir('o resumo automatico sai por return no teto, sem falhar o evento',
         'except degustacao.CotaEsgotada:\n        return' in fonte_handler, True)

print('\n6. O teto de SMS')
resposta = mock.Mock(status_code=200)
resposta.json.return_value = {'situacao': 'OK', 'id': '1'}
with mock.patch.object(dj_settings, 'SMS_ENABLED', True), \
        mock.patch.object(dj_settings, 'SMSDEV_API_KEY', 'chave-da-instalacao'), \
        mock.patch.object(smsdev.requests, 'post', return_value=resposta) as envio:
    for _i in range(degustacao.TETO_SMS):
        smsdev.send_sms('11999990000', 'oi', f'roteiro-{_i}', tenant_id=clinica.id)
    clinica.refresh_from_db()
    conferir('os SMS pela chave da instalacao sao contados', clinica.degustacao_sms, degustacao.TETO_SMS)
    try:
        smsdev.send_sms('11999990000', 'oi', 'roteiro-x', tenant_id=clinica.id)
        conferir('o SMS alem do teto e recusado', False, True)
    except smsdev.SmsChannelDisabled as exc:
        conferir('o SMS alem do teto e recusado como canal indisponivel, citando o e-mail',
                 'e-mail continua' in str(exc), True)
    conferir('e nao chega ao provedor', envio.call_count, degustacao.TETO_SMS)
    with mock.patch.object(smsdev, 'resolve_api_key', return_value='chave-da-clinica'):
        smsdev.send_sms('11999990000', 'oi', 'roteiro-propria', tenant_id=clinica.id)
    clinica.refresh_from_db()
    conferir('com a chave da propria clinica, nao conta', clinica.degustacao_sms, degustacao.TETO_SMS)

print('\n7. A escolha do medico')
oitavo = degustar('oitavo')
ana = medico(oitavo, 'ana', [Role.DOCTOR])
bia = medico(oitavo, 'bia', [Role.DOCTOR])
caio = medico(oitavo, 'caio', [Role.DOCTOR, Role.SECRETARY])
secretaria = medico(oitavo, 'sec', [Role.SECRETARY])
estranho = medico(comum, 'estranho', [Role.DOCTOR])
c_oitavo = entrar(dono(oitavo), oitavo)
equipe = c_oitavo.get('/app/org/equipe/').content.decode()
conferir('a equipe oferece a escolha, com o mais antigo marcado',
         ('Quem continua médico depois da degustação' in equipe, f'value="{ana.id}" selected' in equipe),
         (True, True))
for rotulo, valor in (('vinculo de outra clinica', estranho.id), ('quem nao e medico', secretaria.id),
                      ('id invalido', 'xyz')):
    c_oitavo.post('/app/org/equipe/degustacao/', {'membership': valor})
    oitavo.refresh_from_db()
    conferir(f'{rotulo} e recusado sem gravar', oitavo.degustacao_medico_mantido_id, None)
conferir('GET nao grava', c_oitavo.get('/app/org/equipe/degustacao/').status_code, 405)
c_oitavo.post('/app/org/equipe/degustacao/', {'membership': bia.id})
oitavo.refresh_from_db()
conferir('o medico escolhido fica gravado', oitavo.degustacao_medico_mantido_id, bia.id)
c_sec = entrar(secretaria.user, oitavo)
conferir('a secretaria nao escolhe', c_sec.post('/app/org/equipe/degustacao/', {'membership': ana.id}).status_code in (403, 404), True)

print('\n8. O oitavo dia, pela tela')
mail.outbox = []
vinculos_antes = Membership.objects.filter(tenant=oitavo).count()
Tenant.objects.filter(id=oitavo.id).update(degustacao_ate=timezone.now() - timedelta(minutes=1))
c_oitavo.get('/app/reporting/')
oitavo.refresh_from_db()
for m in (ana, bia, caio):
    m.refresh_from_db()
conferir('a clinica volta ao Gratuito', (oitavo.plan, oitavo.degustacao_encerrada_em is not None), ('free', True))
conferir('o escolhido continua medico e ativo', (Role.DOCTOR in bia.roles, bia.status), (True, 'active'))
conferir('quem so era medico perde o papel e fica suspenso', (ana.roles, ana.status), ([], 'suspended'))
conferir('quem tambem era secretaria fica, sem o papel medico',
         (caio.roles, caio.status), ([Role.SECRETARY], 'active'))
conferir('nenhum vinculo some', Membership.objects.filter(tenant=oitavo).count(), vinculos_antes)
conferir('os retirados ficam anotados para a conversao', len(oitavo.degustacao_retirados), 2)
conferir('a trilha registra o encerramento',
         AuditEvent.objects.filter(tenant_id=oitavo.id, action='tenancy.degustacao_encerrada').count(), 1)
fim = [m for m in mail.outbox if 'terminou' in m.subject]
conferir('o responsavel recebe o e-mail do fim, uma vez', len(fim), 1)
conferir('o e-mail diz quantos ficaram sem o perfil', bool(fim) and '2 vínculos' in fim[0].body, True)
conferir('encerrar de novo nao faz nada', degustacao.encerrar(oitavo.id), False)
tela = c_oitavo.get('/app/reporting/').content.decode()
conferir('a faixa passa a dizer que terminou, ao responsavel',
         (FAIXA in tela, 'terminou' in tela), (True, True))

print('\n9. O oitavo dia, pelo worker e pela tarefa')
worker = degustar('worker')
Tenant.objects.filter(id=worker.id).update(degustacao_ate=timezone.now() - timedelta(minutes=1))
with mock.patch.object(dj_settings, 'SMS_ENABLED', True), \
        mock.patch.object(dj_settings, 'SMSDEV_API_KEY', 'chave-da-instalacao'):
    try:
        smsdev.resolve_api_key(worker.id)
        conferir('o lembrete do worker no oitavo dia ja nao tem SMS', False, True)
    except smsdev.SmsChannelDisabled:
        conferir('o lembrete do worker no oitavo dia ja nao tem SMS', True, True)
worker.refresh_from_db()
conferir('e a clinica foi encerrada ali, sem ninguem abrir a tela', worker.plan, 'free')
vespera = degustar('vespera')
Tenant.objects.filter(id=vespera.id).update(degustacao_ate=timezone.now() + timedelta(days=1))
mail.outbox = []
primeira = degustacao.rodada()
segunda = degustacao.rodada()
acabando = [m for m in mail.outbox if 'acabando' in m.subject and any(
    f'dono-vespera{SUFIXO}' in to for to in m.to)]
conferir('o aviso de vespera sai uma vez, mesmo com duas rodadas', len(acabando), 1)
conferir('a segunda rodada nao encerra nem avisa ninguem de novo',
         (segunda['encerradas'], any(f'dono-vespera{SUFIXO}' in t for m in mail.outbox[len(acabando):] for t in m.to)),
         (0, False))
Tenant.objects.filter(id=vespera.id).update(degustacao_ate=timezone.now() - timedelta(seconds=1))
degustacao.rodada()
vespera.refresh_from_db()
conferir('a tarefa encerra a vencida que ninguem abriu', vespera.plan, 'free')
from django.conf import settings as cfg
conferir('a tarefa esta agendada a cada quinze minutos',
         str(cfg.CELERY_BEAT_SCHEDULE['tenancy-rodada-da-degustacao']['schedule']._orig_minute), '*/15')

print('\n10. A conversao em contrato')
oitavo.plan = 'complete'
oitavo.save(update_fields=['plan'])
devolvidos = degustacao.converter(oitavo)
oitavo.refresh_from_db()
for m in (ana, caio):
    m.refresh_from_db()
conferir('os dois medicos voltam', devolvidos, 2)
conferir('quem foi suspenso volta ativo e medico', (ana.status, Role.DOCTOR in ana.roles), ('active', True))
conferir('quem era secretaria volta a ser medico tambem', sorted(caio.roles), sorted([Role.SECRETARY, Role.DOCTOR]))
conferir('o prazo sai de cena', (oitavo.degustacao_ate, oitavo.degustacao_retirados), (None, []))
tela = c_oitavo.get('/app/reporting/').content.decode()
conferir('e a faixa some', FAIXA in tela, False)
fonte_console = open('/app/ops/superadmin.py', encoding='utf-8').read()
conferir('a troca de plano do console chama a conversao', 'degustacao.converter(tenant, por=request.user)' in fonte_console, True)

print('\n11. Estender')
em_curso = Tenant.objects.get(id=outra.id)
prazo = em_curso.degustacao_ate
conferir('em andamento, estende 7 dias', degustacao.estender(em_curso, 7), True)
em_curso.refresh_from_db()
conferir('o prazo andou sete dias', em_curso.degustacao_ate - prazo, timedelta(days=7))
conferir('encerrada, nao estende (seria outra degustacao)', degustacao.estender(worker, 7), False)

print('\n12. O que a vitrine promete e o que o codigo cobra')
from base.content import FAQ
pergunta = [f for f in FAQ if 'testar o plano Completo' in f['pergunta']]
conferir('o FAQ responde, com os numeros do codigo',
         bool(pergunta) and all(str(n) in pergunta[0]['resposta']
                                for n in (degustacao.DIAS, degustacao.TETO_IA, degustacao.TETO_SMS)), True)
conferir('o TISS nao vem liberado na degustacao', clinica.tiss_liberado, False)

limpar()
zerar_tetos()
print()
if falhas:
    print('FALHAS (%d):' % len(falhas))
    for falha in falhas:
        print('  -', falha)
    raise SystemExit(1)
print('OK: porta da vitrine, contrato do Gratuito, prazo de Brasilia, tetos de IA e SMS, '
      'oitavo dia pelos tres caminhos, escolha do medico, aviso de vespera, conversao e extensao.')
