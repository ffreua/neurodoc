"""A janela de mensagens da equipe isola, conta certo e nao vaza?

Tenta quebrar. As perguntas sao:

- abrir a conversa dos dois lados cria UMA conversa, ou duas mudas?
- um terceiro da MESMA clinica le a conversa alheia? (o caso dificil: o
  escopo por inquilino nao ajuda em nada aqui)
- um id de usuario de OUTRA clinica abre conversa atravessando a fronteira?
- o contador nao lido bate com a contagem real de mensagens?
- quem envia incrementa o proprio nao lido?
- marcar como lida zera, e a badge do cabecalho acompanha?
- mensagem vazia e mensagem gigante sao recusadas?
- clinica suspensa recusa o ENVIO e continua deixando marcar como lida?
- o corpo da mensagem atravessa intacto, servido como JSON com nosniff, e o
  cliente nunca o insere como marcacao?
- uma conexao NOVA de SSE reentrega o historico que o Redis ainda guarda?
- a pagina entrega o cookie de CSRF que o cliente le na hora de enviar?
- a badge do cabecalho traz a contagem, e as pecas do aviso instantaneo
  continuam no cliente?
- o estado diz de quem e a sessao, para a aba descobrir que outra conta
  entrou no mesmo navegador?
- trocar de pessoa deixa a conversa anterior armada para receber o texto?

ATENCAO: a secao 8 deixa a clinica demo A SUSPENSA por alguns segundos e a
restaura em seguida. Se alguem estiver usando a demo nesse instante, vera o
envio recusado — nao rode com gente testando do outro lado.
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

import json
import re

BASE_DIR = dj_settings.BASE_DIR

from accounts.models import User
from teamchat import services, streaming
from teamchat.models import Conversation, ConversationMember, Message, direct_key_for
from tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

failures = []

tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
status_original = tenant_a.status

medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
medico2 = User.objects.get(email='doctor-b@demo.neurodoc.local')
secretaria = User.objects.get(email='secretary-a@demo.neurodoc.local')
gestora = User.objects.get(email='manager-a@demo.neurodoc.local')

criadas = []


def entrar(user, tenant=None):
    tenant = tenant or tenant_a
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


def corpo(resposta):
    try:
        return json.loads(resposta.content.decode('utf-8'))
    except ValueError:
        return {}


print('=== 1. a conversa e a mesma pelos dois lados ===')
c1 = services.open_direct(tenant_a.id, medico.id, secretaria.id)
c2 = services.open_direct(tenant_a.id, secretaria.id, medico.id)
criadas.append(c1)
print(f'  medico->secretaria = {c1.id}')
print(f'  secretaria->medico = {c2.id}')
print(f'  chave canonica     = {direct_key_for(medico.id, secretaria.id)}')
if c1.id != c2.id:
    failures.append('abrir dos dois lados criou duas conversas — cada um escreve numa que o outro nao le')
if Conversation.objects.filter(tenant=tenant_a, direct_key=c1.direct_key).count() != 1:
    failures.append('mais de uma conversa com a mesma chave canonica')

print('=== 2. um terceiro da mesma clinica nao le nem escreve ===')
terceiro = entrar(gestora)
r = terceiro.get(f'/app/mensagens/{c1.id}/')
print(f'  gestora GET conversa alheia   -> {r.status_code} (404 esperado)')
if r.status_code != 404:
    failures.append(f'terceiro leu conversa alheia da mesma clinica ({r.status_code})')
r = terceiro.post(f'/app/mensagens/{c1.id}/enviar/', json.dumps({'texto': 'intruso'}),
                  content_type='application/json')
print(f'  gestora POST enviar           -> {r.status_code} (404 esperado)')
if r.status_code != 404:
    failures.append(f'terceiro escreveu em conversa alheia ({r.status_code})')
r = terceiro.post(f'/app/mensagens/lida/{c1.id}/', '{}', content_type='application/json')
print(f'  gestora POST marcar lida      -> {r.status_code} (404 esperado)')
if r.status_code != 404:
    failures.append(f'terceiro marcou conversa alheia como lida ({r.status_code})')

print('=== 3. fronteira entre clinicas ===')
# A gestora existe so na clinica A. Visto de dentro da clinica B, ela e um
# id de usuario valido que nao pertence aquele inquilino — exatamente o que
# um POST forjado tentaria usar.
print(f'  alvo: {gestora.email} (sem vinculo na clinica B)')
print(f'  tem vinculo na B? {Membership.objects.filter(tenant=tenant_b, user=gestora).exists()}')
dono_b = Membership.objects.filter(
    tenant=tenant_b, status=MembershipStatus.ACTIVE,
).select_related('user').first()
try:
    services.open_direct(tenant_b.id, dono_b.user_id, gestora.id)
    failures.append('abriu conversa com usuario sem vinculo no inquilino')
    print('  open_direct atravessando      -> ACEITOU (falha)')
except services.ChatError as e:
    print(f'  open_direct atravessando      -> recusou: {e}')

cliente_b = entrar(dono_b.user, tenant_b)
r = cliente_b.post('/app/mensagens/abrir/', json.dumps({'user_id': str(gestora.id)}),
                   content_type='application/json')
print(f'  POST abrir pela rota          -> {r.status_code} (400 esperado)')
if r.status_code != 400:
    failures.append(f'a rota aceitou usuario de outro inquilino ({r.status_code})')

r = cliente_b.post('/app/mensagens/abrir/', json.dumps({'user_id': 'nao-e-uuid'}),
                   content_type='application/json')
print(f'  POST abrir com id invalido    -> {r.status_code} (400 esperado)')
if r.status_code != 400:
    failures.append(f'id malformado nao foi recusado com 400 ({r.status_code})')

# A conversa da clinica B nao pode ser aberta por quem esta na A.
# `order_by` explicito: sem ele o PostgreSQL pode devolver a MESMA linha em
# [0] e [1] (dois SELECT com LIMIT/OFFSET e sem ordem definida), e o roteiro
# falharia por um motivo que nao e o que ele investiga.
membros_b = list(
    Membership.objects.filter(tenant=tenant_b, status=MembershipStatus.ACTIVE)
    .order_by('created_at', 'id')[:2]
)
conversa_b = services.open_direct(
    tenant_b.id, membros_b[0].user_id, membros_b[1].user_id,
)
criadas.append(conversa_b)
r = entrar(medico).get(f'/app/mensagens/{conversa_b.id}/')
print(f'  GET conversa da clinica B (sessao na A) -> {r.status_code} (404 esperado)')
if r.status_code != 404:
    failures.append(f'conversa de outra clinica ficou legivel ({r.status_code})')

print('=== 4. o contador nao lido bate com a realidade ===')
services.mark_read(tenant_a.id, c1.id, medico.id)
services.mark_read(tenant_a.id, c1.id, secretaria.id)
for i in range(3):
    services.send(tenant_a.id, c1, medico.id, f'recado {i}')
membro_sec = services.membership_in(tenant_a.id, c1.id, secretaria.id)
membro_med = services.membership_in(tenant_a.id, c1.id, medico.id)
reais = Message.objects.filter(tenant=tenant_a, conversation=c1).count()
print(f'  mensagens gravadas            = {reais}')
print(f'  nao lido da secretaria        = {membro_sec.unread_count} (3 esperado)')
print(f'  nao lido de quem enviou       = {membro_med.unread_count} (0 esperado)')
if membro_sec.unread_count != 3:
    failures.append(f'contador do destinatario errado: {membro_sec.unread_count}')
if membro_med.unread_count != 0:
    failures.append('quem enviou incrementou o proprio nao lido')

total = services.unread_total(tenant_a.id, secretaria.id)
soma_real = sum(
    Message.objects.filter(
        tenant=tenant_a, conversation_id=m.conversation_id,
    ).exclude(sender_id=secretaria.id).filter(
        **({'created_at__gt': m.last_read_at} if m.last_read_at else {})
    ).count()
    for m in ConversationMember.objects.filter(tenant=tenant_a, user=secretaria)
)
print(f'  soma dos contadores           = {total}')
print(f'  contagem real de mensagens    = {soma_real}')
if total != soma_real:
    failures.append(f'o denormalizado divergiu do real ({total} != {soma_real})')

print('=== 5. marcar como lida zera, e a badge do cabecalho acompanha ===')
cliente_sec = entrar(secretaria)
r = cliente_sec.get('/app/mensagens/estado/')
dados = corpo(r)
print(f'  GET estado                    -> {r.status_code} total={dados.get("total")}')
if dados.get('total') != 3:
    failures.append(f'estado devolveu total errado: {dados.get("total")}')
nomes = [p['nome'] for p in dados.get('pessoas', [])]
print(f'  pessoas oferecidas            = {nomes}')
if any(p['user_id'] == str(secretaria.id) for p in dados.get('pessoas', [])):
    failures.append('a propria pessoa apareceu na lista de colegas')

r = cliente_sec.post(f'/app/mensagens/lida/{c1.id}/', '{}', content_type='application/json')
print(f'  POST marcar lida              -> {r.status_code} total={corpo(r).get("total")}')
if corpo(r).get('total') != 0:
    failures.append('marcar como lida nao zerou o contador')

pagina = cliente_sec.get('/app/reporting/')
if pagina.status_code == 200:
    marcado = b'id="nd-tc-badge"' in pagina.content
    print(f'  botao no cabecalho da pagina  -> presente={marcado}')
    if not marcado:
        failures.append('o botao de mensagens nao foi renderizado no cabecalho')

print('=== 6. corpo vazio e corpo gigante ===')
cliente_med = entrar(medico)
for rotulo, texto in [('vazio', '   '), ('gigante', 'x' * 5000)]:
    r = cliente_med.post(f'/app/mensagens/{c1.id}/enviar/', json.dumps({'texto': texto}),
                         content_type='application/json')
    print(f'  enviar {rotulo:8}              -> {r.status_code} {corpo(r).get("erro", "")}')
    if r.status_code != 400:
        failures.append(f'mensagem {rotulo} foi aceita ({r.status_code})')

print('=== 7. o texto volta como texto, e nunca como marcacao ===')
# O que protege aqui NAO e escapar `<` no corpo do JSON. Um `<script>` dentro
# de uma resposta `application/json` nao executa: o navegador nao analisa JSON
# como HTML, e `X-Content-Type-Options: nosniff` impede que ele tente adivinhar
# outro tipo. Escapar o conteudo alem disso mutilaria a mensagem de quem
# legitimamente escreveu `<` — e a mensagem tem de voltar EXATAMENTE como foi
# digitada.
#
# As tres camadas que de fato respondem, e que este trecho confere:
#   1. o corpo atravessa intacto;
#   2. a resposta e servida como JSON, com nosniff;
#   3. o cliente insere tudo por `textContent` — nenhum `innerHTML` no arquivo.
veneno = '<script>alert("xss")</script> & <b>bold</b>'
services.send(tenant_a.id, c1, medico.id, veneno)
r = cliente_sec.get(f'/app/mensagens/{c1.id}/')
ultima = corpo(r)['mensagens'][-1]
print(f'  gravado  = {ultima["texto"]!r}')
print(f'  intacto  = {ultima["texto"] == veneno}')
if ultima['texto'] != veneno:
    failures.append('o corpo da mensagem foi alterado no caminho')

tipo = r.headers.get('Content-Type', '')
nosniff = r.headers.get('X-Content-Type-Options', '')
print(f'  Content-Type            = {tipo}')
print(f'  X-Content-Type-Options  = {nosniff}')
if 'application/json' not in tipo:
    failures.append(f'a resposta nao e servida como JSON ({tipo})')
if nosniff.lower() != 'nosniff':
    failures.append('sem X-Content-Type-Options: nosniff — o navegador poderia adivinhar HTML')

cliente_js = (BASE_DIR / 'static' / 'teamchat' / 'teamchat.js').read_text(encoding='utf-8')
# Comentarios fora antes de procurar. A busca crua por "innerHTML" acusava o
# proprio cabecalho do arquivo, que diz em prosa que innerHTML nao e usado —
# um roteiro que falha por causa da documentacao da regra que ele verifica e
# um roteiro que sera desligado na primeira vez que atrapalhar.
codigo = re.sub(r'/\*.*?\*/', '', cliente_js, flags=re.S)
codigo = re.sub(r'(?m)^\s*//.*$', '', codigo)
perigosos = [nome for nome in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write')
             if nome in codigo]
print(f'  escrita de HTML no cliente = {perigosos or "nenhuma"} (nenhuma esperada)')
if perigosos:
    failures.append(
        f'o cliente escreve HTML ({", ".join(perigosos)}) — conteudo de colega '
        f'nunca pode virar marcacao'
    )

print('=== 8. clinica suspensa: congela o envio, nao a leitura ===')
tenant_a.status = TenantStatus.SUSPENDED
tenant_a.status_note = 'check_mensagens'
tenant_a.save(update_fields=['status', 'status_note'])
cliente_med = entrar(medico)
r = cliente_med.get(f'/app/mensagens/{c1.id}/')
print(f'  GET conversa                  -> {r.status_code} (200 esperado)')
if r.status_code != 200:
    failures.append(f'clinica suspensa bloqueou a leitura da conversa ({r.status_code})')
r = cliente_med.post(f'/app/mensagens/{c1.id}/enviar/', json.dumps({'texto': 'durante a suspensao'}),
                     content_type='application/json')
print(f'  POST enviar                   -> {r.status_code} (403 esperado)')
if r.status_code != 403:
    failures.append(f'clinica suspensa aceitou o envio de mensagem ({r.status_code})')
r = cliente_med.post(f'/app/mensagens/lida/{c1.id}/', '{}', content_type='application/json')
print(f'  POST marcar lida              -> {r.status_code} (200 esperado)')
if r.status_code != 200:
    failures.append(f'clinica suspensa bloqueou marcar como lida ({r.status_code}) — a badge ficaria travada')
tenant_a.status = status_original
tenant_a.status_note = ''
tenant_a.save(update_fields=['status', 'status_note'])
print(f'--- estado da clinica A restaurado: {tenant_a.status}')

print('=== 9. vinculo revogado some da lista e recusa conversa ===')
vinculo = Membership.objects.get(tenant=tenant_a, user=medico2)
antes = vinculo.status
vinculo.status = MembershipStatus.REVOKED
vinculo.save(update_fields=['status'])
estado = services.state_for(tenant_a.id, medico.id)
presente = any(p['user_id'] == str(medico2.id) for p in estado['pessoas'])
print(f'  revogado aparece na lista     -> {presente} (False esperado)')
if presente:
    failures.append('vinculo revogado continuou oferecido como destinatario')
try:
    services.open_direct(tenant_a.id, gestora.id, medico2.id)
    failures.append('abriu conversa com vinculo revogado')
    print('  open_direct com revogado      -> ACEITOU (falha)')
except services.ChatError as e:
    print(f'  open_direct com revogado      -> recusou: {e}')
vinculo.status = antes
vinculo.save(update_fields=['status'])
print(f'--- vinculo de {medico2.email} restaurado: {vinculo.status}')

print('=== 10. conexao nova nao reentrega o historico do Redis ===')
# Defeito real encontrado testando com `curl` atraves do Traefik: uma conexao
# sem `Last-Event-ID` comecava do inicio do stream e reentregava tudo o que o
# Redis ainda guardava (ate uma hora). Na janela isso inflava o contador de
# nao lidas das conversas fechadas ate a sondagem seguinte desfazer.
streaming.publish(tenant_a.id, secretaria.id, 'mensagem', {'id': 'antiga-1'})
streaming.publish(tenant_a.id, secretaria.id, 'mensagem', {'id': 'antiga-2'})
fim = streaming.tail_id(tenant_a.id, secretaria.id)
atrasadas = streaming.read_after(tenant_a.id, secretaria.id, fim)
print(f'  fim da caixa                  = {fim}')
print(f'  conexao nova recebe           = {len(atrasadas)} evento(s) (0 esperado)')
if atrasadas:
    failures.append(f'conexao nova reentregou {len(atrasadas)} evento(s) antigo(s)')

streaming.publish(tenant_a.id, secretaria.id, 'mensagem', {'id': 'nova-3'})
novas = streaming.read_after(tenant_a.id, secretaria.id, fim)
print(f'  depois de uma mensagem nova   = {len(novas)} evento(s) (1 esperado)')
if len(novas) != 1:
    failures.append(f'o que chegou depois do fim nao foi entregue ({len(novas)} evento(s))')

# Reconexao continua retomando de onde parou: com o id anterior ao fim, os
# dois eventos antigos voltam a ser visiveis.
todos = streaming.read_after(tenant_a.id, secretaria.id, '0')
print(f'  reconexao a partir do zero    = {len(todos)} evento(s) (>=3 esperado)')
if len(todos) < 3:
    failures.append('a retomada por Last-Event-ID deixou de enxergar o historico')
streaming._client().delete(streaming.inbox_key(tenant_a.id, secretaria.id))
print('  caixa de teste removida do Redis')

print('=== 11. o cookie de CSRF esta la para o cliente ler ===')
# Defeito real relatado em uso: uma aba aberta antes de alguem entrar com
# outra conta no mesmo navegador ficava com o token de CSRF anterior (o
# Django troca o token a cada login) e o envio voltava 403. O cliente passou
# a ler o token do COOKIE na hora do envio, e nao do campo escondido gravado
# quando a pagina foi montada. Isto confere que o cookie existe e que o campo
# continua la como reserva.
pagina = entrar(medico).get('/app/reporting/')
cookie_csrf = pagina.cookies.get('csrftoken') or pagina.client.cookies.get('csrftoken')
print(f'  cookie csrftoken presente     -> {bool(cookie_csrf)}')
if not cookie_csrf:
    failures.append('sem cookie csrftoken — o cliente nao teria de onde ler o token atual')
if b'name="csrfmiddlewaretoken"' not in pagina.content:
    failures.append('sem campo csrfmiddlewaretoken na janela — a reserva do cliente sumiu')
print(f'  campo csrfmiddlewaretoken     -> {b"csrfmiddlewaretoken" in pagina.content}')

cliente_js = (BASE_DIR / 'static' / 'teamchat' / 'teamchat.js').read_text(encoding='utf-8')
le_cookie = 'document.cookie' in cliente_js and 'csrftoken' in cliente_js
print(f'  cliente le o token do cookie  -> {le_cookie}')
if not le_cookie:
    failures.append('o cliente voltou a depender so do campo escondido, que envelhece')

print('=== 12. o aviso do cabecalho: badge no servidor e no cliente ===')
# O pedido era: quem NAO esta com a janela aberta precisa ver quantas
# mensagens chegaram, num circulo vermelho no botao. Duas metades:
#   servidor  -> a badge ja sai renderizada com o numero certo;
#   cliente   -> o SSE acende na hora, sem esperar a sondagem.
# A segunda metade e JavaScript e nao roda aqui; o que da para travar e que
# as pecas de que ela depende continuam existindo.
conv_badge = services.open_direct(tenant_a.id, medico.id, secretaria.id)
# E a MESMA conversa da secao 1 (mesmo par), como tem de ser — registrar de
# novo so faria a limpeza imprimir a mesma linha duas vezes.
if conv_badge.id not in [c.id for c in criadas]:
    criadas.append(conv_badge)
services.mark_read(tenant_a.id, conv_badge.id, secretaria.id)

cliente_sec = entrar(secretaria)
# `/app/patients/` e nao `/app/reporting/`: o painel gerencial exige
# MANAGERIAL_DASHBOARD, que a secretaria nao tem — pedir a ele devolveria um
# 302 sem cabecalho, e o roteiro concluiria que a badge sumiu.
antes = cliente_sec.get('/app/patients/').content
print(f'  badge escondida sem mensagem  -> {b"nd-tc-badge" in antes and b"hidden>0<" in antes}')
if b'hidden>0<' not in antes:
    failures.append('a badge nao nasce escondida e zerada')

for i in range(3):
    services.send(tenant_a.id, conv_badge, medico.id, f'aviso {i}')
depois = cliente_sec.get('/app/patients/').content
print(f'  badge com 3 nao lidas         -> {b">3</span>" in depois}')
if b'>3</span>' not in depois:
    failures.append('a badge do cabecalho nao trouxe a contagem depois das mensagens')

js = (BASE_DIR / 'static' / 'teamchat' / 'teamchat.js').read_text(encoding='utf-8')
pecas = {
    'stream sobe com a pagina': 'disputarLideranca()' in js,
    'uma conexao por navegador': 'BroadcastChannel' in js and 'CHAVE_LIDER' in js,
    'soma antes de saber de quem e': 'totalNaoLidas + 1' in js,
    'titulo da aba avisa': "'(' + total + ') '" in js,
    'pulso na badge': 'is-nova' in js,
}
for nome, ok in pecas.items():
    print(f'  {nome:30} -> {ok}')
    if not ok:
        failures.append(f'o aviso do cabecalho perdeu uma peca: {nome}')
if 'is-nova' not in (BASE_DIR / 'static' / 'teamchat' / 'teamchat.css').read_text(encoding='utf-8'):
    failures.append('sem a animacao .is-nova no CSS, o pulso da badge nao existe')

print('=== 13. a tela sabe de quem e a sessao ===')
# Duas abas do mesmo perfil dividem UM cookie: entrar com outra conta na
# segunda troca a sessao da primeira. A aba antiga continuava mostrando o
# nome de quem entrou nela e falando pelo servidor como a conta nova — a
# lista de colegas ficava errada em silencio (reproduzido no navegador: a
# aba do medico passou a listar o proprio medico, e a secretaria sumia).
# O estado agora diz de quem e a sessao, e o cliente compara com o id que a
# pagina trouxe.
estado_med = services.state_for(tenant_a.id, medico.id)
estado_sec = services.state_for(tenant_a.id, secretaria.id)
print(f'  estado do medico diz eu=     {estado_med["eu"] == str(medico.id)}')
print(f'  estado da secretaria diz eu= {estado_sec["eu"] == str(secretaria.id)}')
if estado_med['eu'] != str(medico.id) or estado_sec['eu'] != str(secretaria.id):
    failures.append('o estado nao identifica de quem e a sessao')
nomes_med = [p['nome'] for p in estado_med['pessoas']]
print(f'  o medico NAO se ve na lista   -> {"Ana Neuro" not in nomes_med}')
if any(p['user_id'] == str(medico.id) for p in estado_med['pessoas']):
    failures.append('a pessoa aparece na propria lista de colegas')

js = (BASE_DIR / 'static' / 'teamchat' / 'teamchat.js').read_text(encoding='utf-8')
if 'dados.eu !== eu' not in js:
    failures.append('o cliente parou de conferir se a sessao mudou de dono')
print(f'  cliente compara sessao        -> {"dados.eu !== eu" in js}')

print('=== 14. trocar de pessoa nao deixa a conversa anterior armada ===')
# O defeito que a revisao achou: se abrir a conversa falhasse, `conversaAtual`
# continuava apontando para a conversa ANTERIOR enquanto o cabecalho ja
# mostrava o novo nome — escrever ali mandaria a mensagem para a pessoa
# errada. Num sistema em que se escreve "a paciente das 15h piorou", isso
# nao e um incomodo de interface.
tem_zeragem = "conversaAtual = '';" in js
tem_token = 'meuPedido !== pedidoAtual' in js
tem_guarda = 'A conversa não abriu' in js
tem_bfcache = "evento.persisted" in js
for nome, ok in [
    ('zera a conversa ao trocar de pessoa', tem_zeragem),
    ('descarta resposta atrasada', tem_token),
    ('recusa enviar sem conversa aberta', tem_guarda),
    ('religa a aba restaurada do bfcache', tem_bfcache),
]:
    print(f'  {nome:38} -> {ok}')
    if not ok:
        failures.append(f'protecao perdida no cliente: {nome}')

print('=== limpeza ===')
for conversa in criadas:
    apagadas = Message.objects.filter(conversation=conversa).delete()[0]
    ConversationMember.objects.filter(conversation=conversa).delete()
    Conversation.objects.filter(id=conversa.id).delete()
    print(f'  {conversa.id} -> {apagadas} mensagem(ns) removida(s)')

if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: conversa unica por par, isolada por participacao e por inquilino, contador fiel,')
print('    envio congelado na clinica suspensa e corpo devolvido como texto.')
