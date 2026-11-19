"""Incluir horário fora da cadência da semana: o caso de 2026-11-19.

Relato de produção: numa agenda de quarta das 13h30 com células de 45 min
(13h30, 14h15, 15h00, 15h45...), a secretária excluiu 14h15 e 15h00 e
incluiu 14h30. O sistema reabriu o pedaço 14h30–15h15 dos excluídos, mas a
grade só desenha células na cadência da regra, e ali não cabia nenhuma: o
período ficou aberto e **invisível**. Depois disso, todo "Incluir horário"
às 14h30 era recusado como "já é horário de atendimento", e o dia aparecia
vazio no mês.

O que este roteiro tenta quebrar:

1. o caso exato: excluir 14h15 e 15h00 e incluir 14h30 deixa uma célula
   **livre** 14h30–15h15 na grade, que aceita reserva, sem célula
   sobreposta;
2. o estado que ficou em produção (os excluídos aparados, sem extra): o
   período fantasma não recusa mais, e incluir 14h30 cria a célula;
3. o que continua recusado: o pedido sobre uma célula que **existe**
   (livre, e ocupada), e sobre bloqueio de data;
4. o que continua como era: excluir e incluir no mesmo lugar é desfazer
   (nenhum extra gravado), estender depois do fim da janela grava só o
   pedaço de fora, e o almoço não recusa o extra;
5. excluir a célula incluída fora da cadência a tira da grade;
6. a semana, o mês e a lista de horários livres enxergam a célula.

Tudo numa transação desfeita no fim, com clínica e médico próprios.
"""
import datetime
import uuid
from datetime import time, timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from patients.models import Patient, RegistrationStage
from scheduling import services
from scheduling.availability import _combine, available_slots, day_grid, fits, month_summary, week_grid
from scheduling.models import (
    AvailabilityRule, RecurringBreak, ScheduleBlock, ScheduleBlockKind,
)
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []
CHR = chr(10)


def confere(condicao, rotulo, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {rotulo}' + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        falhas.append(rotulo)


class Desfazer(Exception):
    pass


def hm(valor):
    return timezone.localtime(valor).strftime('%H:%M')


def grade(medico, dia):
    return [(hm(c['start']), hm(c['end']), c['status']) for c in day_grid(medico.id, dia)]


def sobrepostas(medico, dia):
    cells = sorted(day_grid(medico.id, dia), key=lambda c: c['start'])
    return [
        (hm(a['start']), hm(b['start'])) for a, b in zip(cells, cells[1:]) if b['start'] < a['end']
    ]


def recusa(funcao, *args):
    try:
        funcao(*args)
        return ''
    except services.SchedulingError as exc:
        return str(exc) or '(sem texto)'


try:
    with transaction.atomic():
        tenant = Tenant.objects.create(
            legal_name='Clínica da cadência', slug=f'cad-{uuid.uuid4().hex[:10]}',
            cpf=str(uuid.uuid4().int)[:11],
        )
        user = User.objects.create_user(email=f'medica-{uuid.uuid4().hex[:6]}@example.com', password='x-Senha-123!')
        medico = Membership.objects.create(
            tenant=tenant, user=user, roles=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
            activated_at=timezone.now(),
        )
        sec_user = User.objects.create_user(email=f'sec-{uuid.uuid4().hex[:6]}@example.com', password='x-Senha-123!')
        secretaria = Membership.objects.create(
            tenant=tenant, user=sec_user, roles=[Role.SECRETARY], status=MembershipStatus.ACTIVE,
            activated_at=timezone.now(),
        )
        ctx = AccessContext(
            user_id=sec_user.id, tenant_id=tenant.id, membership_id=secretaria.id,
            permissions=frozenset([Role.SECRETARY]), request_id=None, tenant_status=tenant.status,
            capabilities=frozenset(),
        )

        # Uma quarta daqui a umas três semanas, e a regra de produção.
        hoje = timezone.localdate()
        dia = hoje + timedelta(days=21)
        while dia.weekday() != 2:
            dia += timedelta(days=1)
        AvailabilityRule.objects.create(
            tenant=tenant, physician_membership=medico, weekday=2,
            local_start=time(13, 30), local_end=time(17, 15), starts_on=hoje,
            ends_on=hoje + timedelta(days=365), slot_minutes=45, buffer_minutes=0,
            appointment_type='other',
        )
        em = lambda h, m: _combine(dia, time(h, m))  # noqa: E731

        print(CHR + '1. O caso exato: excluir 14h15 e 15h00, incluir 14h30')
        confere(grade(medico, dia)[:3] == [('13:30', '14:15', 'free'), ('14:15', '15:00', 'free'), ('15:00', '15:45', 'free')],
                'a grade de partida', str(grade(medico, dia)))
        services.remove_free_slot(ctx, medico, em(14, 15))
        services.remove_free_slot(ctx, medico, em(15, 0))
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(14, 30), 1)
        confere(erro == '', 'incluir 14h30 aceito', erro)
        g = grade(medico, dia)
        confere(('14:30', '15:15', 'free') in g, 'a célula 14h30–15h15 aparece livre', str(g))
        confere(not sobrepostas(medico, dia), 'nenhuma célula sobreposta', str(sobrepostas(medico, dia)))
        confere(fits(medico.id, em(14, 30), em(15, 15))[0], 'a reserva cabe nela', str(fits(medico.id, em(14, 30), em(15, 15))))
        confere(em(14, 30) in [inicio for inicio, _ in available_slots(medico.id, dia, minutes=45)], 'está na lista de horários livres')
        confere(('13:30', '14:15', 'free') in g and ('15:45', '16:30', 'free') in g, 'as vizinhas continuam')

        print(CHR + '2. O estado que ficou em produção: o fantasma não recusa mais')
        ScheduleBlock.objects.filter(physician_membership=medico).delete()
        for (h1, m1), (h2, m2) in (((14, 15), (14, 30)), ((15, 15), (15, 45))):
            ScheduleBlock.objects.create(
                tenant=tenant, physician_membership=medico, start_at=em(h1, m1), end_at=em(h2, m2),
                kind=ScheduleBlockKind.REMOVED_SLOT, reason='Horário excluído pela agenda',
            )
        g = grade(medico, dia)
        confere(not any(i in ('14:15', '14:30', '15:00') for i, _, _ in g), 'de partida, sem célula entre 14h15 e 15h45 (o fantasma)', str(g))
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(14, 30), 1)
        confere(erro == '', 'incluir 14h30 aceito', erro)
        confere(('14:30', '15:15', 'free') in grade(medico, dia), 'a célula aparece', str(grade(medico, dia)))
        confere(not sobrepostas(medico, dia), 'nenhuma célula sobreposta')

        print(CHR + '3. O que continua recusado')
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(14, 30), 1)
        confere('já é horário de atendimento' in erro, 'de novo sobre a célula incluída', erro)
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(13, 45), 1)
        confere('já é horário de atendimento' in erro and '13:30' in erro, 'encavalado na célula livre das 13h30', erro)
        paciente = Patient.objects.create(tenant=tenant, full_name='Paciente da cadência',
                                          registration_stage=RegistrationStage.COMPLETE,
                                          birth_date_unknown_reason='Roteiro.')
        from scheduling.models import Appointment, AppointmentStatus, AppointmentType
        Appointment.objects.create(
            tenant=tenant, patient=paciente, physician_membership=medico, starts_at=em(15, 45),
            ends_at=em(16, 30), occupied_range=(em(15, 45), em(16, 30)),
            status=AppointmentStatus.SCHEDULED, type=AppointmentType.OTHER,
        )
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(16, 0), 1)
        confere('já é horário de atendimento' in erro, 'sobre a célula ocupada', erro)
        ScheduleBlock.objects.create(
            tenant=tenant, physician_membership=medico, start_at=em(18, 0), end_at=em(20, 0),
            kind=ScheduleBlockKind.BLOCK, reason='Cirurgia',
        )
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(18, 30), 1)
        confere('bloqueado' in erro, 'sobre bloqueio de data', erro)

        print(CHR + '4. O que continua como era')
        ScheduleBlock.objects.filter(physician_membership=medico).delete()
        Appointment.objects.filter(physician_membership=medico).delete()
        services.remove_free_slot(ctx, medico, em(14, 15))
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(14, 15), 1)
        confere(erro == '', 'excluir e incluir no mesmo lugar', erro)
        confere(not ScheduleBlock.objects.filter(physician_membership=medico).exists(),
                'é desfazer: nenhum extra nem excluído gravado')
        services.remove_free_slot(ctx, medico, em(16, 30))
        services.include_extra_hours(ctx, medico, dia, time(16, 30), 2)
        extras = list(ScheduleBlock.objects.filter(physician_membership=medico, kind=ScheduleBlockKind.EXTRA_AVAILABILITY))
        confere(len(extras) == 1 and hm(extras[0].start_at) == '17:15' and hm(extras[0].end_at) == '18:00',
                'reabrir 16h30 e estender: grava só o pedaço de fora',
                str([(hm(e.start_at), hm(e.end_at)) for e in extras]))
        confere(('17:15', '18:00', 'free') in grade(medico, dia), 'e a célula aparece')
        ScheduleBlock.objects.filter(physician_membership=medico).delete()
        RecurringBreak.objects.create(
            tenant=tenant, physician_membership=medico, weekday=2, local_start=time(15, 0),
            local_end=time(15, 45), starts_on=hoje, reason='Almoço',
        )
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(15, 0), 1)
        confere(erro == '', 'o almoço não recusa o extra', erro)
        RecurringBreak.objects.filter(physician_membership=medico).delete()
        ScheduleBlock.objects.filter(physician_membership=medico).delete()

        print(CHR + '5. Excluir a célula incluída fora da cadência')
        services.remove_free_slot(ctx, medico, em(14, 15))
        services.remove_free_slot(ctx, medico, em(15, 0))
        services.include_extra_hours(ctx, medico, dia, time(14, 30), 1)
        services.remove_free_slot(ctx, medico, em(14, 30))
        g = grade(medico, dia)
        confere(not any(i in ('14:15', '14:30', '15:00') for i, _, _ in g), 'some da grade, sem reabrir as da semana', str(g))
        erro = recusa(services.include_extra_hours, ctx, medico, dia, time(14, 30), 1)
        confere(erro == '' and ('14:30', '15:15', 'free') in grade(medico, dia), 'e pode ser incluída de novo', erro)

        print(CHR + '6. Semana, mês e lista de livres')
        _, colunas = week_grid(medico.id, dia - timedelta(days=dia.weekday()))
        do_dia = next(c for c in colunas if c['date'] == dia)
        confere(any(hm(c['start']) == '14:30' and c['status'] == 'free' for c in do_dia['cells']), 'a semana mostra 14h30')
        mes = month_summary(medico.id, [dia])
        resumo = mes.get(dia) or {}
        livres_dia = sum(1 for c in day_grid(medico.id, dia) if c['status'] == 'free')
        confere(resumo.get('free') == livres_dia, 'o mês conta igual à grade do dia', f'{resumo} x {livres_dia}')

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('check_horario_fora_da_cadencia: tudo certo.')
