"""O e-mail sai mesmo -- e sai pelo worker, como tem de ser em producao?

O defeito que originou este roteiro nao era "o e-mail esta desligado".
Era que **o e-mail de conta nunca funcionaria em producao**, ligado ou
nao: `send_email_verification` falava com o SMTP dentro da requisicao, no
processo `app`, e no Swarm o `app` esta em `traefik_public` +
`neurodoc_v1_internal` -- sem saida para a internet. Quem alcanca a
internet e o worker, em `neurodoc_v1_egress`.

O desenho ja sabia disso: `NEURODOC_SMTP_PASSWORD` so e entregue ao
worker, e `core/settings.py` so a exige quando `SERVICE_ROLE == 'worker'`.
Faltava o caminho.

As perguntas sao:

- o processo web enfileira em vez de falar com o SMTP?
- a mensagem chega de verdade, passando pelo worker?
- verificacao de conta e recuperacao de senha usam esse caminho?
- a tarefa pede o backend SMTP explicitamente (senao a fila se realimenta)?
- anexo e recusado com clareza em vez de sumir?

Depende do Mailpit do ambiente local (`ops/local_compose.py`). Com o envio
desligado, o roteiro diz o que falta e sai sem falhar: nao ha o que
verificar quando o backend e a caixa em memoria.
"""
import json
import time
import urllib.error
import urllib.request

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

falhas = []
MAILPIT = 'http://mailpit:8025/api/v1'


def caixa(caminho='/messages?limit=50'):
    with urllib.request.urlopen(MAILPIT + caminho, timeout=5) as resposta:
        return json.loads(resposta.read())


def limpar():
    pedido = urllib.request.Request(MAILPIT + '/messages', method='DELETE')
    urllib.request.urlopen(pedido, timeout=5).read()


def esperar(predicado, segundos=20):
    """Espera a mensagem aparecer na caixa.

    O envio e assincrono de proposito -- e esse o ponto do roteiro --,
    entao conferir na hora seguinte a chamada leria uma caixa vazia e
    acusaria falha onde ha apenas latencia de fila.
    """
    limite = time.time() + segundos
    while time.time() < limite:
        encontradas = [m for m in caixa()['messages'] if predicado(m)]
        if encontradas:
            return encontradas
        time.sleep(0.5)
    return []


print('=== 0. o ambiente tem o que verificar? ===')
print(f'  EMAIL_ENABLED={dj_settings.EMAIL_ENABLED}')
print(f'  backend={dj_settings.EMAIL_BACKEND}')
print(f'  servidor={dj_settings.EMAIL_HOST}:{dj_settings.EMAIL_PORT}')
if not dj_settings.EMAIL_ENABLED:
    print('---')
    print('PULADO: envio desligado (EMAIL_ENABLED=False), backend e a caixa em '
          'memoria. Ligue no .env e rode `python -m ops.local_compose` para '
          'exercitar o caminho de verdade.')
    raise SystemExit(0)
try:
    limpar()
except (urllib.error.URLError, OSError) as exc:
    print('---')
    print(f'PULADO: Mailpit inalcancavel ({exc}). Suba a pilha local completa.')
    raise SystemExit(0)

print('=== 1. o processo web enfileira, nao fala com o SMTP ===')
esperado = 'communications.mail_backend.WorkerEmailBackend'
print(f'  backend em uso e o da fila={dj_settings.EMAIL_BACKEND == esperado}')
if dj_settings.EMAIL_BACKEND != esperado:
    falhas.append(
        'com o envio ligado, o backend padrao deveria ser o que enfileira: '
        'falar com o SMTP daqui nao funciona em producao (o app nao tem egresso)'
    )

print('=== 2. a mensagem atravessa a fila e chega ===')
from django.core.mail import send_mail

MARCADOR = f'roteiro-{int(time.time())}'
send_mail(
    subject=f'NeuroDoc {MARCADOR}', message='corpo do roteiro',
    from_email=dj_settings.DEFAULT_FROM_EMAIL,
    recipient_list=['destino-roteiro@example.invalid'],
)
chegadas = esperar(lambda m: MARCADOR in m['Subject'])
print(f'  chegou na caixa={bool(chegadas)}')
if not chegadas:
    falhas.append('a mensagem foi enfileirada e nunca chegou: o worker nao entrega')
else:
    print(f'  remetente={chegadas[0]["From"]["Address"]}  '
          f'destino={chegadas[0]["To"][0]["Address"]}')

print('=== 3. verificacao de conta usa o caminho ===')
# E o fluxo que o usuario encontrou quebrado: criar a clinica pelo convite
# manda um e-mail de ativacao que nunca saia.
from accounts.models import User
from accounts.services import send_email_verification

limpar()
alvo = User.objects.filter(email='doctor-a@demo.neurodoc.local').first()
pedido = type('R', (), {'build_absolute_uri': lambda self, p: 'http://localhost:8001' + p})()
send_email_verification(alvo, pedido)
chegadas = esperar(lambda m: alvo.email in [d['Address'] for d in m['To']])
print(f'  e-mail de verificacao chegou={bool(chegadas)}')
if not chegadas:
    falhas.append('o e-mail de verificacao de conta nao chega ao destinatario')
else:
    assunto = chegadas[0]['Subject']
    print(f'  assunto={assunto!r}')
    if 'onfirme' not in assunto:
        falhas.append(f'o assunto da verificacao mudou sem aviso: {assunto!r}')

print('=== 4. recuperacao de senha usa o caminho ===')
# Nao passa por codigo nosso: e o `PasswordResetForm` do proprio Django,
# que chama `send_mail`. E justamente por isso o backend resolve, e uma
# tarefa em cada ponto de envio nao resolveria.
limpar()
c = Client()
c.post('/accounts/password-reset/', {'email': alvo.email})
chegadas = esperar(lambda m: alvo.email in [d['Address'] for d in m['To']])
print(f'  e-mail de recuperacao chegou={bool(chegadas)}')
if not chegadas:
    falhas.append('a recuperacao de senha nao chega: o formulario do Django nao passa pela fila')
else:
    corpo = caixa(f'/message/{chegadas[0]["ID"]}')
    texto = corpo.get('Text') or ''
    tem_link = '/accounts/reset/' in texto
    print(f'  traz o link de redefinicao={tem_link}')
    if not tem_link:
        falhas.append('o e-mail de recuperacao chegou sem o link de redefinicao')

print('=== 5. a tarefa nao realimenta a fila ===')
# Se a tarefa usasse `EMAIL_BACKEND`, leria o backend que enfileira e a
# mensagem daria voltas para sempre. A checagem e no codigo, porque o
# sintoma (fila crescendo) so aparece em producao.
import inspect

from communications import tasks

fonte = inspect.getsource(tasks.deliver_installation_email)
explicito = "backend='django.core.mail.backends.smtp.EmailBackend'" in fonte
print(f'  pede o backend SMTP explicitamente={explicito}')
if not explicito:
    falhas.append('a tarefa de entrega usa o backend padrao: a fila se realimenta')

print('=== 6. anexo e recusado, nao descartado ===')
from django.core.mail import EmailMessage

from communications.mail_backend import AttachmentNotSupported, WorkerEmailBackend

com_anexo = EmailMessage(
    subject='com anexo', body='x', from_email=dj_settings.DEFAULT_FROM_EMAIL,
    to=['alguem@example.invalid'],
)
com_anexo.attach('laudo.pdf', b'%PDF-1.4 conteudo', 'application/pdf')
try:
    WorkerEmailBackend().send_messages([com_anexo])
    print('  anexo passou em silencio (nao deveria)')
    falhas.append('anexo passou pela fila em silencio: o PDF sumiria sem aviso')
except AttachmentNotSupported as exc:
    print(f'  recusado com explicacao: {str(exc)[:60]}...')

limpar()
print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o web enfileira, o worker entrega, e conta e senha chegam.')
