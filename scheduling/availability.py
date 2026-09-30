"""Disponibilidade e grade da agenda.

O desenho central: **uma célula base, ocupação variável.**

O médico declara a janela ("segunda, 08h às 18h") e o tamanho da célula
(40 min). A duração de cada tipo de atendimento é configurada por médico
(`AppointmentTypeDuration`): primeira consulta 80, retorno 40. Reservar uma
primeira consulta ocupa **duas** células consecutivas; um retorno ocupa uma.

A alternativa — uma régua de horários por tipo — não dá calendário: cada
tipo pediria uma coluna própria, e a secretária não teria como ver de uma
vez o que está livre. Com célula base, existe uma grade só, e é ela que a
tela mostra em cores.

Nada é materializado. Publicar a agenda por um ano não cria trinta mil
linhas de horário: a grade é calculada a partir das regras, dos bloqueios e
das reservas. Mudar a regra passa a valer imediatamente, sem regeneração —
e não há como a agenda materializada e a regra discordarem.

Precedência, do mais forte para o mais fraco:

1. bloqueio de data (`ScheduleBlock`: feriado, férias, bloqueio) tira o
   horário, mesmo dentro da janela semanal — é o "exceção de data prevalece
   sobre regra semanal" do RF-06.02;
2. atendimento extra (`ScheduleBlock` de kind `extra_availability`)
   acrescenta janela fora da regra;
3. reserva que ocupa (`OCCUPYING_STATUSES`) marca a célula.
"""

from datetime import datetime, time, timedelta
from math import gcd

from django.db.models import Q
from django.utils import timezone

from .models import (
    DEFAULT_TYPE_MINUTES, OCCUPYING_STATUSES, Appointment, AppointmentType,
    AppointmentTypeDuration, AvailabilityRule, ScheduleBlock, ScheduleBlockKind,
)

#: Célula usada quando o médico ainda não declarou nenhuma regra. Não é
#: chute clínico: é só o passo do desenho da grade vazia.
FALLBACK_SLOT_MINUTES = 30


def _combine(day, time_value):
    naive = datetime.combine(day, time_value)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


def day_bounds(day):
    start = _combine(day, time.min)
    return start, start + timedelta(days=1)


def _ends_on_ok(day):
    return Q(ends_on__isnull=True) | Q(ends_on__gte=day)


def type_durations(physician_membership_id):
    """Duração de cada tipo para este médico, com o padrão onde faltar."""
    configured = {
        row.appointment_type: row.minutes
        for row in AppointmentTypeDuration.objects.filter(
            physician_membership_id=physician_membership_id,
        )
    }
    return {
        value: configured.get(value, DEFAULT_TYPE_MINUTES[value])
        for value in AppointmentType.values
    }


def suggested_slot_minutes(physician_membership_id):
    """Célula base sugerida: o MDC das durações configuradas.

    É o maior tamanho de célula em que **toda** duração cabe num número
    inteiro de células — 80 e 40 dão 40; 60 e 45 dariam 15. Serve como
    sugestão no formulário; a célula que vale é a que o médico declarou na
    regra.
    """
    minutes = [m for m in type_durations(physician_membership_id).values() if m]
    if not minutes:
        return FALLBACK_SLOT_MINUTES
    result = minutes[0]
    for value in minutes[1:]:
        result = gcd(result, value)
    return max(result, 5)


def rules_on(physician_membership_id, day):
    return list(
        AvailabilityRule.objects.filter(
            physician_membership_id=physician_membership_id,
            weekday=day.weekday(), starts_on__lte=day,
        ).filter(_ends_on_ok(day)).order_by('local_start')
    )


def blocks_on(physician_membership_id, day):
    start, end = day_bounds(day)
    return list(
        ScheduleBlock.objects.filter(
            physician_membership_id=physician_membership_id,
            start_at__lt=end, end_at__gt=start,
        ).order_by('start_at')
    )


def appointments_on(physician_membership_id, day, include_all=False):
    start, end = day_bounds(day)
    # `patient__contacts` vem junto porque a agenda mostra, em cada
    # horário marcado, para onde a confirmação por SMS e por e-mail
    # seria enviada. Sem o prefetch é uma consulta por paciente na tela.
    queryset = Appointment.objects.filter(
        physician_membership_id=physician_membership_id,
        starts_at__lt=end, ends_at__gt=start,
    ).select_related('patient').prefetch_related('patient__contacts')
    if not include_all:
        queryset = queryset.filter(status__in=list(OCCUPYING_STATUSES))
    return list(queryset.order_by('starts_at'))


def _subtract(intervals, block_start, block_end):
    result = []
    for start, end in intervals:
        if block_end <= start or block_start >= end:
            result.append((start, end))
            continue
        if block_start > start:
            result.append((start, block_start))
        if block_end < end:
            result.append((block_end, end))
    return result


def open_intervals(physician_membership_id, day, rules=None, blocks=None):
    """Janelas em que o médico atende neste dia, já descontados os bloqueios.

    Não desconta reserva: a reserva **marca** a célula, e a grade precisa
    mostrar a célula ocupada, não escondê-la. Esconder o horário reservado
    faria a secretária achar que o médico não atende naquela hora.
    """
    rules = rules if rules is not None else rules_on(physician_membership_id, day)
    blocks = blocks if blocks is not None else blocks_on(physician_membership_id, day)
    day_start, day_end = day_bounds(day)

    intervals = [(_combine(day, rule.local_start), _combine(day, rule.local_end)) for rule in rules]
    for block in blocks:
        if block.kind == ScheduleBlockKind.EXTRA_AVAILABILITY:
            intervals.append((max(block.start_at, day_start), min(block.end_at, day_end)))
    for block in blocks:
        if block.kind != ScheduleBlockKind.EXTRA_AVAILABILITY:
            intervals = _subtract(intervals, block.start_at, block.end_at)
    return sorted(i for i in intervals if i[0] < i[1])


def slot_minutes_for(physician_membership_id, day, rules=None):
    """Tamanho da célula neste dia — o menor entre as regras que valem.

    Menor, e não o da primeira regra: com duas regras no mesmo dia (manhã de
    40, tarde de 20), a grade tem de ter célula que sirva às duas, senão a
    tarde apareceria com horários que não existem.
    """
    rules = rules if rules is not None else rules_on(physician_membership_id, day)
    values = [rule.slot_minutes for rule in rules if rule.slot_minutes]
    if not values:
        return None
    return min(values)


def day_grid(physician_membership_id, day, appointments=None, include_cancelled=False,
             rules=None, blocks=None):
    """A grade do dia, célula por célula, para a tela desenhar.

    Cada célula é um dicionário com `start`, `end`, `status` e o que aquele
    status precisa: a reserva, quando ocupada; o bloqueio e o motivo, quando
    bloqueada.

    `status` é um de:

    - `free` — dá para marcar;
    - `busy` — tem reserva ocupando;
    - `past` — livre, mas já passou: oferecer ao paciente não faz sentido;
    - `blocked` — dentro da janela semanal, mas tirado por bloqueio de data.

    Célula fora da janela do médico simplesmente não existe na lista — a
    grade da tela desenha o vazio.
    """
    # `rules`/`blocks` podem vir pré-carregados: a visão de mês monta 42
    # grades, e ir ao banco em cada uma seriam mais de cem consultas para
    # desenhar um calendário.
    rules = rules if rules is not None else rules_on(physician_membership_id, day)
    blocks = blocks if blocks is not None else blocks_on(physician_membership_id, day)
    step = slot_minutes_for(physician_membership_id, day, rules=rules)
    extra = [b for b in blocks if b.kind == ScheduleBlockKind.EXTRA_AVAILABILITY]
    if step is None:
        # Dia sem regra semanal, mas com atendimento extra, é justamente o
        # mutirão numa quarta em que o médico não atende. Sem esta saída o dia
        # voltava vazio e o extra não abria nada — a célula vem da duração
        # configurada por ele.
        if not extra:
            return []
        step = suggested_slot_minutes(physician_membership_id)

    if appointments is None:
        appointments = appointments_on(physician_membership_id, day, include_all=include_cancelled)

    open_windows = open_intervals(physician_membership_id, day, rules=rules, blocks=blocks)
    # Janela declarada **antes** dos bloqueios: é a diferença entre as duas
    # que produz a célula "blocked", que a tela mostra com o motivo em vez de
    # deixar um buraco inexplicado.
    declared = [(_combine(day, rule.local_start), _combine(day, rule.local_end)) for rule in rules]
    for block in extra:
        declared.append((block.start_at, block.end_at))

    blocking = [b for b in blocks if b.kind != ScheduleBlockKind.EXTRA_AVAILABILITY]
    now = timezone.now()
    occupying = [a for a in appointments if a.status in OCCUPYING_STATUSES]

    cells = []
    seen = set()
    for window_start, window_end in sorted(declared):
        cursor = window_start
        while cursor + timedelta(minutes=step) <= window_end:
            cell_end = cursor + timedelta(minutes=step)
            if cursor in seen:
                cursor = cell_end
                continue
            seen.add(cursor)

            appointment = next(
                (a for a in occupying if a.starts_at < cell_end and a.ends_at > cursor), None,
            )
            block = next(
                (b for b in blocking if b.start_at < cell_end and b.end_at > cursor), None,
            )
            inside_open = any(start <= cursor and cell_end <= end for start, end in open_windows)

            if appointment is not None:
                status = 'busy'
            elif block is not None or not inside_open:
                status = 'blocked'
            elif cell_end <= now:
                status = 'past'
            else:
                status = 'free'

            cells.append({
                'start': cursor, 'end': cell_end, 'status': status,
                'appointment': appointment, 'block': block,
                # A reserva começa nesta célula? A tela desenha o nome do
                # paciente só na primeira, e as seguintes como continuação —
                # senão uma consulta de 80 minutos apareceria duas vezes.
                'is_start': appointment is not None and appointment.starts_at >= cursor,
                'reason': (block.reason or block.get_kind_display()) if block else '',
            })
            cursor = cell_end
    return cells


def week_grid(physician_membership_id, week_start, include_cancelled=False):
    """Sete dias de grade, com a régua de horários comum às colunas.

    Devolve `(horas, colunas)`. `horas` é a régua da esquerda; cada coluna
    traz o dia e um mapa hora -> célula, para o template não precisar
    procurar.
    """
    days = [week_start + timedelta(days=index) for index in range(7)]
    columns = []
    times = set()
    for day in days:
        cells = day_grid(physician_membership_id, day, include_cancelled=include_cancelled)
        by_time = {}
        for cell in cells:
            key = timezone.localtime(cell['start']).strftime('%H:%M')
            by_time[key] = cell
            times.add(key)
        columns.append({
            'date': day, 'cells': cells, 'by_time': by_time,
            'free': sum(1 for c in cells if c['status'] == 'free'),
            'busy': sum(1 for c in cells if c['status'] == 'busy'),
            'total': len(cells),
        })
    ordered_times = sorted(times)
    for column in columns:
        column['rows'] = [column['by_time'].get(hour) for hour in ordered_times]
    return ordered_times, columns


def available_slots(physician_membership_id, day, minutes=None):
    """Horários em que **cabe** um atendimento de `minutes` neste dia.

    Diferente de `day_grid`: aqui a resposta é "onde dá para marcar uma
    consulta desta duração", então células consecutivas livres são
    consideradas juntas. Uma primeira consulta de 80 minutos só aparece onde
    houver duas células livres seguidas.
    """
    cells = day_grid(physician_membership_id, day)
    if not cells:
        return []
    step = slot_minutes_for(physician_membership_id, day)
    needed = max(1, -(-int(minutes or step) // step)) if step else 1

    slots = []
    free_run = []
    for cell in cells:
        if cell['status'] == 'free':
            if free_run and cell['start'] != free_run[-1]['end']:
                free_run = []
            free_run.append(cell)
            if len(free_run) >= needed:
                window = free_run[-needed:]
                slots.append((window[0]['start'], window[-1]['end']))
        else:
            free_run = []
    return slots


def fits(physician_membership_id, starts_at, ends_at):
    """Se o intervalo cabe inteiro em célula livre.

    Usado antes de reservar. O banco já impede sobreposição pela
    ExclusionConstraint; isto é o que impede marcar **fora** da janela do
    médico ou dentro de um feriado bloqueado — coisas que a constraint não
    tem como saber.

    A recusa diz **qual** é o problema, e a distinção importa: célula
    ocupada e célula livre onde a duração não cabe são coisas diferentes.
    Dizer "horário já ocupado" para um horário visivelmente livre na tela
    faz a secretária desconfiar da agenda em vez de escolher outro tipo de
    atendimento.
    """
    day = timezone.localtime(starts_at).date()
    cells = day_grid(physician_membership_id, day)
    covered = [c for c in cells if c['start'] < ends_at and c['end'] > starts_at]
    if not covered:
        return False, 'Fora dos horários de atendimento deste médico.'

    minutes = int((ends_at - starts_at).total_seconds() // 60)
    blocked = [c for c in covered if c['status'] == 'blocked']
    if blocked:
        return False, blocked[0]['reason'] or 'Horário bloqueado na agenda.'

    busy = [c for c in covered if c['status'] == 'busy']
    if busy:
        if busy[0] is covered[0]:
            return False, 'Este horário já está ocupado.'
        local = timezone.localtime(busy[0]['start']).strftime('%H:%M')
        return False, (
            f'Um atendimento de {minutes} minutos não cabe a partir daqui: '
            f'às {local} o horário já está ocupado. Escolha um tipo mais curto '
            'ou outro horário.'
        )

    if covered[0]['start'] > starts_at or covered[-1]['end'] < ends_at:
        end_local = timezone.localtime(covered[-1]['end']).strftime('%H:%M')
        return False, (
            f'Um atendimento de {minutes} minutos não cabe a partir daqui: '
            f'o atendimento deste dia termina às {end_local}.'
        )
    return True, ''


def month_summary(physician_membership_id, days):
    """Contagem de horários livres e ocupados para cada dia da lista.

    Existe para a visão de mês poder responder "onde tem vaga" — que é a
    pergunta de quem está remarcando ao telefone. Uma célula de mês com
    apenas "2 pacientes" não diz se ainda cabe alguém.

    Carrega regras, bloqueios e reservas **uma vez** e monta as grades em
    memória. Chamar `day_grid` por dia seriam mais de cem consultas para
    desenhar um calendário; assim são três.
    """
    if not days:
        return {}
    start, end = min(days), max(days)
    day_start = _combine(start, time.min)
    day_end = _combine(end, time.min) + timedelta(days=1)

    all_rules = list(
        AvailabilityRule.objects.filter(
            physician_membership_id=physician_membership_id, starts_on__lte=end,
        ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=start))
    )
    all_blocks = list(
        ScheduleBlock.objects.filter(
            physician_membership_id=physician_membership_id,
            start_at__lt=day_end, end_at__gt=day_start,
        )
    )
    all_appointments = list(
        Appointment.objects.filter(
            physician_membership_id=physician_membership_id,
            starts_at__lt=day_end, ends_at__gt=day_start,
            status__in=list(OCCUPYING_STATUSES),
        ).select_related('patient')
    )

    summary = {}
    for day in days:
        window_start = _combine(day, time.min)
        window_end = window_start + timedelta(days=1)
        rules = [
            rule for rule in all_rules
            if rule.weekday == day.weekday() and rule.starts_on <= day
            and (rule.ends_on is None or rule.ends_on >= day)
        ]
        blocks = [
            block for block in all_blocks
            if block.start_at < window_end and block.end_at > window_start
        ]
        appointments = [
            appointment for appointment in all_appointments
            if appointment.starts_at < window_end and appointment.ends_at > window_start
        ]
        cells = day_grid(
            physician_membership_id, day, appointments=appointments,
            rules=rules, blocks=blocks,
        )
        # "Ocupados" conta **pacientes**, não células: uma consulta de 80 min
        # ocupa duas células e continua sendo um paciente. Contar células
        # faria a agenda parecer duas vezes mais cheia do que está.
        summary[day] = {
            'free': sum(1 for cell in cells if cell['status'] == 'free'),
            'past': sum(1 for cell in cells if cell['status'] == 'past'),
            'blocked': sum(1 for cell in cells if cell['status'] == 'blocked'),
            'booked': len({
                cell['appointment'].id for cell in cells
                if cell['status'] == 'busy' and cell['appointment'] is not None
            }),
            'total': len(cells),
            'works': bool(cells),
            # A visão mensal usa a mesma grade já calculada para oferecer
            # cada vaga diretamente. Guardar as células aqui não acrescenta
            # consulta: elas acabaram de ser montadas com os três lotes
            # carregados acima.
            'cells': cells,
        }
    return summary
