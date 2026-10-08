"""Notificacoes: de quem se trata, para onde levam, e quem as recebe.

O que este teste tenta quebrar: aviso que nao diz o paciente, botao que
leva a 404, aviso entregue a quem nao pode abrir o destino, "marcar todas"
alcancando a caixa de outra clinica ou de outra pessoa, e alvo apagado
derrubando a tela.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from django.contrib.messages import get_messages
from django.utils import timezone

from accounts.models import User
from documents.models import (
    DocumentRequest, DocumentRequestKind, DocumentRequestStatus,
)
from notifications import targets
from notifications.models import Notification
from notifications.services import notify_capability, patient_context
from patients.models import Patient
from tenancy.models import Membership, Tenant
from tenancy.permissions import Capability

TENANT = 'demo-clinica-a'
TENANT_B = 'demo-clinica-b'
falhas = []
criados = {'pedidos': [], 'avisos': []}


def note(r):
    itens = [str(m) for m in get_messages(r.wsgi_request)]
    return itens[-1] if itens else '(sem aviso)'


def client_for(email, slug=TENANT):
    user = User.objects.get(email=email)
    m = Membership.objects.get(user=user, tenant__slug=slug)
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(m.tenant_id)
    s.save()
    return c, user, m


dono, u_dono, m_dono = client_for('doctor-a@demo.neurodoc.local')
secretaria, u_sec, m_sec = client_for('secretary-a@demo.neurodoc.local')
tenant = Tenant.objects.get(slug=TENANT)
paciente = Patient.objects.filter(tenant=tenant, status='active').first()

print('=' * 66)
print('1. O AVISO NOMEIA O PACIENTE')
print('=' * 66)

pedido = DocumentRequest.objects.create(
    tenant=tenant, patient=paciente, kind=DocumentRequestKind.PRESCRIPTION_SIMPLE,
    requester_name='Filha do paciente', requester_is_patient=False,
    payload={'medicacoes': [{'nome': 'Keppra', 'dose': '', 'uso': ''}]},
    status=DocumentRequestStatus.RECEIVED,
    privacy_ack_at=timezone.now(), privacy_notice_version='2026-09-v1',
)
criados['pedidos'].append(pedido.id)

feitos = notify_capability(
    tenant, Capability.READ_CLINICAL, kind='portal_request',
    sanitized_title=f'{pedido.get_kind_display()} solicitada no portal',
    target_type='document_request', target_id=pedido.id,
    context=patient_context(paciente, requester='Filha do paciente'),
)
criados['avisos'].extend(n.id for n in Notification.objects.filter(
    tenant=tenant, target_id=pedido.id))
print('  destinatarios ->', len(feitos))

aviso = Notification.objects.filter(tenant=tenant, target_id=pedido.id, user=u_dono).first()
if aviso is None:
    falhas.append('o medico nao recebeu o aviso do pedido')
else:
    print('  titulo  ->', aviso.sanitized_title)
    print('  contexto->', aviso.context)
    if aviso.context.get('patient') != paciente.full_name:
        falhas.append('o aviso nao carrega o nome do paciente')
    if not aviso.context.get('record_number'):
        falhas.append('o aviso nao carrega o numero do prontuario')

print()
print('=' * 66)
print('2. SO RECEBE QUEM PODE ABRIR')
print('=' * 66)
# A fila do portal exige capacidade clinica. A secretaria nao a tem, e
# receber o aviso seria saber que aquele paciente pediu alguma coisa, com
# um botao que responde 404.
da_secretaria = Notification.objects.filter(
    tenant=tenant, target_id=pedido.id, user=u_sec).exists()
print('  secretaria recebeu o aviso do portal ->', da_secretaria)
if da_secretaria:
    falhas.append('a secretaria recebeu aviso de pedido que nao pode abrir')

print()
print('=' * 66)
print('3. O BOTAO LEVA AO LUGAR CERTO')
print('=' * 66)
url = targets.url_for(aviso)
print('  destino ->', url)
if url != f'/app/documents/solicitacoes/{pedido.id}/':
    falhas.append(f'o destino do aviso esta errado: {url}')

r = dono.get('/app/notifications/')
corpo = r.content.decode()
print('  a lista mostra o paciente ->', paciente.full_name in corpo)
print('  a lista mostra o botao    ->', 'Revisar solicitação' in corpo)
if paciente.full_name not in corpo:
    falhas.append('a lista nao mostra o nome do paciente')
if 'Revisar solicitação' not in corpo:
    falhas.append('a lista nao mostra o botao de resolucao')

r = dono.post(f'/app/notifications/{aviso.id}/abrir/', follow=True)
aviso.refresh_from_db()
destino = r.request['PATH_INFO']
print('  abrir -> ', destino, '| marcada como lida:', aviso.read_at is not None)
if destino != url:
    falhas.append(f'abrir levou a {destino} em vez de {url}')
if aviso.read_at is None:
    falhas.append('abrir nao marcou como lida')

print()
print('=' * 66)
print('4. ABRIR E POST, NAO GET')
print('=' * 66)
# Um GET que altera estado e disparado por qualquer coisa que pre-carregue
# enderecos — o navegador faz isso sozinho, e a caixa se marcaria lida
# sozinha.
outro = Notification.objects.create(
    tenant=tenant, user=u_dono, kind='teste', sanitized_title='Teste GET',
    target_type='document_request', target_id=pedido.id,
)
criados['avisos'].append(outro.id)
r = dono.get(f'/app/notifications/{outro.id}/abrir/')
outro.refresh_from_db()
print('  GET em /abrir/ ->', r.status_code, '| marcada como lida:', outro.read_at is not None)
if outro.read_at is not None:
    falhas.append('um GET marcou a notificacao como lida')

print()
print('=' * 66)
print('5. ALVO APAGADO NAO DERRUBA A TELA')
print('=' * 66)
orfao = Notification.objects.create(
    tenant=tenant, user=u_dono, kind='portal_request',
    sanitized_title='Pedido que nao existe mais',
    target_type='document_request',
    target_id='00000000-0000-4000-8000-000000000000',
)
criados['avisos'].append(orfao.id)
r = dono.post(f'/app/notifications/{orfao.id}/abrir/', follow=True)
orfao.refresh_from_db()
print('  abrir alvo inexistente ->', note(r))
print('  marcada como lida      ->', orfao.read_at is not None)
if orfao.read_at is None:
    falhas.append('o aviso orfao nao foi marcado como lido')
if r.request['PATH_INFO'] != '/app/notifications/':
    falhas.append('o aviso orfao nao devolveu a lista')

sem_alvo = Notification.objects.create(
    tenant=tenant, user=u_dono, kind='desconhecido',
    sanitized_title='Aviso de um tipo que saiu do produto',
    target_type='tipo_que_nao_existe', target_id=pedido.id,
)
criados['avisos'].append(sem_alvo.id)
print('  url de tipo desconhecido ->', targets.url_for(sem_alvo))
if targets.url_for(sem_alvo) is not None:
    falhas.append('um tipo desconhecido devolveu URL')
r = dono.get('/app/notifications/')
print('  a lista aguenta o tipo desconhecido ->', r.status_code)
if r.status_code != 200:
    falhas.append('a lista quebrou com um tipo desconhecido')

print()
print('=' * 66)
print('5b. AS NAO LIDAS VEM PRIMEIRO')
print('=' * 66)
# No PostgreSQL, `ORDER BY` crescente de coluna anulavel poe o NULL no
# **fim** — e `read_at` nulo e exatamente a nao lida. Sem `nulls_first` a
# ordem sai ao contrario, e nenhum teste de conteudo percebe: as linhas
# estao todas la.
Notification.objects.filter(tenant=tenant, user=u_dono).update(
    read_at=timezone.now())
recente = Notification.objects.create(
    tenant=tenant, user=u_dono, kind='teste',
    sanitized_title='ESTA E A NAO LIDA', target_type='patient', target_id=paciente.id)
criados['avisos'].append(recente.id)
r = dono.get('/app/notifications/')
corpo = r.content.decode()
posicao_nao_lida = corpo.find('ESTA E A NAO LIDA')
primeira_lida = corpo.find('lida</span>')
print('  a nao lida aparece antes de qualquer lida ->',
      posicao_nao_lida != -1 and (primeira_lida == -1 or posicao_nao_lida < primeira_lida))
if posicao_nao_lida == -1:
    falhas.append('a nao lida nao apareceu na lista')
elif primeira_lida != -1 and posicao_nao_lida > primeira_lida:
    falhas.append('as lidas vieram antes das nao lidas — falta nulls_first na ordenacao')

print()
print('=' * 66)
print('6. MARCAR TODAS')
print('=' * 66)
Notification.objects.filter(tenant=tenant, user=u_dono).update(read_at=None)
nao_lidas = Notification.objects.filter(tenant=tenant, user=u_dono, read_at__isnull=True).count()

# Uma nao lida da outra clinica, e uma de outra pessoa: nenhuma das duas
# pode ser tocada.
tenant_b = Tenant.objects.get(slug=TENANT_B)
alheia_clinica = Notification.objects.create(
    tenant=tenant_b, user=u_dono, kind='teste',
    sanitized_title='Da clinica B, nao pode ser tocada')
alheia_pessoa = Notification.objects.create(
    tenant=tenant, user=u_sec, kind='teste',
    sanitized_title='Da secretaria, nao pode ser tocada')
criados['avisos'].extend([alheia_clinica.id, alheia_pessoa.id])

r = dono.post('/app/notifications/marcar-todas/', follow=True)
print(f'  {nao_lidas} nao lidas ->', note(r))
restantes = Notification.objects.filter(
    tenant=tenant, user=u_dono, read_at__isnull=True).count()
print('  sobrou nao lida na clinica A ->', restantes)
if restantes:
    falhas.append(f'{restantes} notificacao(oes) ficaram nao lidas')

alheia_clinica.refresh_from_db()
alheia_pessoa.refresh_from_db()
print('  a da clinica B continua nao lida ->', alheia_clinica.read_at is None)
print('  a da secretaria continua nao lida ->', alheia_pessoa.read_at is None)
if alheia_clinica.read_at is not None:
    falhas.append('"marcar todas" alcancou a caixa da outra clinica')
if alheia_pessoa.read_at is not None:
    falhas.append('"marcar todas" alcancou a caixa de outra pessoa')

# Sem nao lidas, a acao diz isso em vez de fingir que fez algo.
r = dono.post('/app/notifications/marcar-todas/', follow=True)
print('  com a caixa limpa ->', note(r))

print()
print('=' * 66)
print('7. NINGUEM LE A CAIXA DE OUTRO')
print('=' * 66)
alvo_alheio = Notification.objects.filter(tenant=tenant, user=u_sec).first()
if alvo_alheio is not None:
    r = dono.post(f'/app/notifications/{alvo_alheio.id}/read/')
    print('  medico marca aviso da secretaria ->', r.status_code)
    if r.status_code != 404:
        falhas.append(f'um usuario marcou a notificacao de outro (HTTP {r.status_code})')

print()
print('=' * 66)
print('8. LIMPAR TODAS')
print('=' * 66)
# Apaga lidas e nao lidas desta pessoa nesta clinica -- e nada alem disso.
# As alheias da secao 6 voltam a ser criadas aqui, porque `marcar todas`
# ja as conferiu como lidas/nao lidas e o que interessa agora e se
# continuam EXISTINDO.
Notification.objects.create(tenant=tenant, user=u_dono, kind='teste',
                            sanitized_title='Lida, para limpar', read_at=timezone.now())
Notification.objects.create(tenant=tenant, user=u_dono, kind='teste',
                            sanitized_title='Nao lida, para limpar')
pedido_antes = DocumentRequest.objects.filter(id__in=criados['pedidos']).count()
minhas = Notification.objects.filter(tenant=tenant, user=u_dono).count()

r = dono.get('/app/notifications/limpar/')
print('  GET em limpar ->', r.status_code)
if r.status_code != 405:
    falhas.append(f'limpar aceitou GET (HTTP {r.status_code}) -- pre-carga apagaria a caixa')
if Notification.objects.filter(tenant=tenant, user=u_dono).count() != minhas:
    falhas.append('um GET apagou notificacoes')

r = dono.post('/app/notifications/limpar/', follow=True)
print(f'  {minhas} na caixa ->', note(r))
sobrou = Notification.objects.filter(tenant=tenant, user=u_dono).count()
print('  sobrou na caixa do medico na clinica A ->', sobrou)
if sobrou:
    falhas.append(f'{sobrou} notificacao(oes) ficaram depois de limpar')
if str(minhas) not in note(r):
    falhas.append('a confirmacao nao diz quantas sairam')
print('  a da clinica B continua existindo ->',
      Notification.objects.filter(id=alheia_clinica.id).exists())
print('  a da secretaria continua existindo ->',
      Notification.objects.filter(id=alheia_pessoa.id).exists())
if not Notification.objects.filter(id=alheia_clinica.id).exists():
    falhas.append('"limpar" apagou a caixa da outra clinica')
if not Notification.objects.filter(id=alheia_pessoa.id).exists():
    falhas.append('"limpar" apagou a caixa de outra pessoa')
if DocumentRequest.objects.filter(id__in=criados['pedidos']).count() != pedido_antes:
    falhas.append('limpar a caixa apagou o pedido do portal que o aviso apontava')
print('  o pedido do portal continua na fila ->',
      DocumentRequest.objects.filter(id__in=criados['pedidos']).count() == pedido_antes)

r = dono.post('/app/notifications/limpar/', follow=True)
print('  com a caixa vazia ->', note(r))
if 'vazia' not in note(r):
    falhas.append('limpar a caixa vazia nao diz que ja estava vazia')

# Os dois botoes pedem confirmacao, e pelo atributo -- `onclick` seria
# barrado pela politica de conteudo.
Notification.objects.create(tenant=tenant, user=u_dono, kind='teste',
                            sanitized_title='Para o botao aparecer')
pagina = dono.get('/app/notifications/').content.decode()
botoes = pagina.count('action="/app/notifications/limpar/"')
confirmados = pagina.count('data-nd-confirm="Limpar todas as notificações')
print(f'  botoes de limpar na pagina (central + sino) -> {botoes}, com confirmacao -> {confirmados}')
if botoes != 2:
    falhas.append(f'esperava o botao na central e no sino, achei {botoes}')
if confirmados != botoes:
    falhas.append('botao de limpar sem confirmacao')
Notification.objects.filter(tenant=tenant, user=u_dono, kind='teste').delete()

# ---------------------------------------------------------------- limpeza
Notification.objects.filter(id__in=criados['avisos']).delete()
Notification.objects.filter(target_id__in=criados['pedidos']).delete()
DocumentRequest.objects.filter(id__in=criados['pedidos']).delete()
print()
print('limpeza concluida')

print('---')
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: o aviso diz de quem e, leva a resolucao, e so alcanca quem pode agir.')
