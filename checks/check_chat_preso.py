"""A resposta do chat não fica "transmitindo" para sempre (auditoria de 2026-11-11).

A mensagem do assistente nasce "transmitindo" antes de entrar na fila, e só
a tarefa a tira dali. Fila atrasada, worker reiniciado ou Redis fora
deixavam a mensagem presa, e três presas bloqueavam o chat do médico pelo
limite de respostas simultâneas. E cancelar não interrompia nada: o worker
seguia chamando o provedor e gravava "concluída" por cima.

O roteiro confere: a varredura encerra a presa antiga e deixa a recente; a
presa antiga não conta no limite; a tarefa não chama o provedor para a
mensagem cancelada na fila; e o fim da tarefa não desfaz o cancelamento.

Tudo dentro de transação desfeita; nenhum provedor é chamado.

    docker compose exec -T app python manage.py shell < checks/check_chat_preso.py
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from ai import tasks
from ai.cancellation import MAX_CONCURRENT_STREAMS_PER_USER, ConcurrencyLimitExceeded, check_concurrency_limit
from ai.chat_models import ChatMessage, ChatMessageState, ChatSession
from ai.chat_services import finalize_assistant_message, post_user_message, start_assistant_message
from tenancy.models import Membership

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


user = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.filter(user=user, status='active').order_by('created_at').first()

try:
    with transaction.atomic():
        # Começa sem nenhuma resposta em andamento deste médico.
        ChatMessage.objects.filter(
            session__owner_user=user, state=ChatMessageState.STREAMING,
        ).update(state=ChatMessageState.FAILED)
        sessao = ChatSession.objects.create(tenant_id=vinculo.tenant_id, owner_user=user, title='roteiro chat preso')

        def resposta(minutos_atras=0):
            post_user_message(sessao, 'pergunta do roteiro')
            m = start_assistant_message(sessao)
            if minutos_atras:
                ChatMessage.objects.filter(id=m.id).update(
                    created_at=timezone.now() - timezone.timedelta(minutes=minutos_atras),
                )
            return m

        print('=== 1. Presas antigas não bloqueiam o chat ===')
        antigas = [resposta(minutos_atras=60) for _ in range(MAX_CONCURRENT_STREAMS_PER_USER)]
        try:
            check_concurrency_limit(vinculo.tenant_id, user.id)
            liberado = True
        except ConcurrencyLimitExceeded:
            liberado = False
        conferir(f'{MAX_CONCURRENT_STREAMS_PER_USER} respostas perdidas há uma hora não contam no limite', liberado)

        print('=== 2. A varredura encerra a presa antiga e deixa a recente ===')
        recente = resposta()
        tasks.encerrar_respostas_presas()
        estados = set(ChatMessage.objects.filter(id__in=[m.id for m in antigas]).values_list('state', flat=True))
        conferir('as antigas viram "falhou"', estados == {ChatMessageState.FAILED}, estados)
        recente.refresh_from_db()
        conferir('a recente continua transmitindo', recente.state == ChatMessageState.STREAMING, recente.state)
        agendadas = {v['task'] for v in settings.CELERY_BEAT_SCHEDULE.values()}
        conferir('a varredura está no beat', 'ai.tasks.encerrar_respostas_presas' in agendadas)

        print('=== 3. Cancelada na fila: o provedor não é chamado ===')
        na_fila = resposta()
        ChatMessage.objects.filter(id=na_fila.id).update(state=ChatMessageState.CANCELLED)
        chamado = []
        original = tasks.get_chat_model
        tasks.get_chat_model = lambda **_: chamado.append(True)
        try:
            retorno = tasks.run_chat_turn.run(str(na_fila.id), str(na_fila.id))
        finally:
            tasks.get_chat_model = original
        conferir('a tarefa sai sem chamar o provedor', not chamado and retorno.get('status') == 'skipped', retorno)

        print('=== 4. O fim da tarefa não desfaz o cancelamento ===')
        cancelada = resposta()
        ChatMessage.objects.filter(id=cancelada.id).update(state=ChatMessageState.CANCELLED)
        finalize_assistant_message(cancelada, 'texto que chegou depois do cancelamento')
        cancelada.refresh_from_db()
        conferir('continua cancelada', cancelada.state == ChatMessageState.CANCELLED, cancelada.state)
        conferir('e sem o texto que chegou depois', cancelada.content == '', cancelada.content)

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('OK: a resposta presa é encerrada e o cancelamento vale.')
