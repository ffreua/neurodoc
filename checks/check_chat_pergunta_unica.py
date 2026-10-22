"""A pergunta do chat vai ao provedor uma vez só (auditoria da 1.24, A1).

A view grava a pergunta **completa** antes de enfileirar a tarefa
(`chat_services.post_user_message`), e `build_history` lia as completas.
Resultado: o provedor recebia `[..., pergunta, pergunta]`, a pergunta gastava
uma vaga da janela de histórico, e na conversa sem paciente a "pergunta
anterior" da busca no manual era a própria pergunta atual — o seguimento
("e para desfazer?") deixava de achar o trecho pela pergunta de antes.

`check_chatbot` e `check_chat_manual` não pegavam: chamam `build_chat_prompt`
com uma pergunta que **não foi gravada**, e em produção ela sempre é. Este
roteiro segue o caminho real: grava como a view grava e monta como a
tarefa monta.

    docker compose exec -T app python manage.py shell < checks/check_chat_pergunta_unica.py
"""
from unittest import mock

from langchain_core.messages import HumanMessage

from accounts.models import User
from ai.chat_models import ChatMessageState, ChatSession
from ai.chat_prompt import build_chat_prompt
from ai.chat_services import post_user_message, start_assistant_message
from tenancy.models import Membership

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(nome)


user = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.filter(user=user, status='active').order_by('created_at').first()
sessoes = []


def nova_sessao(**extra):
    s = ChatSession.objects.create(
        tenant_id=vinculo.tenant_id, owner_user=user, title='roteiro pergunta única', **extra,
    )
    sessoes.append(s)
    return s


def turno(sessao, pergunta, resposta=None):
    p = post_user_message(sessao, pergunta)
    a = start_assistant_message(sessao)
    if resposta is not None:
        a.content = resposta
        a.state = ChatMessageState.COMPLETE
        a.save(update_fields=['content', 'state'])
    return p


def humanas(msgs):
    return [m.content for m in msgs if isinstance(m, HumanMessage)]


try:
    print('=== 1. Sem paciente: a pergunta atual vai uma vez ===')
    s = nova_sessao()
    turno(s, 'Como bloqueio um horário na agenda?', 'Pelo modal do horário.')
    p2 = turno(s, 'E para desfazer?')
    msgs, _ = build_chat_prompt(s, p2.content, pergunta_id=p2.id)
    h = humanas(msgs)
    conferir('a pergunta atual aparece uma vez', h.count('E para desfazer?') == 1, h)
    conferir('a pergunta atual é a última humana', h[-1] == 'E para desfazer?', h)
    conferir('a pergunta anterior continua no histórico', 'Como bloqueio um horário na agenda?' in h, h)

    print('=== 2. A busca no manual usa a pergunta de antes ===')
    capturado = {}
    import ai.conhecimento as conhecimento

    original = conhecimento.buscar

    def espiao(texto, *a, **k):
        capturado['texto'] = texto
        return original(texto, *a, **k)

    with mock.patch.object(conhecimento, 'buscar', espiao):
        build_chat_prompt(s, p2.content, pergunta_id=p2.id)
    texto = capturado.get('texto', '')
    conferir('a busca recebe a pergunta anterior', 'bloqueio' in texto, texto)
    conferir('a busca não repete a pergunta atual', texto.count('E para desfazer?') == 1, texto)

    print('=== 3. Com paciente: a pergunta atual vai uma vez ===')
    from patients.models import Patient

    paciente = Patient.objects.filter(tenant_id=vinculo.tenant_id).order_by('created_at').first()
    sp = nova_sessao(patient=paciente)
    turno(sp, 'Resuma o caso.', 'Resumo.')
    q = turno(sp, 'E o exame neurológico?')
    msgs, _ = build_chat_prompt(sp, q.content, pergunta_id=q.id)
    h = humanas(msgs)
    conferir('com paciente: uma vez', h.count('E o exame neurológico?') == 1, h)

    print('=== 4. O caminho da tarefa passa o id ===')
    from ai import tasks

    with mock.patch.object(tasks, '_build_chat_messages', wraps=tasks._build_chat_messages) as w:
        with mock.patch.object(tasks, '_avaliar_privacidade', side_effect=RuntimeError('parar aqui')):
            assistente = start_assistant_message(s)
            try:
                tasks.run_chat_turn(str(assistente.id), str(p2.id))
            except RuntimeError:
                pass
    chamada = w.call_args
    conferir('run_chat_turn passa a pergunta_id', chamada is not None
             and str(chamada.kwargs.get('pergunta_id')) == str(p2.id), chamada)

    print('=== 5. Sem pergunta_id o comportamento antigo segue (compatível) ===')
    msgs, _ = build_chat_prompt(s, 'Pergunta não gravada?')
    conferir('pergunta não gravada aparece uma vez', humanas(msgs).count('Pergunta não gravada?') == 1)
finally:
    for s in sessoes:
        s.messages.all().delete()
        s.delete()

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: a pergunta do chat vai ao provedor uma vez só.')
