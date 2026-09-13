"""O chat de apoio manda ao provedor o que deveria, e so isso?

Ate a versao anterior mandava **apenas a mensagem digitada**: sem
instrucao de sistema, sem historico, sem um dado do prontuario e sem
desidentificacao. Este roteiro existe para que isso nao volte.

As perguntas sao:

- a instrucao de sistema vai junto, com as quatro regras?
- o prontuario do paciente da sessao vai junto, e so o dele?
- o historico da conversa chega ao modelo?
- o nome e o CPF do paciente saem da instalacao?
- sessao sem paciente alcanca prontuario?
- paciente de outra clinica entra numa sessao?
- vinculo revogado entre enfileirar e executar ainda manda prontuario?

Nada aqui chama provedor de verdade: o que se verifica e o que **sai**.
"""
from types import SimpleNamespace

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from ai.chat_models import ChatMessageRole, ChatMessageState, ChatSession
from ai.chat_prompt import CHAT_SYSTEM_PROMPT, build_chat_prompt, build_patient_context
from ai.context import AIAuthorizationDenied, build_ai_authorization
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.get(user=medico, tenant=tenant_a)
paciente = Patient.objects.get(tenant=tenant_a, full_name='Carlos Adulto da Silva')
paciente_b = Patient.objects.filter(tenant=tenant_b).first()

criadas = []


def nova_sessao(patient=None, titulo='check'):
    s = ChatSession.objects.create(
        tenant=tenant_a, owner_user=medico, patient=patient, title=titulo,
    )
    criadas.append(s.id)
    return s


def autorizacao(patient_id):
    ctx = SimpleNamespace(tenant_id=tenant_a.id, user_id=medico.id, membership_id=vinculo.id)
    return build_ai_authorization(ctx, patient_id=patient_id)


print('=== 1. a instrucao de sistema vai junto, com as quatro regras ===')
sessao = nova_sessao(paciente)
msgs, contexto = build_chat_prompt(sessao, 'Resuma o caso.', authorization=autorizacao(paciente.id))
sistema = msgs[0].content
regras = {
    'FONTES': 'FONTES' in sistema,
    'dado ausente se diz': 'Nao encontrei isso no prontuario' in sistema.replace('ã', 'a').replace('á', 'a').replace('ú', 'u').replace('é', 'e'),
    'numero nao inventado': 'NUMERO NENHUM' in sistema.replace('Ú', 'U'),
    'decisao do medico': 'A DECISAO E DO MEDICO' in sistema.replace('Ã', 'A').replace('É', 'E').replace('É', 'E'),
}
for rotulo, presente in regras.items():
    print(f'  {rotulo:24} presente={presente}')
    if not presente:
        falhas.append(f'a instrucao de sistema perdeu a regra: {rotulo}')
if not sistema.startswith(CHAT_SYSTEM_PROMPT[:60]):
    falhas.append('a primeira mensagem nao e a instrucao de sistema')

print('=== 2. o prontuario do paciente da sessao vai junto ===')
tem_bloco = 'DADOS DO PRONTUARIO' in sistema.replace('Á', 'A')
print(f'  bloco de prontuario presente={tem_bloco}  tamanho={len(contexto)} caracteres')
print(f'  atendimentos no bloco={contexto.count("Conduta:")}')
if not tem_bloco or not contexto:
    falhas.append('o prontuario do paciente nao foi enviado ao modelo')

print('=== 3. nome e CPF nao saem da instalacao ===')
tudo = '\n'.join(m.content for m in msgs)
vazou = [t for t in ['Carlos', 'Adulto', 'Silva', paciente.cpf or 'sem-cpf'] if t in tudo]
print(f'  termos identificaveis no que sai: {vazou or "nenhum"}')
print(f'  marcadores [PACIENTE]: {tudo.count("[PACIENTE]")}')
if vazou:
    falhas.append(f'o texto enviado ao provedor carrega {vazou}')

print('=== 4. o historico da conversa chega ao modelo ===')
from ai import chat_services

chat_services.post_user_message(sessao, 'Primeira pergunta sobre o caso.')
resposta = chat_services.start_assistant_message(sessao)
chat_services.finalize_assistant_message(resposta, 'Primeira resposta da IA.')
msgs2, _ = build_chat_prompt(sessao, 'E no segundo caso?', authorization=autorizacao(paciente.id))
tudo2 = '\n'.join(m.content for m in msgs2)
print(f'  mensagens enviadas: {len(msgs2)} (era {len(msgs)})')
print(f'  pergunta anterior presente={"Primeira pergunta" in tudo2}')
print(f'  resposta anterior presente={"Primeira resposta" in tudo2}')
if 'Primeira pergunta' not in tudo2 or 'Primeira resposta' not in tudo2:
    falhas.append('o historico da conversa nao chega ao modelo: cada volta iria sozinha')

print('=== 5. mensagem incompleta nao entra no historico ===')
pendente = chat_services.start_assistant_message(sessao)
pendente.content = 'TEXTO PELA METADE'
pendente.save(update_fields=['content'])
msgs3, _ = build_chat_prompt(sessao, 'Outra pergunta.', authorization=autorizacao(paciente.id))
entrou = 'TEXTO PELA METADE' in '\n'.join(m.content for m in msgs3)
print(f'  resposta em andamento entrou no historico={entrou} (False esperado)')
if entrou:
    falhas.append('resposta pela metade entrou no historico como se fosse resposta dada')
pendente.state = ChatMessageState.FAILED
pendente.save(update_fields=['state'])

print('=== 6. sessao sem paciente nao alcanca prontuario ===')
sem_paciente = nova_sessao(None, 'sem paciente')
msgs4, contexto4 = build_chat_prompt(sem_paciente, 'Qual o historico do Carlos?', authorization=None)
sistema4 = msgs4[0].content
print(f'  bloco de prontuario={bool(contexto4)} (vazio esperado)')
print(f'  o prompt avisa que nao ha paciente={"nao esta ligada a nenhum paciente" in sistema4.replace("ã","a").replace("á","a")}')
if contexto4:
    falhas.append('sessao sem paciente recebeu dados de prontuario')

print('=== 7. as ferramentas recusam fora de escopo ===')
from ai.tools import clinical

sem_escopo = SimpleNamespace(tenant_id=tenant_a.id, patient_id=None,
                             user_id=medico.id, membership_id=vinculo.id, encounter_id=None)
try:
    clinical.get_patient_timeline(sem_escopo)
    print('  autorizacao sem paciente listou atendimentos (nao deveria)')
    falhas.append('a ferramenta clinica devolveu dados sem paciente em escopo')
except clinical.ToolScopeError as exc:
    print(f'  sem paciente em escopo -> recusado: {exc}')

print('=== 8. paciente de outra clinica nao entra ===')
try:
    autorizacao(paciente_b.id)
    print('  paciente da clinica B autorizado (nao deveria)')
    falhas.append('paciente de outro inquilino foi autorizado no chat')
except AIAuthorizationDenied as exc:
    print(f'  paciente da clinica B -> recusado: {exc}')

print('=== 9. vinculo revogado corta o prontuario ===')
# Entre enfileirar e executar cabe uma revogacao: a tarefa reconstroi a
# autorizacao do banco, e e a ultima chance de recusar.
from ai.tasks import _build_chat_messages

vinculo.status = MembershipStatus.SUSPENDED
vinculo.save(update_fields=['status'])
try:
    _build_chat_messages(sessao, 'Resuma o caso.')
    print('  vinculo suspenso ainda montou o prompt (nao deveria)')
    falhas.append('vinculo suspenso entre enfileirar e executar ainda recebeu prontuario')
except AIAuthorizationDenied as exc:
    print(f'  vinculo suspenso -> recusado: {str(exc)[:60]}')
finally:
    vinculo.status = MembershipStatus.ACTIVE
    vinculo.save(update_fields=['status'])

print('=== 10. a tela: layout, aviso e composer ===')
c = Client()
c.force_login(medico)
s = c.session
s['tenant_id'] = str(tenant_a.id)
s.save()
corpo = c.get(f'/app/ai/chat/{sessao.id}/').content.decode()
itens = {
    'duas colunas': 'nd-chat-aside' in corpo and 'nd-chat-main' in corpo,
    'composer fixo': 'nd-chat-composer' in corpo,
    'aviso de revisao': 'Revise antes de usar' in corpo,
    'busca de paciente': 'nd-chat-paciente' in corpo,
}
for rotulo, ok in itens.items():
    print(f'  {rotulo:20} {ok}')
    if not ok:
        falhas.append(f'a tela do chat perdeu: {rotulo}')

print('=== 11. apagar: so o dono, e a trilha guarda o fato sem o texto ===')
from audit.models import AuditEvent

descartavel = nova_sessao(paciente, 'conversa a apagar')
chat_services.post_user_message(descartavel, 'SEGREDO DA CONVERSA')
resp = chat_services.start_assistant_message(descartavel)
chat_services.finalize_assistant_message(resp, 'RESPOSTA SECRETA')

outro = User.objects.get(email='doctor-b@demo.neurodoc.local')
alheio = Client()
alheio.force_login(outro)
sa = alheio.session
sa['tenant_id'] = str(tenant_a.id)
sa.save()
r = alheio.post(f'/app/ai/chat/{descartavel.id}/apagar/')
sobreviveu = ChatSession.objects.filter(id=descartavel.id).exists()
print(f'  conversa alheia -> {r.status_code}  sobreviveu={sobreviveu}')
if r.status_code != 404 or not sobreviveu:
    falhas.append('um medico apagou a conversa de outro')

r = c.post(f'/app/ai/chat/{descartavel.id}/apagar/', follow=True)
sumiu = not ChatSession.objects.filter(id=descartavel.id).exists()
sem_mensagens = ChatMessage.objects.filter(session_id=descartavel.id).count() == 0
print(f'  o dono apaga -> {r.status_code}  sumiu={sumiu}  mensagens={0 if sem_mensagens else "sobraram"}')
if not sumiu or not sem_mensagens:
    falhas.append('apagar a conversa deixou a sessao ou as mensagens para tras')

evento = AuditEvent.objects.filter(action='ai.chat_session_deleted').order_by('-created_at').first()
meta = str(evento.integrity_metadata if evento else '')
vazou = 'SEGREDO' in meta or 'SECRETA' in meta
print(f'  trilha registrou={evento is not None}  texto vazou para a trilha={vazou}')
if evento is None:
    falhas.append('apagar a conversa nao gerou evento de auditoria')
if vazou:
    falhas.append('a trilha guardou o texto da conversa apagada')

# O prontuario nao e afetado: conversa de apoio nao e registro clinico.
if not Patient.objects.filter(id=paciente.id).exists():
    falhas.append('apagar a conversa afetou o paciente')
print(f'  paciente intacto={Patient.objects.filter(id=paciente.id).exists()}')

# limpeza
from ai.chat_models import ChatMessage

ChatMessage.objects.filter(session_id__in=criadas).delete()
ChatSession.objects.filter(id__in=criadas).delete()

print('---')
if falhas:
    for line in falhas:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o chat manda instrucao, prontuario do paciente certo e historico -- sem identificar ninguem.')
