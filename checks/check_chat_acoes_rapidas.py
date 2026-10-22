"""As ações rápidas do chat são só texto no campo — e o resto do chat continua igual?

Os quatro cartões (revisar diagnóstico, revisar evolução, preparar retorno,
explicar ao paciente) escrevem um pedido pronto no campo de mensagem. O
pedido segue depois pelo caminho de qualquer mensagem. O que este roteiro
tenta quebrar:

- os cartões aparecem só na conversa com paciente, e só para quem já abre o
  chat (secretária, gestor e outra clínica continuam de fora);
- o cartão não envia: é botão comum, sem formulário, e o script não chama
  `submit` nesse caminho; o rascunho já digitado é preservado;
- o texto é estático, não traz dado de paciente, e não escapa do atributo;
- a mensagem enviada percorre a view de sempre, a tarefa recebe só
  identificadores, e o modelo recebe instrução de sistema, prontuário
  desidentificado e o pedido — com o provedor **simulado**;
- o pedido manda reconhecer o recorte e o dado ausente, e não prescrever;
- nada no prontuário muda, e o modelo do chat não ganhou campo novo.

Nenhuma chamada a provedor real.
"""
import re
from pathlib import Path
from unittest import mock

from django.conf import settings as dj_settings
from django.test import Client
from django.urls import reverse

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.AI_ENABLED = True

from accounts.models import User
from ai import tasks as ai_tasks
from ai.acoes_rapidas import ACOES
from ai.chat_models import ChatMessage, ChatMessageRole, ChatSession
from clinical.models import Encounter
from patients.models import Patient
from tenancy.models import Tenant

falhas = []
criadas = []


def conferir(condicao, mensagem):
    print(f'  {"ok   " if condicao else "FALHA"} {mensagem}')
    if not condicao:
        falhas.append(mensagem)


tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
medico_b = User.objects.get(email='doctor-b@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
gestora = User.objects.get(email='manager-a@demo.neurodoc.local')
paciente = Patient.objects.get(tenant=tenant_a, full_name__iexact='Carlos Adulto da Silva')


def cliente(user, tenant, **kw):
    c = Client(**kw)
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def sessao(patient=None):
    s = ChatSession.objects.create(tenant=tenant_a, owner_user=medico, patient=patient, title='check acoes')
    criadas.append(s.id)
    return s


com_paciente = sessao(paciente)
sem_paciente = sessao(None)
url_com = reverse('ai:chat-session-detail', args=[com_paciente.id])
url_sem = reverse('ai:chat-session-detail', args=[sem_paciente.id])

try:
    print('=== 1. visibilidade ===')
    c = cliente(medico, tenant_a)
    html = c.get(url_com).content.decode()
    ids = re.findall(r'data-nd-acao="([a-z_]+)"', html)
    conferir(ids == [a.id for a in ACOES] and len(ids) == 4,
             f'conversa com paciente mostra os quatro cartões, na ordem ({ids})')
    for a in ACOES:
        conferir(a.rotulo in html, f'cartão "{a.rotulo}" com o rótulo visível')
    html_sem = c.get(url_sem).content.decode()
    conferir('nd-chat-acoes' not in html_sem and 'data-nd-acao' not in html_sem,
             'conversa sem paciente não mostra os cartões')
    conferir('id="chat-content"' in html_sem and 'nd-chat-form' in html_sem,
             'conversa sem paciente mantém o campo e o envio de sempre')
    for rotulo, user, tenant in [('secretária', secretaria, tenant_a), ('gestora', gestora, tenant_a)]:
        r = cliente(user, tenant).get(url_com)
        conferir(r.status_code == 404 and b'data-nd-acao' not in r.content,
                 f'{rotulo} não abre a conversa clínica ({r.status_code})')
    r = cliente(medico_b, tenant_b).get(url_com)
    conferir(r.status_code == 404, f'médico de outra clínica não abre a conversa ({r.status_code})')
    r = cliente(medico_b, tenant_a).get(url_com) if medico_b.memberships.filter(tenant=tenant_a).exists() else None
    if r is not None:
        conferir(r.status_code == 404, f'outro médico da mesma clínica não abre conversa alheia ({r.status_code})')

    print('=== 2. o cartão só escreve no campo ===')
    blocos = re.findall(r'<button[^>]*data-nd-acao="[^"]*"[^>]*>', html)
    conferir(len(blocos) == 4 and all('type="button"' in b for b in blocos),
             'os quatro cartões são type="button" (não enviam o formulário)')
    conferir(not any('onclick' in b.lower() for b in blocos), 'sem manipulador embutido (CSP)')
    inicio = html.find('nd-chat-acoes')
    conferir(0 < inicio < html.find('id="nd-chat-form"'),
             'os cartões ficam fora do formulário de envio')
    js = Path('static/ai/chat-shell.js').read_text(encoding='utf-8')
    trecho = js[js.find('data-nd-acao-texto'):js.find('/* --------------------------------------------- filtro')]
    conferir(bool(trecho) and 'submit' not in trecho and 'requestSubmit' not in trecho,
             'o clique do cartão não chama submit')
    conferir("atual.trim() ?" in trecho and "'\\n\\n'" in trecho,
             'texto já digitado é preservado (o pedido entra depois dele)')
    conferir('atual.indexOf(pedido) === -1' in trecho, 'clicar duas vezes não duplica o pedido')
    conferir("event.key !== 'Enter' || event.shiftKey" in js and 'event.isComposing' in js,
             'Enter envia e Shift+Enter quebra linha, com a composição de acento intacta')
    for a in ACOES:
        conferir('<' not in a.texto and '>' not in a.texto and '{{' not in a.texto,
                 f'"{a.id}": texto sem marcação nem variável de template')
        esperado = a.texto.replace('&', '&amp;').replace('"', '&quot;').replace("'", '&#x27;')
        conferir(esperado in html, f'"{a.id}": texto chega inteiro e escapado no atributo')
    nome = paciente.full_name.lower()
    conferir(all(nome not in a.texto.lower() for a in ACOES), 'nenhum texto traz o nome do paciente')

    print('=== 3. a mensagem segue o caminho de sempre ===')
    acao = ACOES[0]
    rascunho = 'Paciente relata piora das cefaleias.'
    conteudo = rascunho + '\n\n' + acao.texto
    with mock.patch('ai.chat_views.run_chat_turn.delay') as enfileirar:
        r = c.post(reverse('ai:chat-message-create', args=[com_paciente.id]), {'content': conteudo})
    conferir(r.status_code == 302, f'envio pela view de sempre redireciona ({r.status_code})')
    usuario = ChatMessage.objects.filter(session=com_paciente, role=ChatMessageRole.USER).order_by('-sequence').first()
    assistente = ChatMessage.objects.filter(session=com_paciente, role=ChatMessageRole.ASSISTANT).order_by('-sequence').first()
    conferir(usuario is not None and usuario.content == conteudo.strip(),
             'a mensagem gravada é exatamente o que estava no campo (rascunho + pedido)')
    args = enfileirar.call_args[0] if enfileirar.called else ()
    conferir(enfileirar.call_count == 1 and set(args) == {str(assistente.id), str(usuario.id)},
             'a tarefa recebe só os dois identificadores, nunca o texto')

    capturado = {}

    class ModeloFalso:
        def stream(self, prompt):
            capturado['prompt'] = prompt
            yield type('C', (), {'content': 'Rascunho de revisão para o médico.'})()

    encontro = Encounter.objects.filter(tenant=tenant_a, patient=paciente).order_by('-occurred_at').first()
    antes = (encontro.content_hash, encontro.row_version, encontro.status) if encontro else None
    with mock.patch.object(ai_tasks, 'get_chat_model', return_value=ModeloFalso()):
        ai_tasks.run_chat_turn(str(assistente.id), str(usuario.id))
    prompt = capturado.get('prompt') or []
    sistema = getattr(prompt[0], 'content', '') if prompt else ''
    tudo = '\n'.join(str(getattr(m, 'content', '')) for m in prompt)
    conferir(sistema.startswith('Você é um assistente de redação'),
             'a instrução de sistema de sempre vem primeiro')
    conferir('REGRAS ABSOLUTAS' in sistema, 'as regras absolutas continuam acima do pedido')
    conferir('DADOS DO PRONTUÁRIO' in tudo or 'Atendimentos' in tudo,
             'o prontuário do paciente da sessão vai junto')
    conferir(paciente.full_name.upper() not in tudo.upper(),
             'o nome do paciente não sai da instalação (desidentificação)')
    conferir(acao.texto.split('\n')[0] in str(getattr(prompt[-1], 'content', '')),
             'o pedido da ação chega como a última mensagem do médico')
    assistente.refresh_from_db()
    conferir(assistente.state == 'complete' and assistente.content.startswith('Rascunho de revisão'),
             f'a resposta é gravada como sempre ({assistente.state})')
    if encontro:
        encontro.refresh_from_db()
        conferir((encontro.content_hash, encontro.row_version, encontro.status) == antes,
                 'o atendimento do paciente não muda')

    print('=== 4. o pedido não induz invenção nem conduta ===')
    for a in ACOES:
        t = a.texto.lower()
        conferir('recorte' in t and 'não diga que revisou tudo' in t,
                 f'"{a.id}": declara que o modelo recebeu um recorte')
        conferir('dado ausente não é resultado normal' in t, f'"{a.id}": dado ausente não vira normal')
    t = {a.id: a.texto.lower() for a in ACOES}
    conferir('não prescreva tratamento' in t['revisao_diagnostica']
             and 'não dê diagnóstico definitivo' in t['revisao_diagnostica']
             and 'probabilidade numérica' in t['revisao_diagnostica'],
             'revisão diagnóstica: sem diagnóstico definitivo, probabilidade nem tratamento')
    conferir('rascunho' in t['revisao_evolucao'] and 'cole o trecho' in t['revisao_evolucao'],
             'revisão da evolução: admite não ver o rascunho de hoje e pede o trecho')
    conferir('pendente' in t['preparar_retorno'] and 'não sugira agendamentos' in t['preparar_retorno'],
             'preparar retorno: ausência no recorte não vira exame pendente, nada é agendado')
    conferir('não acrescente tratamento' in t['orientacoes_paciente']
             and 'rascunho para revisão do médico' in t['orientacoes_paciente'],
             'explicar ao paciente: sem tratamento novo, termina como rascunho')

    print('=== 5. nada novo no modelo do chat ===')
    campos = {f.name for f in ChatMessage._meta.get_fields()}
    conferir(not any('acao' in nome for nome in campos), 'ChatMessage sem campo de ação')
    migracoes = sorted(p.name for p in Path('ai/migrations').glob('0*.py'))
    conferir(not any('acao' in m for m in migracoes), 'nenhuma migração para as ações')

    print('=== 6. CSRF continua valendo no envio ===')
    c_csrf = cliente(medico, tenant_a, enforce_csrf_checks=True)
    with mock.patch('ai.chat_views.run_chat_turn.delay') as enfileirar:
        r = c_csrf.post(reverse('ai:chat-message-create', args=[com_paciente.id]), {'content': ACOES[1].texto})
    conferir(r.status_code == 403 and not enfileirar.called, f'envio sem token é recusado ({r.status_code})')
finally:
    # Na ordem da própria tela de apagar: as mensagens protegem a conversa,
    # e o job de cada uma sai depois delas.
    from ai.models import AIJob

    jobs = list(ChatMessage.objects.filter(session_id__in=criadas, ai_job__isnull=False)
                .values_list('ai_job_id', flat=True))
    ChatMessage.objects.filter(session_id__in=criadas).delete()
    AIJob.objects.filter(id__in=jobs).delete()
    ChatSession.objects.filter(id__in=criadas).delete()

if falhas:
    print(f'\nFALHA: {len(falhas)} problema(s):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('\nOK: as ações rápidas só escrevem no campo, e o chat segue igual.')
