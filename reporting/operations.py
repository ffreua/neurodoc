import datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from finance.models import FinancialAdjustment, Payment, ReceivableStatus
from finance.payments import quantize_brl
from finance.selectors import visible_receivables
from scheduling.models import OCCUPYING_STATUSES, Appointment, AvailabilityRule, ScheduleBlock


def _day_bounds(day):
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    end = timezone.make_aware(datetime.datetime.combine(day, datetime.time.max))
    return start, end


def schedule_occupancy(tenant, physician_membership, start, end):
    """Minutos ocupados por reservas válidas / minutos ofertados após
    bloqueios. Encaixes (`is_overbook`) são somados à parte -- nunca
    misturados ao numerador padrão, para nunca mascarar uma taxa > 100%.
    """
    offered_minutes = 0
    day = start
    while day <= end:
        weekday = day.weekday()
        rules = AvailabilityRule.objects.filter(
            tenant=tenant, physician_membership=physician_membership, weekday=weekday,
        ).filter(Q(starts_on__isnull=True) | Q(starts_on__lte=day)).filter(
            Q(ends_on__isnull=True) | Q(ends_on__gte=day),
        )
        day_offered = sum(
            (rule.local_end.hour * 60 + rule.local_end.minute) - (rule.local_start.hour * 60 + rule.local_start.minute)
            for rule in rules
        )
        day_start, day_end = _day_bounds(day)
        blocks = ScheduleBlock.objects.filter(
            tenant=tenant, physician_membership=physician_membership, kind__in=['block', 'vacation'],
            start_at__lte=day_end, end_at__gte=day_start,
        )
        blocked_minutes = 0
        for block in blocks:
            overlap_start = max(block.start_at, day_start)
            overlap_end = min(block.end_at, day_end)
            if overlap_end > overlap_start:
                blocked_minutes += (overlap_end - overlap_start).total_seconds() / 60
        offered_minutes += max(day_offered - blocked_minutes, 0)
        day += datetime.timedelta(days=1)

    appointments = Appointment.objects.filter(
        tenant=tenant, physician_membership=physician_membership,
        starts_at__date__gte=start, starts_at__date__lte=end, status__in=OCCUPYING_STATUSES,
    )
    occupied_minutes = 0.0
    overbook_minutes = 0.0
    for appt in appointments:
        duration = (appt.ends_at - appt.starts_at).total_seconds() / 60
        if appt.is_overbook:
            overbook_minutes += duration
        else:
            occupied_minutes += duration

    return {
        'offered_minutes': offered_minutes, 'occupied_minutes': occupied_minutes, 'overbook_minutes': overbook_minutes,
        'rate': (occupied_minutes / offered_minutes) if offered_minutes else None,
        'rate_with_overbook': ((occupied_minutes + overbook_minutes) / offered_minutes) if offered_minutes else None,
    }


def payment_category_breakdown(tenant, start, end, unit='patient'):
    """`unit='patient'` (padrão) ou `unit='appointment'` -- nunca soma as
    duas visões sem indicar qual foi escolhida, e nunca duplica um
    paciente que tenha ambas as categorias na mesma janela.
    """
    receivables = visible_receivables(tenant).filter(
        competence_date__gte=start, competence_date__lte=end,
    ).exclude(status=ReceivableStatus.CANCELLED)
    result = {}
    for category_field, snapshot_key in [('private', 'private'), ('insurance', 'insurance')]:
        qs = receivables.filter(fee_snapshot__payment_category=snapshot_key)
        if unit == 'patient':
            result[category_field] = qs.values('patient_id').distinct().count()
        else:
            result[category_field] = qs.count()
    return result


def revenue_by_competence(tenant, start, end):
    """Soma charged_amount (já líquido de desconto/acréscimo, aplicados em
    S09 diretamente sobre esse campo) das cobranças elegíveis pela
    competence_date -- recebimento em caixa é reportado separadamente.
    """
    receivables = visible_receivables(tenant).filter(
        competence_date__gte=start, competence_date__lte=end,
    ).exclude(status=ReceivableStatus.CANCELLED)
    total = quantize_brl(0)
    for r in receivables:
        total += r.charged_amount
    return total


def cash_received(tenant, start, end):
    """Soma Payment.amount menos estornos, pela data em que o dinheiro
    efetivamente chegou (paid_at) -- nunca pela competência da cobrança.
    """
    payments = Payment.objects.filter(
        tenant=tenant,
        receivable__archived_at__isnull=True,
        receivable__doctor_share_paid_at__isnull=True,
        paid_at__date__gte=start,
        paid_at__date__lte=end,
    )
    total_paid = quantize_brl(0)
    for p in payments:
        total_paid += p.amount
    refunds = FinancialAdjustment.objects.filter(
        tenant=tenant,
        receivable__archived_at__isnull=True,
        receivable__doctor_share_paid_at__isnull=True,
        type='refund', payment__paid_at__date__gte=start, payment__paid_at__date__lte=end,
    )
    total_refunded = quantize_brl(0)
    for a in refunds:
        total_refunded += a.amount
    return quantize_brl(total_paid - total_refunded)


def outstanding_balance(tenant, as_of_date):
    """Cobrado líquido menos recebido líquido, por vencimento até a data
    de corte -- um saldo negativo indica crédito e exige conciliação, não
    é tratado como dívida.
    """
    from finance.payments import balance

    receivables = visible_receivables(tenant).filter(
        due_date__lte=as_of_date,
    ).exclude(status=ReceivableStatus.CANCELLED)
    total = quantize_brl(0)
    for r in receivables:
        total += balance(r)
    return total


def doctor_share_forecast(tenant, start, end):
    """Soma do repasse previsto (snapshot congelado no momento da
    cobrança) -- nunca rotulado como repasse efetivamente pago.
    """
    receivables = visible_receivables(tenant).filter(
        competence_date__gte=start, competence_date__lte=end,
    ).exclude(status=ReceivableStatus.CANCELLED)
    total = quantize_brl(0)
    for r in receivables:
        share = r.fee_snapshot.get('doctor_share_amount')
        if share:
            total += quantize_brl(Decimal(share))
    return total


def atendidos_por_tipo(tenant, start, end):
    """Consultas atendidas no período, por tipo da agenda.

    Atendido é quem fez check-in, como nas estatísticas da agenda. O tipo é
    o que a secretária marcou no horário (primeira consulta, seguimento,
    retorno, procedimento) — não inferido do histórico do paciente.
    """
    from django.db.models import Count

    from scheduling.estatisticas import ATENDIDOS
    from scheduling.models import AppointmentType

    linhas = dict(
        Appointment.objects.filter(
            tenant=tenant, status__in=ATENDIDOS,
            starts_at__date__gte=start, starts_at__date__lte=end,
        ).values_list('type').annotate(n=Count('id'))
    )
    return {codigo: linhas.get(codigo, 0) for codigo, _rotulo in AppointmentType.choices}


#: A ordem das linhas da receita por tipo: as consultas na ordem da agenda,
#: depois os procedimentos, um por linha, do que mais rendeu.
_ORDEM_DAS_CONSULTAS = ('first_visit', 'follow_up', 'return_visit', 'other', 'procedure', '')


def receita_por_tipo(tenant, start, end):
    """A receita por competência, discriminada: consultas por tipo e cada procedimento.

    Soma o mesmo conjunto de `revenue_by_competence` (cobranças visíveis e
    não canceladas com competência no período), então a última linha fecha
    com o total da tela. Cada cobrança vai para uma linha só:

    - **procedimento** (`charge_kind`, ou o procedimento na regra de
      honorário) entra na linha do próprio procedimento, pelo código TUSS e
      a descrição — "para quem faz": sem procedimento, a linha não existe;
    - **consulta** entra pelo tipo do horário (primeira consulta, seguimento,
      retorno); sem horário, pelo tipo gravado na regra de honorário; sem
      nenhum dos dois, "Consulta sem tipo na agenda" (atendimento aberto
      direto no prontuário, ou o histórico migrado).
    """
    from catalogs.models import ProcedureCode
    from finance.models import ChargeKind
    from scheduling.models import AppointmentType

    rotulos = dict(AppointmentType.choices)
    cobrancas = list(
        visible_receivables(tenant).filter(
            competence_date__gte=start, competence_date__lte=end,
        ).exclude(status=ReceivableStatus.CANCELLED).select_related('appointment')
        .only('charge_kind', 'fee_snapshot', 'charged_amount', 'appointment__type')
    )
    ids_de_procedimento = {
        (c.fee_snapshot or {}).get('procedure_id') for c in cobrancas
    } - {None, ''}
    procedimentos = {
        str(pid): f'{codigo} — {descricao[:80]}'
        for pid, codigo, descricao in ProcedureCode.objects.filter(id__in=ids_de_procedimento)
        .values_list('id', 'code', 'description')
    }

    grupos = {}
    for c in cobrancas:
        snap = c.fee_snapshot or {}
        pid = snap.get('procedure_id')
        if c.charge_kind == ChargeKind.PROCEDURE or pid:
            chave = ('procedimento', str(pid or ''))
            rotulo = procedimentos.get(str(pid), 'Procedimento sem código')
        else:
            tipo = (c.appointment.type if c.appointment_id else '') or snap.get('appointment_type') or ''
            chave = ('consulta', tipo)
            rotulo = rotulos.get(tipo, 'Consulta sem tipo na agenda')
        g = grupos.setdefault(chave, {'rotulo': rotulo, 'grupo': chave[0], 'tipo': chave[1],
                                      'n': 0, 'valor': quantize_brl(0)})
        g['n'] += 1
        g['valor'] += c.charged_amount

    consultas = sorted(
        (g for (k, _), g in grupos.items() if k == 'consulta'),
        key=lambda g: _ORDEM_DAS_CONSULTAS.index(g['tipo']) if g['tipo'] in _ORDEM_DAS_CONSULTAS else 99,
    )
    procs = sorted((g for (k, _), g in grupos.items() if k == 'procedimento'), key=lambda g: -g['valor'])
    linhas = consultas + procs
    total = sum((g['valor'] for g in linhas), quantize_brl(0))
    for g in linhas:
        g['valor'] = quantize_brl(g['valor'])
        g['medio'] = quantize_brl(g['valor'] / g['n']) if g['n'] else quantize_brl(0)
        g['pct'] = (g['valor'] / total * 100) if total else Decimal(0)
    return {'linhas': linhas, 'total': quantize_brl(total), 'n': sum(g['n'] for g in linhas)}
