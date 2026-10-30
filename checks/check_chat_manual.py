"""O chat de apoio sem paciente responde pelo manual do sistema.

Desde a 1.18, a conversa que não está ligada a paciente também tira dúvida
de uso do NeuroDoc, a partir de trechos do manual (`base/help_content.py`)
e da documentação técnica (`docs/homologation/`, `docs/governance/`)
escolhidos para cada pergunta (`ai/conhecimento.py`).

As perguntas que o roteiro faz, e por que cada uma:

- **a busca acha o trecho certo?** Pergunta de uso, com as palavras de quem
  usa a tela, precisa trazer o artigo do manual que responde — senão o
  modelo descreve a tela de memória;
- **o trecho chega ao prompt, com a fonte?** Sem a fonte, o modelo não tem
  o que citar;
- **pergunta de seguimento ("e para desfazer?") também acha?** Ela sozinha
  não tem palavra nenhuma do assunto; a busca leva junto a pergunta
  anterior;
- **conversa com paciente fica de fora?** Ali a janela é do prontuário, e a
  documentação disputaria espaço com os dados dele;
- **pergunta que não é do sistema cai na instrução certa?** Sem trecho, o
  prompt manda dizer que não encontrou no manual, em vez de inventar;
- **o corpus não traz o que não deve?** Nem plano de trabalho nem histórico
  de publicação, que descrevem como o sistema *foi* feito.

Não chama provedor nenhum: o roteiro confere o que **seria enviado**.
"""
import uuid

from ai.chat_models import ChatMessage, ChatMessageRole, ChatMessageState, ChatSession
from ai.chat_prompt import COM_MANUAL, SEM_MANUAL, build_chat_prompt
from ai.conhecimento import buscar, indice
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        falhas.append(descricao)


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).select_related('user').first()
paciente = Patient.objects.filter(tenant=tenant).first()
sessoes = []


def nova_sessao(com_paciente):
    sessao = ChatSession.objects.create(
        tenant=tenant, owner_user=medico.user,
        patient=paciente if com_paciente else None, title='roteiro do manual',
    )
    sessoes.append(sessao)
    return sessao


print('=== 1. o índice existe e traz o manual e a documentação ===')
documentos, _, _ = indice()
fontes = {t['fonte'] for t, _, _ in documentos}
confere(len(documentos) > 100, 'o índice tem trechos suficientes', len(documentos))
confere(any(f.startswith('/ajuda/') for f in fontes), 'o manual (/ajuda/) está no índice')
confere(any(f.startswith('docs/homologation/') for f in fontes), 'a documentação técnica está no índice')
confere(not any('releases' in f or 'superpowers' in f for f in fontes),
        'plano de trabalho e histórico de publicação ficam de fora')
confere(not any('/comunicado-' in f for f in fontes),
        'comunicado às clínicas fica de fora (diz o que valia no dia, não o que vale hoje)')
confere(any(f.endswith('/ajuda/receita-sncr/') for f in fontes),
        'o artigo da receita eletrônica do SNCR está no índice')

print('=== 2. a busca acha o trecho certo para pergunta de uso ===')
casos = [
    ('Como bloqueio um horário na agenda?', ('agenda', 'bloque')),
    ('Onde fica o laudo que o paciente enviou pelo portal?', ('portal', 'exame')),
    ('Como altero a dose de uma medicação no atendimento?', ('medica',)),
    ('Como exporto os dados da clínica?', ('export',)),
]
for pergunta, esperadas in casos:
    trechos = buscar(pergunta)
    primeiro = trechos[0] if trechos else None
    texto = (f'{primeiro["titulo"]} {primeiro["texto"]}' if primeiro else '').lower()
    confere(primeiro is not None and all(e in texto for e in esperadas),
            f'"{pergunta}" traz um trecho que fala de {", ".join(esperadas)}',
            primeiro['titulo'] if primeiro else 'nenhum trecho')

print('=== 3. o trecho chega ao prompt, com a fonte ===')
sessao = nova_sessao(com_paciente=False)
mensagens, contexto = build_chat_prompt(sessao, 'Como bloqueio um horário na agenda?')
sistema = mensagens[0].content
confere(COM_MANUAL.split('\n', 1)[0] in sistema, 'o prompt traz a seção do manual')
confere('(fonte: /ajuda/' in sistema, 'o trecho vem com a página do manual como fonte')
confere('nao esta ligada a nenhum paciente' in sistema.replace('ã', 'a').replace('á', 'a'),
        'o prompt continua dizendo que a conversa não tem paciente')
confere(not contexto, 'o retorno "contexto" segue sendo só prontuário (vazio sem paciente)')

print('=== 4. a pergunta de seguimento acha pela anterior ===')
ChatMessage.objects.create(
    tenant=tenant, session=sessao, sequence=1, role=ChatMessageRole.USER,
    state=ChatMessageState.COMPLETE, content='Como bloqueio um horário na agenda?',
)
ChatMessage.objects.create(
    tenant=tenant, session=sessao, sequence=2, role=ChatMessageRole.ASSISTANT,
    state=ChatMessageState.COMPLETE, content='No modal do horário livre, Bloquear este horário.',
)
mensagens, _ = build_chat_prompt(sessao, 'E para desfazer?')
confere('(fonte: /ajuda/' in mensagens[0].content,
        '"E para desfazer?" depois da pergunta da agenda ainda traz o manual')
confere(len(mensagens) == 4, 'o histórico continua indo junto', len(mensagens))

print('=== 5. conversa com paciente não recebe o manual ===')
if paciente is not None:
    com = nova_sessao(com_paciente=True)
    mensagens, _ = build_chat_prompt(com, 'Como bloqueio um horário na agenda?')
    sistema = mensagens[0].content
    confere(COM_MANUAL.split('\n', 1)[0] not in sistema and '(fonte: /ajuda/' not in sistema,
            'a sessão ligada a paciente fica só com o prontuário')

print('=== 6. pergunta sem trecho cai na instrução de não inventar ===')
sem = nova_sessao(com_paciente=False)
mensagens, _ = build_chat_prompt(sem, f'xyzzy {uuid.uuid4().hex} quux?')
confere(SEM_MANUAL in mensagens[0].content, 'sem trecho, o prompt manda dizer que não encontrou')

ChatMessage.objects.filter(session__in=sessoes).delete()
ChatSession.objects.filter(id__in=[s.id for s in sessoes]).delete()

print('---')
if falhas:
    for falha in falhas:
        print('FALHA:', falha)
    raise SystemExit(1)
print('OK: o chat sem paciente responde pelo manual, e o com paciente fica com o prontuário.')
