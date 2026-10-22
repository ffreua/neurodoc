"""Uma sincronização da TUSS por vez (auditoria de 2026-10, C3).

`retomar_tuss_incompleta` roda de hora em hora e dispara uma rodada sempre
que há tabela em rascunho — e há rascunho também enquanto a cadeia está
**viva**. A segunda rodada baixava as mesmas páginas da ANS (~80 s cada) e
morria na unicidade do código, depois de ocupar um dos dois lugares do
worker por até 45 minutos.

O roteiro segura a trava **por outra conexão**, como a rodada em andamento
seguraria, e confere: a segunda não chama a ANS nem se reagenda; sem
ninguém segurando, a rodada roda e se reagenda como antes; e a trava é
solta no fim, inclusive quando a rodada estoura.

Nada fala com a ANS: `sync_incremental` é simulado.

    docker compose exec -T app python manage.py shell < checks/check_tuss_uma_rodada.py
"""
from unittest.mock import patch

from django.db import connections

from catalogs import tasks
from integrations import tuss

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


outra = connections.create_connection('default')


def trava_livre():
    """Tenta pegar a trava pela outra conexão; solta se conseguir."""
    with outra.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [tasks.TUSS_LOCK])
        livre = cursor.fetchone()[0]
        if livre:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [tasks.TUSS_LOCK])
    return livre


PARCIAL = {'completo': False, 'paginas': 3, 'total': 75, 'versao': 'ANS-roteiro'}

try:
    print('=== 1. Com outra rodada em andamento, esta não roda ===')
    with outra.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_lock(%s)', [tasks.TUSS_LOCK])
    with patch.object(tuss, 'sync_incremental', return_value=PARCIAL) as ans, \
            patch.object(tasks.sync_tuss_task, 'apply_async') as reagenda:
        resultado = tasks.sync_tuss_task()
    conferir('não chama a ANS', not ans.called)
    conferir('não se reagenda (a rodada viva já agenda a próxima)', not reagenda.called)
    conferir('diz que há outra em andamento', resultado.get('em_andamento') is True, resultado)
    with outra.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s)', [tasks.TUSS_LOCK])

    print('=== 2. Sozinha, a rodada roda e se reagenda como antes ===')
    with patch.object(tuss, 'sync_incremental', return_value=PARCIAL) as ans, \
            patch.object(tasks.sync_tuss_task, 'apply_async') as reagenda:
        resultado = tasks.sync_tuss_task()
    conferir('chama a ANS', ans.called)
    conferir('reagenda a próxima rodada', reagenda.called)
    conferir('e solta a trava no fim', trava_livre())

    print('=== 3. A rodada que estoura também solta a trava ===')
    with patch.object(tuss, 'sync_incremental', side_effect=RuntimeError('simulada')), \
            patch.object(tasks.sync_tuss_task, 'apply_async') as reagenda:
        resultado = tasks.sync_tuss_task()
    conferir('a falha é engolida, como antes', resultado.get('ok') is False, resultado)
    conferir('não reagenda', not reagenda.called)
    conferir('a trava está livre', trava_livre())

    print('=== 4. A ANS fora do ar também solta a trava ===')
    with patch.object(tuss, 'sync_incremental', side_effect=tuss.TussUnavailable('fora')):
        tasks.sync_tuss_task()
    conferir('a trava está livre', trava_livre())
finally:
    outra.close()

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: uma sincronização da TUSS por vez, e a trava sempre solta.')
