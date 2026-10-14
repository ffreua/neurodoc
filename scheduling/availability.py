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
    AppointmentStatus,
    DEFAULT_TYPE_MINUTES, OCCUPYING_STATUSES, Appointment, AppointmentType,
    AppointmentTypeDuration, AvailabilityRule, RecurringBreak, ScheduleBlock,
    ScheduleBlockKind,
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


def breaks_on(physician_membership_id, day):
    """As pausas semanais que valem neste dia."""
    return list(
        RecurringBreak.objects.filter(
            physician_membership_id=physician_membership_id,
            weekday=day.weekday(), starts_on__lte=day,
        ).filter(_ends_on_ok(day)),
    )


def open_intervals(physician_membership_id, day, rules=None, blocks=None, breaks=None):
    """Janelas em que o médico atende neste dia, já descontados os bloqueios.

    Não desconta reserva: a reserva **marca** a célula, e a grade precisa
    mostrar a célula ocupada, não escondê-la. Esconder o horário reservado
    faria a secretária achar que o médico não atende naquela hora.

    **Desconta a pausa semanal** (`RecurringBreak`), e este é o único
    lugar onde isso precisa acontecer: `day_grid`, `available_slots` e a
    validação da reserva passam todos por aqui. Pôr a subtração em cada
    um deles seria três chances de esquecer uma — e a esquecida seria a
    que deixa marcar paciente no horário do almoço.

    A pausa entra **depois** do atendimento extra, de propósito: o extra
    é uma janela aberta à mão para um dia específico, e abrir das 11h às
    13h num dia em que se almoça das 12h às 13h quer dizer "hoje eu
    atendo até as 13h". A ordem aqui faz a pausa recortar também o
    extra, o que é o contrário disso — e é por isso que o extra é
    acrescentado **depois** de a pausa ter recortado a janela semanal.
    """
    rules = rules if rules is not None else rules_on(physician_membership_id, day)
    blocks = blocks if blocks is not None else blocks_on(physician_membership_id, day)
    breaks = breaks if breaks is not None else breaks_on(physician_membership_id, day)
    day_start, day_end = day_bounds(day)

    intervals = [(_combine(day, rule.local_start), _combine(day, rule.local_end)) for rule in rules]
    # A pausa recorta a janela **semanal**, e só ela.
    for pausa in breaks:
        intervals = _subtract(
            intervals, _combine(day, pausa.local_start), _combine(day, pausa.local_end),
        )
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
             rules=None, blocks=None, historico=None, breaks=None):
    """A grade do dia, célula por célula, para a tela desenhar.

    Cada célula é um dicionário com `start`, `end`, `status` e o que aquele
    status precisa: a reserva, quando ocupada; o bloqueio e o motivo, quando
    bloqueada.

    `status` é um de:

    - `free` — dá para marcar;
    - `busy` — tem reserva ocupando;
    - `past` — livre, já passou, e **ninguém foi atendido nele**;
    - `done` — já passou e houve atendimento concluído ou falta;
    - `blocked` — dentro da janela semanal, mas tirado por bloqueio de data.

    **Por que `done` existe, separado de `busy`.** `COMPLETED` e `NO_SHOW`
    não estão em `OCCUPYING_STATUSES`, de propósito: atendimento encerrado
    libera a vaga para remarcação. A consequência era que, olhando um mês
    passado, as consultas que de fato aconteceram **sumiam** da tela — a
    célula voltava como `past`, indistinguível de um horário que ninguém
    usou. Quem navegasse setembro veria a agenda vazia de um mês cheio.

    `done` conserta isso sem tocar na disponibilidade: ele nasce de uma
    célula que já seria `past`, e nenhuma conta de vaga livre olha para
    `past` nem para `done`.

    Célula fora da janela do médico simplesmente não existe na lista — a
    grade da tela desenha o vazio.
    """
    # `rules`/`blocks` podem vir pré-carregados: a visão de mês monta 42
    # grades, e ir ao banco em cada uma seriam mais de cem consultas para
    # desenhar um calendário.
    rules = rules if rules is not None else rules_on(physician_membership_id, day)
    blocks = blocks if blocks is not None else blocks_on(physician_membership_id, day)
    breaks = breaks if breaks is not None else breaks_on(physician_membership_id, day)
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

    open_windows = open_intervals(
        physician_membership_id, day, rules=rules, blocks=blocks, breaks=breaks,
    )
    # Janela declarada **antes** dos bloqueios de data: é a diferença entre
    # as duas que produz a célula "blocked", que a tela mostra com o motivo
    # em vez de deixar um buraco inexplicado.
    janelas_da_regra = [
        (_combine(day, rule.local_start), _combine(day, rule.local_end)) for rule in rules
    ]
    declared = list(janelas_da_regra)

    # **A pausa semanal parte a janela; o bloqueio de data não.** São duas
    # coisas diferentes e a diferença é esta, que custou um defeito:
    #
    # - o bloqueio de data (férias, feriado) é uma exceção posta **por
    #   cima** de um dia de trabalho que continua tendo a forma de sempre.
    #   A célula existe, e aparece fechada com o motivo;
    #
    # - a pausa semanal **é a forma do dia**. O almoço não fecha uma célula:
    #   ele termina a manhã e começa a tarde.
    #
    # Sem partir aqui, a cadência seguia correndo a partir do início da
    # janela e a pausa apenas fechava a célula que a tocasse. Com janela
    # 08h40–18h40, célula de 40 min e almoço das 12h40 às 13h, o dia saía
    # ... 12h00, [12h40 fechada], 13h20 ... — perdia a célula inteira das
    # 12h40 **e** voltava 20 minutos depois do fim do almoço. O esperado é
    # ... 12h00, [almoço], 13h00, 13h40 ...: a tarde recomeça quando a
    # pausa acaba.
    for pausa in breaks:
        declared = _subtract(
            declared, _combine(day, pausa.local_start), _combine(day, pausa.local_end),
        )
    for block in extra:
        declared.append((block.start_at, block.end_at))

    blocking = [b for b in blocks if b.kind != ScheduleBlockKind.EXTRA_AVAILABILITY]
    now = timezone.now()
    occupying = [a for a in appointments if a.status in OCCUPYING_STATUSES]
    # O que **aconteceu** e já não ocupa: concluído e falta. Entra só para
    # a tela poder mostrar o passado como ele foi, e nunca na conta de
    # vaga livre.
    realizados = list(historico or [])

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

            realizado = next(
                (a for a in realizados if a.starts_at < cell_end and a.ends_at > cursor), None,
            )

            if appointment is not None:
                status = 'busy'
            elif block is not None or not inside_open:
                status = 'blocked'
            elif cell_end <= now:
                # `done` quando houve atendimento ali; `past` quando a hora
                # passou e ninguém usou. A distinção é o que permite a tela
                # dizer "vago" sem mentir sobre o mês que já foi.
                status = 'done' if realizado is not None else 'past'
            else:
                status = 'free'

            mostrado = appointment if appointment is not None else realizado
            cells.append({
                'start': cursor, 'end': cell_end, 'status': status,
                'appointment': appointment, 'block': block,
                # A reserva que a célula exibe: a que ocupa, ou a que já
                # aconteceu. A tela lê daqui para não precisar escolher.
                'exibida': mostrado,
                # A reserva começa nesta célula? A tela desenha o nome do
                # paciente só na primeira, e as seguintes como continuação —
                # senão uma consulta de 80 minutos apareceria duas vezes.
                'is_start': mostrado is not None and mostrado.starts_at >= cursor,
                # O motivo da célula fechada, na ordem em que ela foi
                # fechada: bloqueio de data primeiro, depois a pausa
                # semanal. Célula "blocked" sem motivo faz a secretária
                # ligar para o médico perguntando se dá para encaixar.
                'reason': (block.reason or block.get_kind_display()) if block else '',
            })
            cursor = cell_end

    # A pausa entra como **uma** célula, com o horário real dela — e não
    # como a célula da grade que ela tocaria.
    #
    # Ela não participa da cadência (a grade já foi partida acima), mas
    # precisa aparecer: um buraco de vinte minutos sem explicação entre
    # 12h40 e 13h faz a secretária ligar para o médico perguntando se dá
    # para encaixar. Com a célula, a agenda diz "Almoço" e a pergunta não
    # nasce.
    #
    # Só quando cai dentro de uma janela que a regra declarou: pausa
    # configurada para um horário em que o médico não atende não tem o que
    # recortar, e desenhá-la inventaria uma linha na agenda.
    for pausa in breaks:
        inicio = _combine(day, pausa.local_start)
        fim = _combine(day, pausa.local_end)
        if not any(w_start < fim and inicio < w_end for w_start, w_end in janelas_da_regra):
            continue
        cells.append({
            'start': inicio, 'end': fim, 'status': 'blocked',
            'appointment': None, 'block': None, 'exibida': None, 'is_start': False,
            'reason': pausa.reason or 'Intervalo',
        })

    # Ordenar no fim: a pausa foi acrescentada depois, e a tela desenha na
    # ordem em que a lista vem. Sem isto o almoço aparecia no rodapé do
    # dia.
    cells.sort(key=lambda c: c['start'])
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


def fits(physician_membership_id, starts_at, ends_at, ignorar=None):
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

    `ignorar` é a própria consulta, quando é ela quem pergunta — esticar o
    tipo, ou remarcar meia hora para frente. Sem isso a consulta das 17h
    não podia passar a terminar às 18h20 porque "às 17h o horário já está
    ocupado": por ela mesma.
    """
    day = timezone.localtime(starts_at).date()
    appointments = None
    if ignorar is not None:
        appointments = [
            a for a in appointments_on(physician_membership_id, day) if a.id != ignorar
        ]
    cells = day_grid(physician_membership_id, day, appointments=appointments)
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
    # O que já aconteceu e não ocupa mais. Carregado no mesmo lote, e
    # usado **só para exibição**: sem isto, um mês passado aparecia vazio,
    # porque atendimento concluído libera a vaga e a célula voltava como
    # "passou e ninguém usou".
    all_history = list(
        Appointment.objects.filter(
            physician_membership_id=physician_membership_id,
            starts_at__lt=day_end, ends_at__gt=day_start,
            status__in=[AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW],
        ).select_related('patient')
    )
    # As pausas do período inteiro, num lote só — pelo mesmo motivo das
    # regras: a visão de mês monta 42 grades, e uma consulta por grade
    # seriam 42 idas ao banco para desenhar um calendário.
    all_breaks = list(
        RecurringBreak.objects.filter(
            physician_membership_id=physician_membership_id,
        ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=days[0]))
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
        historico = [
            a for a in all_history
            if a.starts_at < window_end and a.ends_at > window_start
        ]
        breaks = [
            pausa for pausa in all_breaks
            if pausa.weekday == day.weekday() and pausa.starts_on <= day
            and (pausa.ends_on is None or pausa.ends_on >= day)
        ]
        cells = day_grid(
            physician_membership_id, day, appointments=appointments,
            rules=rules, blocks=blocks, historico=historico, breaks=breaks,
        )
        # "Ocupados" conta **pacientes**, não células: uma consulta de 80 min
        # ocupa duas células e continua sendo um paciente. Contar células
        # faria a agenda parecer duas vezes mais cheia do que está.
        summary[day] = {
            'free': sum(1 for cell in cells if cell['status'] == 'free'),
            # `past` agora é só o horário que passou **sem ninguém**: é o
            # número que a tela mostra como "vago". Antes ele somava os dois
            # casos, e por isso um mês inteiro passado aparecia como
            # "lotado" -- zero vaga livre lido como agenda cheia.
            'past': sum(1 for cell in cells if cell['status'] == 'past'),
            'blocked': sum(1 for cell in cells if cell['status'] == 'blocked'),
            'booked': len({
                cell['appointment'].id for cell in cells
                if cell['status'] == 'busy' and cell['appointment'] is not None
            }),
            #: Quantos pacientes foram atendidos (ou faltaram) neste dia.
            #: Contado por paciente, como `booked`, e não por célula.
            'realizados': len({
                cell['exibida'].id for cell in cells
                if cell['status'] == 'done' and cell['exibida'] is not None
            }),
            'total': len(cells),
            'works': bool(cells),
            #: O dia inteiro já passou? A tela usa isto para não dizer
            #: "lotado" num dia em que simplesmente não cabe mais marcar.
            'encerrado': bool(cells) and all(
                cell['status'] in ('past', 'done', 'busy', 'blocked') for cell in cells
            ) and not any(cell['status'] == 'free' for cell in cells),
            # A visão mensal usa a mesma grade já calculada para oferecer
            # cada vaga diretamente. Guardar as células aqui não acrescenta
            # consulta: elas acabaram de ser montadas com os três lotes
            # carregados acima.
            'cells': cells,
        }
    return summary
