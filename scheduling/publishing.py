"""Publicar a agenda de um médico por um período, e tratar os feriados.

"Publicar" aqui não é materializar horários. É declarar as regras semanais
com vigência (`AvailabilityRule.starts_on`/`ends_on`) e, na sequência,
resolver os feriados que caem nesse período — que é a parte que precisa de
decisão humana.

O fluxo tem dois passos de propósito:

1. o médico declara a grade semanal e até quando ela vale;
2. o sistema lista os feriados do período e **pergunta** o que bloquear.

O segundo passo não é automático porque atender em feriado é decisão do
médico: plantão, mutirão, reposição de agenda. Bloquear sozinho tiraria
horários que ele queria oferecer, e não bloquear deixaria a secretária
marcando paciente para um dia em que a clínica está fechada. Perguntar é o
único caminho que não erra por conta própria.
"""

from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .holidays import holidays_in_range, national_holidays
from .models import (
    AppointmentType, AppointmentTypeDuration, AvailabilityRule, Holiday, HolidayScope,
    OCCUPYING_STATUSES, Appointment, RecurringBreak, ScheduleBlock, ScheduleBlockKind,
)

WEEKDAY_LABELS = (
    (0, 'Segunda-feira'), (1, 'Terça-feira'), (2, 'Quarta-feira'), (3, 'Quinta-feira'),
    (4, 'Sexta-feira'), (5, 'Sábado'), (6, 'Domingo'),
)
WEEKDAY_SHORT = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sáb', 6: 'Dom'}


class PublishError(Exception):
    pass


def _aware(day, time_value):
    naive = datetime.combine(day, time_value)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


@transaction.atomic
def set_type_durations(context, membership, minutes_by_type):
    """Grava a duração de cada tipo de atendimento deste médico."""
    for appointment_type, minutes in minutes_by_type.items():
        if minutes is None:
            continue
        row, _ = AppointmentTypeDuration.objects.update_or_create(
            tenant_id=context.tenant_id, physician_membership=membership,
            appointment_type=appointment_type, defaults={'minutes': int(minutes)},
        )
        row.full_clean()
        row.save()
    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.durations_configured',
        object_type='membership', object_id=membership.id, outcome='success',
        integrity_metadata={str(k): v for k, v in minutes_by_type.items() if v},
    )


def rules_for(membership, reference_date=None):
    """Regras vigentes (ou futuras) deste médico, para a tela de configuração."""
    reference_date = reference_date or timezone.localdate()
    return list(
        AvailabilityRule.objects
        .filter(physician_membership=membership)
        .filter(models_ends_on_ok(reference_date))
        .order_by('weekday', 'local_start')
    )


def models_ends_on_ok(reference_date):
    from django.db.models import Q

    return Q(ends_on__isnull=True) | Q(ends_on__gte=reference_date)


def appointments_outside_rules(membership, start, end):
    """Reservas que ficariam fora da grade nova.

    Chamado antes de encurtar ou remover uma regra. Encurtar a vigência não
    apaga reserva nenhuma — o paciente continua marcado —, mas a tela precisa
    dizer quantas passariam a estar fora do horário declarado, senão o médico
    encurta a agenda sem saber que deixou pacientes num horário que ele
    acabou de fechar.
    """
    from .availability import fits

    pending = Appointment.objects.filter(
        physician_membership=membership, status__in=list(OCCUPYING_STATUSES),
        starts_at__date__gte=start, starts_at__date__lte=end,
    ).select_related('patient').order_by('starts_at')
    out = []
    for appointment in pending:
        ok, reason = fits(membership.id, appointment.starts_at, appointment.ends_at)
        if not ok:
            out.append({'appointment': appointment, 'reason': reason})
    return out


# --------------------------------------------------------------------------
# Feriados
# --------------------------------------------------------------------------

@transaction.atomic
def ensure_national_holidays(context, years):
    """Garante que os feriados nacionais dos anos pedidos estão cadastrados.

    Calculados, não baixados (ver `scheduling.holidays`). Idempotente: rodar
    de novo não duplica nem sobrescreve o que a clínica editou à mão — só o
    que tem `source='computed'` é gerenciado aqui.
    """
    created = 0
    for year in years:
        for row in national_holidays(year):
            _, was_created = Holiday.objects.get_or_create(
                tenant_id=context.tenant_id, date=row['date'], name=row['name'],
                defaults={
                    'scope': HolidayScope.NATIONAL,
                    'recurring': row['recurring'],
                    'source': 'computed',
                    # Ponto facultativo entra desativado: não é feriado, e
                    # ligá-lo por conta própria bloquearia agenda com base
                    # numa afirmação que o sistema não pode fazer.
                    'active': not row['optional'],
                },
            )
            created += 1 if was_created else 0
    return created


def holidays_to_review(context, membership, start, end):
    """Feriados do período, com o que já está bloqueado marcado.

    É o que a tela de revisão mostra. `blocked` diz se já existe um
    `ScheduleBlock` de feriado naquele dia para este médico — assim reabrir a
    tela mostra o estado atual em vez de sugerir tudo de novo.
    """
    state, city = _practice_place(membership)
    rows = holidays_in_range(context.tenant_id, start, end, state=state, city=city)
    blocked_dates = set(
        timezone.localtime(block.start_at).date()
        for block in ScheduleBlock.objects.filter(
            physician_membership=membership, kind=ScheduleBlockKind.HOLIDAY,
            start_at__date__gte=start, start_at__date__lte=end,
        )
    )
    weekdays_with_rules = set(
        AvailabilityRule.objects.filter(physician_membership=membership)
        .filter(models_ends_on_ok(start)).values_list('weekday', flat=True)
    )
    for row in rows:
        row['blocked'] = row['date'] in blocked_dates
        # Feriado que cai em dia sem atendimento não precisa de decisão: já
        # não há horário para bloquear. Some da lista para não pedir 12
        # confirmações inúteis.
        row['has_schedule'] = row['date'].weekday() in weekdays_with_rules
    return [row for row in rows if row['has_schedule']]


def _practice_place(membership):
    """UF e município onde o médico atende, para o feriado local valer.

    Vem do endereço da organização: é onde o consultório está. Sem endereço
    cadastrado, só os feriados nacionais se aplicam — o que é o
    comportamento correto, e não um chute de localidade.
    """
    tenant = membership.tenant
    settings_blob = tenant.settings or {}
    return (
        (settings_blob.get('state') or '').strip(),
        (settings_blob.get('city') or '').strip(),
    )


@transaction.atomic
def apply_holiday_blocks(context, membership, dates_to_block, start, end, reasons=None):
    """Bloqueia os dias escolhidos e libera os que foram desmarcados.

    Trabalha sobre o intervalo inteiro: o que está na lista fica bloqueado, o
    que não está tem o bloqueio de feriado removido. Assim a tela funciona
    como um conjunto de interruptores, e desmarcar significa "vou atender
    nesse dia".

    Só remove bloqueio de `kind=holiday`: férias e bloqueio manual não são
    tocados por esta tela.
    """
    reasons = reasons or {}
    wanted = set(dates_to_block)
    existing = {
        timezone.localtime(block.start_at).date(): block
        for block in ScheduleBlock.objects.filter(
            physician_membership=membership, kind=ScheduleBlockKind.HOLIDAY,
            start_at__date__gte=start, start_at__date__lte=end,
        )
    }

    blocked, released, kept_appointments = 0, 0, []
    for day in wanted:
        if day in existing:
            continue
        # Reserva que já existe naquele dia não é apagada: bloquear o feriado
        # fecha a agenda para novas marcações, e o que já está marcado é
        # decisão de remarcar ou não — que a tela informa.
        clashes = Appointment.objects.filter(
            physician_membership=membership, status__in=list(OCCUPYING_STATUSES),
            starts_at__date=day,
        ).select_related('patient')
        kept_appointments.extend(clashes)
        block = ScheduleBlock(
            tenant_id=context.tenant_id, physician_membership=membership,
            start_at=_aware(day, time.min), end_at=_aware(day, time.min) + timedelta(days=1),
            kind=ScheduleBlockKind.HOLIDAY,
            reason=(reasons.get(day) or 'Feriado')[:255], override_rule=True,
        )
        block.full_clean()
        block.save()
        blocked += 1

    for day, block in existing.items():
        if day not in wanted:
            block.delete()
            released += 1

    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.holiday_blocks_applied',
        object_type='membership', object_id=membership.id, outcome='success',
        integrity_metadata={'blocked': blocked, 'released': released,
                            'range': [start.isoformat(), end.isoformat()]},
    )
    return {'blocked': blocked, 'released': released, 'appointments': kept_appointments}


def coverage_summary(membership, start, end):
    """Quantos dias e horários a agenda oferece no período.

    Serve para a tela dizer "a agenda está publicada até 31/12/2027, com
    1.248 horários" — que é o que responde à pergunta "publiquei mesmo?".
    """
    from .availability import day_grid

    rules = AvailabilityRule.objects.filter(physician_membership=membership).filter(
        models_ends_on_ok(start),
    )
    if not rules.exists():
        return {'days': 0, 'slots': 0, 'until': None, 'weekdays': []}

    ends = [rule.ends_on for rule in rules]
    until = None if any(e is None for e in ends) else max(ends)
    weekdays = sorted({rule.weekday for rule in rules})

    # Amostra uma semana e multiplica: contar célula por célula um ano
    # inteiro seriam 365 montagens de grade a cada abertura da tela, e o
    # número exato não muda a decisão de quem lê.
    sample_start = start
    week_slots = 0
    week_days = 0
    for offset in range(7):
        day = sample_start + timedelta(days=offset)
        if day > end:
            break
        cells = day_grid(membership.id, day)
        if cells:
            week_days += 1
            week_slots += len(cells)
    total_days = (min(end, until) - start).days + 1 if until else (end - start).days + 1
    weeks = max(total_days / 7, 0)
    return {
        'days': int(week_days * weeks),
        'slots': int(week_slots * weeks),
        'until': until,
        'weekdays': [WEEKDAY_SHORT[day] for day in weekdays],
    }


@transaction.atomic
def publish_weekly_schedule(context, membership, data):
    """Cria as regras semanais a partir do formulário de grade.

    Uma regra por dia marcado. `replace_existing` encerra as regras que já
    existiam naqueles dias em vez de apagá-las: encurtar a vigência preserva
    a agenda passada — a grade de um dia já atendido continua sendo
    reconstruível como era, e é isso que faz a agenda de ontem não mudar
    quando o médico muda o horário de amanhã.
    """
    weekdays = [int(day) for day in data['weekdays']]
    starts_on = data['starts_on']
    ends_on = data.get('ends_on')

    replaced = 0
    if data.get('replace_existing'):
        current = AvailabilityRule.objects.filter(
            physician_membership=membership, weekday__in=weekdays,
        ).filter(models_ends_on_ok(starts_on))
        for rule in current:
            if rule.starts_on >= starts_on:
                # Regra que ainda não começou a valer pode sair de vez: não
                # há agenda passada para preservar.
                rule.delete()
            else:
                rule.ends_on = starts_on - timedelta(days=1)
                rule.full_clean()
                rule.save(update_fields=['ends_on'])
            replaced += 1

    # As pausas dos mesmos dias seguem a regra: substituir encerra as
    # que valiam, em vez de apaga-las. A agenda de ontem continua
    # reconstruivel como era -- inclusive o almoco de ontem.
    pausas_encerradas = 0
    if data.get('replace_existing'):
        for pausa in RecurringBreak.objects.filter(
            physician_membership=membership, weekday__in=weekdays,
        ).filter(models_ends_on_ok(starts_on)):
            if pausa.starts_on >= starts_on:
                pausa.delete()
            else:
                pausa.ends_on = starts_on - timedelta(days=1)
                pausa.full_clean()
                pausa.save(update_fields=['ends_on'])
            pausas_encerradas += 1

    created = []
    pausas_criadas = []
    for weekday in weekdays:
        rule = AvailabilityRule(
            tenant_id=context.tenant_id, physician_membership=membership, weekday=weekday,
            local_start=data['local_start'], local_end=data['local_end'],
            starts_on=starts_on, ends_on=ends_on,
            slot_minutes=data['slot_minutes'],
            buffer_minutes=data.get('buffer_minutes') or 0,
            appointment_type=AppointmentType.OTHER,
        )
        rule.full_clean()
        rule.save()
        created.append(rule)

        for pausa in data.get('pausas') or []:
            linha = RecurringBreak(
                tenant_id=context.tenant_id, physician_membership=membership,
                weekday=weekday, local_start=pausa['inicio'], local_end=pausa['fim'],
                starts_on=starts_on, ends_on=ends_on, reason=pausa.get('motivo', ''),
            )
            linha.full_clean()
            linha.save()
            pausas_criadas.append(linha)

    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.schedule_published',
        object_type='membership', object_id=membership.id, outcome='success',
        integrity_metadata={
            'weekdays': weekdays, 'from': starts_on.isoformat(),
            'until': ends_on.isoformat() if ends_on else None,
            'window': f"{data['local_start']}–{data['local_end']}",
            'slot_minutes': data['slot_minutes'], 'replaced': replaced,
            'pausas': [
                f"{p['inicio']}-{p['fim']}" for p in (data.get('pausas') or [])
            ],
        },
    )
    return {
        'created': created, 'replaced': replaced,
        'pausas': pausas_criadas, 'pausas_encerradas': pausas_encerradas,
    }


@transaction.atomic
def remove_rule(context, membership, rule):
    """Encerra uma regra da grade.

    Regra que já vigorou é encerrada (`ends_on` = ontem), não apagada: a
    agenda dos dias já atendidos continua sendo reconstruível como era.
    Regra que ainda não começou sai de vez.

    **A regra que começa hoje é o terceiro caso, e ele faltava.** Ela
    caía no `else` e recebia `ends_on` = ontem, que é anterior ao
    `starts_on` — `full_clean` recusava e a tela devolvia 500. Quem
    publicou a grade hoje e quis desfazer batia nisso, que é exatamente
    quem mais erra: o primeiro ajuste é o que se refaz.

    O desfecho certo para ela depende de haver agenda marcada hoje:

    - **sem agendamento hoje**, nada aconteceu ainda, e apagar é o que a
      pessoa pediu. É o caso de quem acabou de publicar e viu que errou;
    - **com agendamento hoje**, encerrar **hoje** (`ends_on` = hoje) em
      vez de apagar. Apagando, as células de hoje deixariam de existir e
      o paciente já marcado sumiria do calendário — a reserva continuaria
      no banco, invisível na tela em que se trabalha.

    As pausas semanais daquele dia saem junto, mas só quando **nenhuma
    outra regra** sobra naquele dia da semana: com manhã e tarde
    declaradas em envios separados, remover a manhã não pode levar o
    almoço que a tarde ainda usa.
    """
    today = timezone.localdate()

    if rule.starts_on > today:
        outcome = 'deleted'
    elif rule.starts_on == today:
        tem_agenda_hoje = Appointment.objects.filter(
            physician_membership=membership,
            starts_at__gte=_aware(today, time.min),
            starts_at__lt=_aware(today + timedelta(days=1), time.min),
            status__in=list(OCCUPYING_STATUSES),
        ).exists()
        outcome = 'closed_today' if tem_agenda_hoje else 'deleted'
    else:
        outcome = 'closed'

    weekday = rule.weekday
    if outcome == 'deleted':
        rule.delete()
    else:
        rule.ends_on = today if outcome == 'closed_today' else today - timedelta(days=1)
        rule.full_clean()
        rule.save(update_fields=['ends_on'])

    # As pausas acompanham a regra: intervalo que sobra sozinho volta a
    # recortar a agenda no dia em que alguém republicar aquele dia sem
    # substituir — um almoço de uma grade que não existe mais.
    pausas_removidas = 0
    ainda_atende = AvailabilityRule.objects.filter(
        physician_membership=membership, weekday=weekday,
    ).filter(models_ends_on_ok(today)).exists()
    if not ainda_atende:
        for pausa in RecurringBreak.objects.filter(
            physician_membership=membership, weekday=weekday,
        ).filter(models_ends_on_ok(today)):
            if pausa.starts_on >= today and outcome == 'deleted':
                pausa.delete()
            else:
                pausa.ends_on = today if outcome == 'closed_today' else today - timedelta(days=1)
                if pausa.ends_on < pausa.starts_on:
                    pausa.delete()
                else:
                    pausa.full_clean()
                    pausa.save(update_fields=['ends_on'])
            pausas_removidas += 1

    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.rule_removed',
        object_type='membership', object_id=membership.id, outcome='success',
        integrity_metadata={
            'weekday': weekday, 'result': outcome, 'pausas': pausas_removidas,
        },
    )
    return outcome
