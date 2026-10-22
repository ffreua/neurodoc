"""A agenda da semana carregada em lote, com a mesma grade (auditoria de 2026-10, P2).

`week_grid` chamava `day_grid` sete vezes sem nada pré-carregado: regras,
bloqueios, pausas e reservas buscados por dia, de 28 a 35 consultas para
desenhar a semana. Agora carrega tudo uma vez e entrega a cada dia a parte
dele, como `month_summary` já fazia.

O risco de uma mudança dessas não é o número de consultas: é a grade sair
**diferente**. Por isso a seção principal monta uma semana com tudo o que
mexe na grade — regra que termina no meio da semana, pausa, bloqueio com
motivo, férias, horário excluído, atendimento extra no sábado, reserva
cancelada, consulta de 80 minutos — e compara, **célula por célula**, com
`day_grid` dia a dia, que é o caminho antigo e continua sendo o da visão
de dia.

Tudo em transação desfeita.

    docker compose exec -T app python manage.py shell < checks/check_semana_em_lote.py
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from patients.models import Patient
from scheduling.availability import day_grid, week_grid
from scheduling.models import (
    Appointment, AppointmentStatus, AvailabilityRule, RecurringBreak, ScheduleBlock, ScheduleBlockKind,
)
from tenancy.models import Membership

settings.ALLOWED_HOSTS += ['testserver']
settings.SECURE_SSL_REDIRECT = False

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


def resumo(cells):
    def _id(obj):
        return obj.id if obj is not None else None
    return [
        (c['start'], c['end'], c['status'], _id(c['appointment']), _id(c['block']),
         _id(c['exibida']), c['reason'], c['is_start'], c['unblock_id'])
        for c in cells
    ]


user = User.objects.get(email='doctor-a@demo.neurodoc.local')
medico = (Membership.objects
          .filter(user=user, status='active', roles__contains=['doctor'])
          .order_by('created_at').first())
paciente = Patient.objects.filter(tenant_id=medico.tenant_id).order_by('created_at').first()
fuso = timezone.get_current_timezone()
hoje = timezone.localdate()
segunda = hoje - timedelta(days=hoje.weekday()) + timedelta(weeks=6)
dias = [segunda + timedelta(days=i) for i in range(7)]


def quando(dia, h, m=0):
    return datetime.combine(dia, time(h, m), fuso)


def reservar(inicio, minutos=40, status=AppointmentStatus.SCHEDULED):
    fim = inicio + timedelta(minutes=minutos)
    return Appointment.objects.create(
        tenant_id=medico.tenant_id, patient=paciente, physician_membership=medico,
        starts_at=inicio, ends_at=fim, occupied_range=DateTimeTZRange(inicio, fim), status=status,
    )


def montar_semana():
    base = dict(tenant_id=medico.tenant_id, physician_membership=medico)
    for wd in range(5):
        AvailabilityRule.objects.create(
            **base, weekday=wd, local_start=time(8), local_end=time(12),
            starts_on=segunda - timedelta(days=30), slot_minutes=40,
        )
    # Tarde que deixa de valer na quarta: segunda a quarta têm, quinta e sexta não.
    for wd in range(5):
        AvailabilityRule.objects.create(
            **base, weekday=wd, local_start=time(14), local_end=time(16),
            starts_on=segunda - timedelta(days=30), ends_on=dias[2], slot_minutes=20,
        )
    # Regra de sexta que passa a valer no meio desta semana.
    AvailabilityRule.objects.create(
        **base, weekday=4, local_start=time(17), local_end=time(18),
        starts_on=dias[3], slot_minutes=30,
    )
    RecurringBreak.objects.create(
        **base, weekday=1, local_start=time(10), local_end=time(10, 20),
        starts_on=segunda - timedelta(days=30), reason='Café',
    )
    ScheduleBlock.objects.create(
        **base, kind=ScheduleBlockKind.BLOCK, reason='Reunião',
        start_at=quando(dias[3], 8), end_at=quando(dias[3], 8, 40),
    )
    ScheduleBlock.objects.create(
        **base, kind=ScheduleBlockKind.VACATION, reason='Férias',
        start_at=quando(dias[4], 0), end_at=quando(dias[5], 0),
    )
    ScheduleBlock.objects.create(
        **base, kind=ScheduleBlockKind.REMOVED_SLOT,
        start_at=quando(dias[0], 9, 20), end_at=quando(dias[0], 10),
    )
    ScheduleBlock.objects.create(
        **base, kind=ScheduleBlockKind.EXTRA_AVAILABILITY,
        start_at=quando(dias[5], 9), end_at=quando(dias[5], 11),
    )
    reservar(quando(dias[0], 8, 40), minutos=80)
    reservar(quando(dias[2], 14, 20), minutos=20, status=AppointmentStatus.CANCELLED)
    reservar(quando(dias[5], 9, 40))


def volume(n):
    # As quatro primeiras às 11h20, de segunda a quinta; as seguintes às 15h,
    # inclusive na quinta, em que a tarde já não vale — encaixe fora da grade.
    for i in range(n):
        dia = dias[i % 4]
        if i < 4:
            reservar(quando(dia, 11, 20))
        else:
            reservar(quando(dia, 15), minutos=20)


medidas = {}
for n in (2, 8):
    with transaction.atomic():
        montar_semana()
        volume(n)

        if n == 8:
            print('=== 1. A semana em lote é a mesma grade de cada dia ===')
            for cancelados in (False, True):
                _, colunas = week_grid(medico.id, segunda, include_cancelled=cancelados)
                for dia, coluna in zip(dias, colunas):
                    antigo = resumo(day_grid(medico.id, dia, include_cancelled=cancelados))
                    novo = resumo(coluna['cells'])
                    conferir(f'{dia:%a %d/%m} (cancelados={cancelados}): {len(novo)} células iguais',
                             antigo == novo, f'{len(antigo)} x {len(novo)}')

            print('=== 2. O cenário cobre o que mexe na grade ===')
            _, colunas = week_grid(medico.id, segunda)
            status = {c['status'] for col in colunas for c in col['cells']}
            razoes = {c['reason'] for col in colunas for c in col['cells']}
            conferir('há célula ocupada, livre e fechada', {'busy', 'free', 'blocked'} <= status, status)
            conferir('a pausa e o bloqueio aparecem com o motivo', {'Café', 'Reunião'} <= razoes, razoes)
            conferir('o sábado abre pelo atendimento extra', colunas[5]['total'] > 0)
            conferir('a tarde some depois da quarta',
                     not any(timezone.localtime(c['start']).hour == 14 for c in colunas[3]['cells']))

        with CaptureQueriesContext(connection) as q:
            week_grid(medico.id, segunda)
        dia_a_dia = 0
        for dia in dias:
            with CaptureQueriesContext(connection) as q2:
                day_grid(medico.id, dia)
            dia_a_dia += len(q2)
        medidas[n] = (len(q), dia_a_dia)
        transaction.set_rollback(True)

print('=== 3. O número de consultas não cresce com o volume ===')
conferir('mesmas consultas com 2 e 8 reservas', medidas[2][0] == medidas[8][0], medidas)
conferir('menos consultas que dia a dia', medidas[8][0] < medidas[8][1], medidas)
print(f'  (semana em lote: {medidas[8][0]} consultas; dia a dia: {medidas[8][1]})')

print('=== 4. A tela da semana abre ===')
cliente = Client()
cliente.force_login(user)
sessao = cliente.session
sessao['tenant_id'] = str(medico.tenant_id)
sessao.save()
resposta = cliente.get(f"{reverse('scheduling:week')}?physician={medico.id}&date={segunda:%Y-%m-%d}")
conferir('abre com 200', resposta.status_code == 200, resposta.status_code)

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: a semana em lote desenha a mesma grade com número fixo de consultas.')
