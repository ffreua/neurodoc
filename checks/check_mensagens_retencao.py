"""O chat da equipe esquece: 72 horas, ou quando a pessoa apaga.

Até a 1.18 a conversa ficava para sempre — em uso real, recados de
semanas atrás continuavam na janela. O chat é recado interno, não
prontuário, e guardado para sempre viraria um segundo prontuário informal,
sem assinatura e com dado de paciente dentro.

As perguntas que o roteiro faz:

- mensagem com mais de 72 horas **some da janela** antes mesmo de a
  limpeza rodar?
- a limpeza **apaga do banco** o vencido e deixa o recente?
- o contador de não lidas é **refeito** quando some mensagem que ninguém
  leu — senão a badge do cabeçalho acende por mensagem que não existe mais?
- a conversa que ficou vazia é apagada, mas a **recém-aberta** (que ainda
  não teve a primeira mensagem) não, porque sumiria entre o clique e o
  envio?
- "Apagar conversa" apaga **só para quem clicou**, zera o não lido dele, e
  o colega continua vendo tudo?
- quem não participa leva 404, e `GET` não apaga nada?
- a trilha registra que apagou, **sem o texto**?
- mensagem nova depois de apagar aparece normalmente?
- a tela avisa as 72 horas, tem o botão, e o ícone do som troca de verdade?
"""
import json
import re
import uuid
from pathlib import Path

from django.conf import settings as dj_settings
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from audit.models import AuditEvent
from teamchat import services
from teamchat.models import Conversation, ConversationMember, Message
from tenancy.models import Tenant

falhas = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        falhas.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = User.objects.get(email='doctor-b@demo.neurodoc.local')
gestora = User.objects.get(email='manager-a@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')


def entrar(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def corpo(r):
    try:
        return json.loads(r.content.decode('utf-8'))
    except ValueError:
        return {}


# Começa do zero entre os dois: o roteiro não pode depender do que outra
# rodada deixou.
conversa = services.open_direct(tenant.id, medico.id, gestora.id)
Message.objects.filter(conversation=conversa).delete()
ConversationMember.objects.filter(conversation=conversa).update(
    unread_count=0, cleared_at=None, last_read_at=None,
)

agora = timezone.now()
velha = services.send(tenant.id, conversa, gestora.id, 'recado velho do roteiro')
Message.objects.filter(id=velha.id).update(created_at=agora - timezone.timedelta(hours=73))
nova = services.send(tenant.id, conversa, gestora.id, 'recado novo do roteiro')
membro_medico = ConversationMember.objects.get(conversation=conversa, user=medico)
confere(membro_medico.unread_count == 2, 'o médico tem duas mensagens não lidas', membro_medico.unread_count)

cli_medico = entrar(medico)
cli_gestora = entrar(gestora)

print('=== 1. o vencido some da janela antes da limpeza ===')
r = cli_medico.get(f'/app/mensagens/{conversa.id}/')
textos = [m['texto'] for m in corpo(r).get('mensagens', [])] if r.status_code == 200 else []
confere(r.status_code == 200, 'a conversa abre', r.status_code)
confere('recado velho do roteiro' not in textos, 'a mensagem de 73 horas não aparece', textos)
confere('recado novo do roteiro' in textos, 'a mensagem recente aparece', textos)

print('=== 2. a limpeza apaga do banco e refaz o contador ===')
vazia_velha = Conversation.objects.create(
    tenant=tenant, created_by=medico, direct_key=f'roteiro-vazia-{uuid.uuid4().hex[:12]}',
)
Conversation.objects.filter(id=vazia_velha.id).update(created_at=agora - timezone.timedelta(hours=80))
vazia_nova = Conversation.objects.create(
    tenant=tenant, created_by=medico, direct_key=f'roteiro-nova-{uuid.uuid4().hex[:12]}',
)
resultado = services.apagar_vencidas()
print(f'  resultado: {resultado}')
confere(not Message.objects.filter(id=velha.id).exists(), 'a mensagem vencida saiu do banco')
confere(Message.objects.filter(id=nova.id).exists(), 'a mensagem recente ficou')
membro_medico.refresh_from_db()
confere(membro_medico.unread_count == 1, 'o não lido do médico foi refeito para 1',
        membro_medico.unread_count)
confere(not Conversation.objects.filter(id=vazia_velha.id).exists(), 'a conversa vazia antiga foi apagada')
confere(Conversation.objects.filter(id=vazia_nova.id).exists(),
        'a conversa recém-aberta, ainda sem mensagem, ficou')
confere(Conversation.objects.filter(id=conversa.id).exists(), 'a conversa com mensagem recente ficou')

print('=== 3. apagar a conversa vale só para quem apaga ===')
url = f'/app/mensagens/{conversa.id}/apagar/'
r = cli_medico.get(url)
confere(r.status_code == 405, 'GET não apaga (405)', r.status_code)
intruso = entrar(secretaria)
confere(intruso.post(url).status_code == 404, 'quem não participa leva 404')
r = cli_medico.post(url)
confere(r.status_code == 200, 'o médico apaga a conversa', r.status_code)
membro_medico.refresh_from_db()
confere(membro_medico.cleared_at is not None and membro_medico.unread_count == 0,
        'o apagamento é gravado e o não lido do médico vai a zero')
textos_medico = [m['texto'] for m in corpo(cli_medico.get(f'/app/mensagens/{conversa.id}/')).get('mensagens', [])]
textos_gestora = [m['texto'] for m in corpo(cli_gestora.get(f'/app/mensagens/{conversa.id}/')).get('mensagens', [])]
confere(textos_medico == [], 'a janela do médico fica vazia', textos_medico)
confere('recado novo do roteiro' in textos_gestora, 'a gestora continua vendo a conversa', textos_gestora)
confere(Message.objects.filter(id=nova.id).exists(), 'nada foi apagado do banco por um clique')

evento = AuditEvent.objects.filter(
    action='teamchat.conversation_cleared', object_id=conversa.id,
).order_by('-created_at').first()
confere(evento is not None, 'a trilha registra o apagamento')
confere(evento is not None and 'recado' not in json.dumps(evento.integrity_metadata or {})
        and 'recado' not in (evento.purpose or ''), 'a trilha não leva o texto')

print('=== 4. mensagem nova depois de apagar aparece ===')
services.send(tenant.id, conversa, gestora.id, 'depois de apagar')
textos_medico = [m['texto'] for m in corpo(cli_medico.get(f'/app/mensagens/{conversa.id}/')).get('mensagens', [])]
confere(textos_medico == ['depois de apagar'], 'só a mensagem nova aparece para o médico', textos_medico)

print('=== 5. a tela ===')
html = cli_medico.get('/app/reporting/', follow=True).content.decode('utf-8', 'replace')
confere('72 horas' in html, 'o aviso da janela diz que as mensagens somem em 72 horas')
confere('data-nd-tc="apagar"' in html and 'data-url-apagar=' in html, 'o botão Apagar conversa está na janela')
confere('title="Aviso sonoro' in html, 'o botão do som diz para que serve')
js = (Path(dj_settings.BASE_DIR) / 'static/teamchat/teamchat.js').read_text(encoding='utf-8')
confere(not re.search(r'ico(Ligado|Mudo)\.hidden\s*=', js),
        'o ícone do som não é trocado por `.hidden` (que não existe em <svg>)')
confere('tocarAviso(true)' in js, 'ligar o som toca uma amostra')
confere(not re.search(r'window\.(confirm|alert|prompt)\s*\(', js),
        'apagar não usa caixa do navegador')

Message.objects.filter(conversation=conversa).delete()
ConversationMember.objects.filter(conversation=conversa).update(unread_count=0, cleared_at=None)
Conversation.objects.filter(id=vazia_nova.id).delete()

print('---')
if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)
print('OK: o chat da equipe esquece em 72 horas, e cada um apaga a própria janela.')
