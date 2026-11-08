import logging
from datetime import datetime, time, timedelta

from django.contrib import messages
from django.db import IntegrityError
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from patients.models import Patient
from tenancy.limits import PlanLimitReached
from tenancy.permissions import Capability, CapabilityRequiredView, can_configure_agenda_of
from tenancy.selectors import scope_to_tenant

from . import publishing, services
from .availability import (
    appointments_on, available_slots, day_grid, month_summary, slot_minutes_for,
    suggested_slot_minutes, type_durations, week_grid,
)
from .forms import (
    ChangePatientForm, DoctorChoiceForm, ExtraHoursForm, LocalHolidayForm, QuickBookingForm,
    RemoveFreeSlotForm, RescheduleAppointmentForm, UnblockSlotForm, ReserveAppointmentForm, ScheduleBlockForm, TypeDurationForm,
    WeeklyScheduleForm,
)
from .models import (
    AppointmentStatus, AppointmentType, AvailabilityRule, Holiday, RecurringBreak,
    ScheduleBlock, ScheduleBlockKind,
)


logger = logging.getLogger(__name__)


class TenantScopedView(CapabilityRequiredView):
    """Agenda: marcar, remarcar, cancelar e receber. Os quatro papéis fazem.

    Agenda é trabalho de recepção antes de ser trabalho clínico, e o PRD dá
    a linha a todos. O que a agenda mostra do paciente é nome, horário e
    tipo — não é prontuário. Por isso a grade não exige capacidade clínica,
    e por isso o modal de um horário marcado não pode ganhar conteúdo
    clínico sem passar a exigi-la.
    """

    required_capability = Capability.SCHEDULE


class ScheduleConfigView(TenantScopedView):
    """Configurar a grade: quem administra a clínica, ou o próprio médico.

    A capacidade abre a tela; quem decide de **qual** médico é a grade em
    questão é `_doctor_to_configure_or_404`, por objeto. Só a capacidade
    deixaria um médico republicar a semana do colega, encerrando regra
    vigente de quem não está olhando — e o PRD escreve "própria agenda"
    para o médico exatamente por isso.
    """

    required_capability = Capability.CONFIGURE_AVAILABILITY


def _parse_date(value, default=None):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return default or timezone.localdate()


def _doctors(request):
    from tenancy.models import Membership, MembershipStatus, Role

    return list(
        Membership.objects.filter(
            tenant_id=request.access_context.tenant_id, status=MembershipStatus.ACTIVE,
            roles__contains=[Role.DOCTOR],
        ).select_related('user', 'user__physician_profile').order_by(
            'user__first_name', 'user__email',
        )
    )


def _own_membership(request):
    from tenancy.models import Membership

    return Membership.objects.filter(id=request.access_context.membership_id).select_related(
        'user', 'tenant',
    ).first()


def _doctor_or_404(request, membership_id):
    from tenancy.models import Membership, MembershipStatus, Role

    membership = Membership.objects.filter(
        id=membership_id, tenant_id=request.access_context.tenant_id,
        status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).select_related('user', 'tenant').first()
    if membership is None:
        raise Http404
    return membership


def _doctor_to_configure_or_404(request, membership_id):
    """O médico cuja grade vai ser alterada, se quem pede puder alterá-la.

    Separado de `_doctor_or_404` de propósito: marcar na agenda de outro
    médico é o trabalho normal da recepção, e **reconfigurar** a grade dele
    não é. As duas coisas partem do mesmo `membership_id` na URL, então uma
    função só para as duas transformaria a primeira permissão na segunda.

    Toda tela de configuração passa por aqui. É o que impede a proteção de
    valer em oito das nove e faltar na nona.
    """
    doctor = _doctor_or_404(request, membership_id)
    if not can_configure_agenda_of(request.access_context, doctor.id):
        raise Http404
    return doctor


def _nav_urls(route, doctor, current, previous, following, today):
    """URLs de navegação da barra da agenda, montadas em Python.

    O template do Django não compõe querystring sem virar ilegível, e a barra
    precisa preservar médico **e** data ao trocar de visão. Montar aqui deixa
    o template só exibindo.
    """
    base = reverse(route)
    physician = f'physician={doctor.id}&' if doctor else ''
    return {
        'date_param': current,
        'prev_url': f'{base}?{physician}date={previous.isoformat()}',
        'next_url': f'{base}?{physician}date={following.isoformat()}',
        'today_url': f'{base}?{physician}date={today.isoformat()}',
    }


def _booking_context(request, doctor, day):
    """Contexto que o modal de marcação (`_booking_modals.html`) exige.

    Existe como função porque o modal é incluído por mais de uma tela — a
    grade da semana e a lista do dia — e cada uma montava o próprio
    contexto. A lista do dia não montava `durations`, e o resultado era um
    `<select>` de tipo de atendimento **sem nenhuma opção**: a tela abria,
    o autocomplete funcionava, e o formulário só era rejeitado no servidor,
    já fora do modal, dizendo que faltava um campo que não dava para
    preencher.

    Quem inclui o modal chama isto. É a única forma de as duas telas não
    voltarem a divergir.
    """
    step = slot_minutes_for(doctor.id, day) or suggested_slot_minutes(doctor.id)
    durations = type_durations(doctor.id)
    return {
        'durations': [
            {'value': value, 'label': label, 'minutes': durations[value],
             'cells': max(1, -(-durations[value] // step)) if step else 1}
            for value, label in AppointmentType.choices
        ],
        'slot_minutes': step,
        'booking_form': QuickBookingForm(),
        'change_form': ChangePatientForm(),
        # Para trocar o tipo de um horário já marcado. O seletor do modal
        # usa `durations`, com os minutos: trocar o tipo muda a duração
        # (ver `services.change_appointment_type`).
        'type_choices': AppointmentType.choices,
        # Quem marca não é necessariamente quem abre horário: o botão
        # "Incluir horário" só aparece para quem poderia configurar esta
        # agenda, e a view confere de novo.
        'pode_incluir_horario': can_configure_agenda_of(request.access_context, doctor.id),
    }


def _selected_doctor(request, doctors):
    """O médico da agenda em foco.

    A ordem importa: o que veio na URL, senão o próprio usuário quando ele é
    médico, senão o primeiro da lista. É o que faz o médico abrir a agenda
    dele e a secretária abrir a de alguém, sem escolher nada nas duas vezes.
    """
    requested = request.GET.get('physician')
    if requested:
        for doctor in doctors:
            if str(doctor.id) == requested:
                return doctor
    own = request.access_context.membership_id
    for doctor in doctors:
        if doctor.id == own:
            return doctor
    return doctors[0] if doctors else None


# --------------------------------------------------------------------------
# Calendário
# --------------------------------------------------------------------------

class AgendaWeekView(TenantScopedView):
    """Grade semanal de um médico, com horário livre e ocupado.

    É a tela principal da agenda. Uma coluna por dia, uma linha por célula da
    grade, e a cor diz o estado: livre dá para clicar e marcar, ocupado mostra
    quem está marcado, bloqueado mostra o motivo.

    Sempre um médico por vez, porque horário livre só quer dizer algo dentro
    da agenda de quem vai atender.
    """

    def get(self, request):
        doctors = _doctors(request)
        doctor = _selected_doctor(request, doctors)
        day = _parse_date(request.GET.get('date'))
        week_start = day - timedelta(days=day.weekday())

        today = timezone.localdate()
        context = {
            'doctors': doctors, 'doctor': doctor, 'view_mode': 'week',
            'week_start': week_start, 'week_end': week_start + timedelta(days=6),
            'today': today,
            'appointment_types': AppointmentType.choices,
            **_nav_urls(
                'scheduling:week', doctor, week_start,
                week_start - timedelta(days=7), week_start + timedelta(days=7),
                today - timedelta(days=today.weekday()),
            ),
        }
        if doctor is None:
            return render(request, 'scheduling/agenda.html', context)

        times, columns = week_grid(doctor.id, week_start)
        context.update({
            'times': times, 'columns': columns,
            **_booking_context(request, doctor, week_start),
            'has_schedule': bool(times),
            'totals': {
                'free': sum(column['free'] for column in columns),
                'busy': sum(column['busy'] for column in columns),
                'total': sum(column['total'] for column in columns),
            },
        })
        return render(request, 'scheduling/agenda.html', context)


class AgendaDayView(TenantScopedView):
    """Um dia em detalhe — a lista que serve no balcão e no celular."""

    def get(self, request):
        doctors = _doctors(request)
        doctor = _selected_doctor(request, doctors)
        day = _parse_date(request.GET.get('date'))
        today = timezone.localdate()
        context = {
            'doctors': doctors, 'doctor': doctor, 'view_mode': 'day', 'day': day,
            'today': today,
            'appointment_types': AppointmentType.choices,
            **_nav_urls(
                'scheduling:day', doctor, day,
                day - timedelta(days=1), day + timedelta(days=1), today,
            ),
        }
        if doctor is None:
            return render(request, 'scheduling/agenda_day.html', context)
        cells = day_grid(doctor.id, day)
        context.update({
            'cells': cells,
            **_booking_context(request, doctor, day),
            'has_schedule': bool(cells),
            'free': sum(1 for cell in cells if cell['status'] == 'free'),
            'busy': sum(1 for cell in cells if cell['status'] == 'busy'),
        })
        return render(request, 'scheduling/agenda_day.html', context)


class AgendaMonthView(TenantScopedView):
    """Mês em blocos, com vagas visíveis e marcação direta."""

    def get(self, request):
        doctors = _doctors(request)
        doctor = _selected_doctor(request, doctors)
        day = _parse_date(request.GET.get('date'))
        month_start = day.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        grid_start = month_start - timedelta(days=month_start.weekday())
        grid_end = next_month + timedelta(days=(7 - next_month.weekday()) % 7)

        today = timezone.localdate()
        days = []
        cursor = grid_start
        while cursor < grid_end:
            days.append(cursor)
            cursor += timedelta(days=1)

        # A contagem de livres é o que responde "onde tem vaga", que é a
        # pergunta de quem está remarcando ao telefone. Uma célula com
        # apenas "2 pacientes" não diz se ainda cabe alguém.
        summary = month_summary(doctor.id, days) if doctor is not None else {}

        weeks, week = [], []
        for day in days:
            counts = summary.get(day, {})
            week.append({
                'date': day,
                'in_month': day.month == month_start.month,
                'is_today': day == today,
                'is_past': day < today,
                'free': counts.get('free', 0),
                'booked': counts.get('booked', 0),
                # **"Fechado" é o dia inteiro bloqueado, e nada menos.**
                #
                # Era `há célula bloqueada e nenhuma livre`, e isso valia
                # enquanto a única coisa que bloqueava célula era exceção
                # de **data** — feriado e férias tomam o dia todo, então
                # "tem bloqueio e não sobrou vaga" e "o dia está fechado"
                # eram a mesma frase.
                #
                # O intervalo semanal (o almoço) quebrou a equivalência:
                # ele bloqueia **uma** célula. Qualquer dia com almoço que
                # ficasse cheio passava a aparecer como fechado — e o
                # ramo que lista os pacientes nem era alcançado, então a
                # agenda do dia sumia da tela. Foi o que aconteceu em
                # 13/10/2026: a secretária terminou de preencher as vagas
                # e o dia virou "fechado", com os oito agendamentos
                # invisíveis.
                #
                # `total > 0` junto porque dia sem grade tem 0 == 0, e
                # sábado não é feriado.
                'blocked': (
                    counts.get('total', 0) > 0
                    and counts.get('blocked', 0) == counts.get('total', 0)
                ),
                'works': counts.get('works', False),
                'cells': counts.get('cells', []),
                # Estas tres vem de `month_summary` e precisam ser
                # repassadas **uma a uma**: este dicionario e montado por
                # chave, nao copiado. Esquecer uma nao quebra nada -- o
                # template le vazio e some com a informacao, calado. Foi o
                # que aconteceu com `encerrado`: o dia vencido continuou
                # dizendo "lotado" porque a chave nunca chegou aqui, e a
                # correcao parecia feita.
                'realizados': counts.get('realizados', 0),
                'past': counts.get('past', 0),
                'encerrado': counts.get('encerrado', False),
            })
            if len(week) == 7:
                weeks.append(week)
                week = []

        totals = {
            'free': sum(row.get('free', 0) for day, row in summary.items()
                        if day.month == month_start.month),
            'booked': sum(row.get('booked', 0) for day, row in summary.items()
                          if day.month == month_start.month),
        }
        booking_context = _booking_context(request, doctor, month_start) if doctor is not None else {}
        return render(request, 'scheduling/agenda_month.html', {
            'doctors': doctors, 'doctor': doctor, 'view_mode': 'month',
            'month_start': month_start, 'weeks': weeks, 'today': today,
            'totals': totals,
            **booking_context,
            **_nav_urls(
                'scheduling:month', doctor, month_start,
                (month_start - timedelta(days=1)).replace(day=1), next_month,
                today.replace(day=1),
            ),
        })


# --------------------------------------------------------------------------
# Configuração da agenda pelo médico
# --------------------------------------------------------------------------

class ScheduleSettingsView(ScheduleConfigView):
    """Tela em que o médico monta a própria grade e publica por um período."""

    def _context(self, request, doctor, **overrides):
        today = timezone.localdate()
        rules = publishing.rules_for(doctor)
        durations = type_durations(doctor.id)
        horizon_end = today + timedelta(days=365)
        summary = publishing.coverage_summary(doctor, today, horizon_end)
        holiday_rows = publishing.holidays_to_review(
            request.access_context, doctor, today, horizon_end,
        )
        context = {
            'doctors': _doctors(request), 'doctor': doctor,
            'rules': rules,
            'weekday_labels': dict(publishing.WEEKDAY_LABELS),
            'durations': [
                {'value': value, 'label': label, 'minutes': durations[value]}
                for value, label in AppointmentType.choices
            ],
            'suggested_slot': suggested_slot_minutes(doctor.id),
            'coverage': summary,
            'blocks': ScheduleBlock.objects.filter(
                physician_membership=doctor, end_at__gte=timezone.now(),
            ).order_by('start_at')[:20],
            # As pausas que ainda valem, para a tela poder mostrá-las ao
            # lado da grade: intervalo configurado e invisível é
            # indistinguível de intervalo que não foi gravado.
            'pausas': RecurringBreak.objects.filter(
                physician_membership=doctor,
            ).filter(publishing.models_ends_on_ok(today)).order_by('weekday', 'local_start'),
            'holidays': holiday_rows,
            'unblocked_holidays': sum(1 for row in holiday_rows if not row['blocked']),
            'holiday_range': {'start': today, 'end': horizon_end},
            'local_holidays': Holiday.objects.filter(
                tenant_id=request.access_context.tenant_id, source='manual',
            ).order_by('date')[:30],
            'schedule_form': WeeklyScheduleForm(initial={
                'slot_minutes': suggested_slot_minutes(doctor.id),
                'starts_on': today,
            }),
            'duration_form': TypeDurationForm(initial_minutes=durations),
            'block_form': ScheduleBlockForm(),
            'holiday_form': LocalHolidayForm(),
            'is_own_agenda': doctor.id == request.access_context.membership_id,
        }
        context.update(overrides)
        return context

    def get(self, request):
        doctors = _doctors(request)
        doctor = _selected_doctor(request, doctors)
        if doctor is None:
            return render(request, 'scheduling/settings.html', {'doctors': [], 'doctor': None})
        # Abrir a configuração de outro médico é o primeiro passo de alterá-la,
        # e a tela já vem com os formulários preenchidos com a grade dele.
        if not can_configure_agenda_of(request.access_context, doctor.id):
            raise Http404
        # Feriados nacionais do horizonte, calculados na abertura da tela: são
        # aritmética, não têm custo, e evitam a tela abrir vazia pedindo que
        # alguém rode um comando antes.
        publishing.ensure_national_holidays(
            request.access_context,
            range(timezone.now().year, timezone.now().year + 3),
        )
        return render(request, 'scheduling/settings.html', self._context(request, doctor))


class ScheduleSettingsSaveView(ScheduleConfigView):
    """Publica a grade semanal do médico."""

    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = WeeklyScheduleForm(request.POST)
        if not form.is_valid():
            return render(
                request, 'scheduling/settings.html',
                ScheduleSettingsView()._context(request, doctor, schedule_form=form),
            )
        dados = dict(form.cleaned_data, pausas=form.pausas_declaradas())
        result = publishing.publish_weekly_schedule(request.access_context, doctor, dados)
        ends_on = form.cleaned_data.get('ends_on')
        until = f'até {ends_on.strftime("%d/%m/%Y")}' if ends_on else 'sem prazo'
        quantas_pausas = len(dados['pausas'])
        messages.success(
            request,
            f'Agenda publicada: {len(result["created"])} dia(s) da semana, {until}.'
            + (f' {result["replaced"]} regra(s) anterior(es) encerrada(s).' if result['replaced'] else '')
            + (f' {quantas_pausas} intervalo(s) por dia.' if quantas_pausas else ''),
        )
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class TypeDurationSaveView(ScheduleConfigView):
    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = TypeDurationForm(request.POST)
        if not form.is_valid():
            return render(
                request, 'scheduling/settings.html',
                ScheduleSettingsView()._context(request, doctor, duration_form=form),
            )
        publishing.set_type_durations(request.access_context, doctor, form.minutes_by_type)
        messages.success(
            request,
            'Durações salvas. A célula da agenda que serve a todas elas é de '
            f'{getattr(form, "suggested_slot", 0)} minutos.',
        )
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class RuleDeleteView(ScheduleConfigView):
    def post(self, request, membership_id, rule_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        rule = get_object_or_404(
            AvailabilityRule, id=rule_id, physician_membership=doctor,
            tenant_id=request.access_context.tenant_id,
        )
        outcome = publishing.remove_rule(request.access_context, doctor, rule)
        messages.success(request, {
            'deleted': 'Horário removido da grade.',
            'closed': 'Horário encerrado a partir de hoje; a agenda passada '
                      'continua como era.',
            # O caso de quem publicou hoje e já tem paciente marcado: a
            # grade de hoje fica, porque apagá-la tiraria do calendário um
            # horário que alguém já reservou.
            'closed_today': 'Horário encerrado a partir de amanhã. Hoje ele '
                            'continua na grade porque já há agendamento — '
                            'cancele ou remarque antes, se quiser o dia livre.',
        }[outcome])
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class BlockCreateView(ScheduleConfigView):
    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = ScheduleBlockForm(request.POST)
        if not form.is_valid():
            return render(
                request, 'scheduling/settings.html',
                ScheduleSettingsView()._context(request, doctor, block_form=form),
            )
        services.create_block(
            request.access_context, doctor, form.cleaned_data['kind'],
            form.cleaned_data['start_at'], form.cleaned_data['end_at'],
            reason=form.cleaned_data.get('reason', ''),
        )
        messages.success(request, 'Registrado na agenda.')
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class ExtraHoursCreateView(ScheduleConfigView):
    """O botão "Incluir horário" ao lado do dia, nas três visões da agenda.

    Mesma permissão de Configurar horários, por objeto: a secretária abre
    horário na agenda de qualquer médico, o médico só na dele. Abrir
    horário é mudar a grade de alguém, não marcar nela.
    """

    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = ExtraHoursForm(request.POST)
        day = _parse_date(request.POST.get('date'))
        if not form.is_valid():
            messages.error(request, _first_error(form))
            return _agenda_redirect(request, doctor, day)
        day = form.cleaned_data['date']
        try:
            block = services.include_extra_hours(
                request.access_context, doctor, day, form.cleaned_data['start_time'],
                form.cleaned_data['cells'], reason=form.cleaned_data.get('reason', ''),
            )
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        if block is None:
            # Só reabriu o que tinha sido excluído: não há extra novo.
            messages.success(
                request,
                f'Horário reaberto em {day.strftime("%d/%m/%Y")} a partir das '
                f'{form.cleaned_data["start_time"].strftime("%H:%M")}.',
            )
            return _agenda_redirect(request, doctor, day)
        inicio = timezone.localtime(block.start_at).strftime('%H:%M')
        fim = timezone.localtime(block.end_at).strftime('%H:%M')
        messages.success(
            request,
            f'Horário incluído em {day.strftime("%d/%m/%Y")}, das {inicio} às {fim}. '
            'Para desfazer, clique no horário e use Excluir este horário.',
        )
        return _agenda_redirect(request, doctor, day)


class FreeSlotRemoveView(ScheduleConfigView):
    """"Excluir este horário", no modal que abre ao clicar num horário livre.

    A permissão é a de Incluir horário, e pela mesma razão: tirar um
    horário é mudar a grade do médico, não marcar nela. A recepção marca
    na agenda de qualquer médico, mas o médico só fecha horário na dele.
    """

    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = RemoveFreeSlotForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Não foi possível identificar o horário. Clique nele de novo.')
            return _agenda_redirect(request, doctor, _parse_date(request.POST.get('date')))
        starts_at = form.cleaned_data['starts_at']
        day = timezone.localtime(starts_at).date()
        try:
            services.remove_free_slot(request.access_context, doctor, starts_at)
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        quando = f'{day.strftime("%d/%m/%Y")} às {timezone.localtime(starts_at).strftime("%H:%M")}'
        messages.success(
            request,
            f'Horário de {quando} excluído da agenda. Para trazê-lo de volta, use Incluir horário.',
        )
        return _agenda_redirect(request, doctor, day)


class FreeSlotBlockView(ScheduleConfigView):
    """"Bloquear este horário", ao lado de Excluir no modal de marcar.

    Mesma permissão de Excluir e de Incluir horário. A diferença para o
    Excluir é a estatística: o bloqueado conta como bloqueado no mês, o
    excluído não conta (ver `services.block_free_slot`).
    """

    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = RemoveFreeSlotForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Não foi possível identificar o horário. Clique nele de novo.')
            return _agenda_redirect(request, doctor, _parse_date(request.POST.get('date')))
        starts_at = form.cleaned_data['starts_at']
        day = timezone.localtime(starts_at).date()
        try:
            services.block_free_slot(request.access_context, doctor, starts_at)
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        quando = f'{day.strftime("%d/%m/%Y")} às {timezone.localtime(starts_at).strftime("%H:%M")}'
        messages.success(
            request,
            f'Horário de {quando} bloqueado. Para liberá-lo, clique nele na agenda.',
        )
        return _agenda_redirect(request, doctor, day)


class SlotUnblockView(ScheduleConfigView):
    """O clique na célula bloqueada pelo modal: desfaz o bloqueio."""

    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = UnblockSlotForm(request.POST)
        day = _parse_date(request.POST.get('date'))
        if not form.is_valid():
            messages.error(request, 'Não foi possível identificar o horário. Clique nele de novo.')
            return _agenda_redirect(request, doctor, day)
        try:
            inicio = services.unblock_slot(
                request.access_context, doctor, form.cleaned_data['block_id'],
            )
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        local = timezone.localtime(inicio)
        messages.success(
            request,
            f'Horário de {local.strftime("%d/%m/%Y")} às {local.strftime("%H:%M")} liberado.',
        )
        return _agenda_redirect(request, doctor, local.date())


class BlockDeleteView(ScheduleConfigView):
    def post(self, request, membership_id, block_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        block = get_object_or_404(
            ScheduleBlock, id=block_id, physician_membership=doctor,
            tenant_id=request.access_context.tenant_id,
        )
        block.delete()
        messages.success(request, 'Removido da agenda.')
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class HolidayReviewView(ScheduleConfigView):
    """Aplica as decisões de feriado: o que bloquear e o que atender.

    Trabalha como um conjunto de interruptores sobre o período: o que vem
    marcado fica bloqueado, o que não vem tem o bloqueio de feriado removido.
    Desmarcar quer dizer "vou atender nesse dia".
    """

    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        start = _parse_date(request.POST.get('range_start'))
        end = _parse_date(request.POST.get('range_end'), default=start + timedelta(days=365))
        chosen = []
        reasons = {}
        for raw in request.POST.getlist('block_dates'):
            day = _parse_date(raw, default=None)
            if day is None:
                continue
            chosen.append(day)
            reasons[day] = request.POST.get(f'name_{raw}', 'Feriado')
        result = publishing.apply_holiday_blocks(
            request.access_context, doctor, chosen, start, end, reasons=reasons,
        )
        text = f'{result["blocked"]} feriado(s) bloqueado(s)'
        if result['released']:
            text += f', {result["released"]} liberado(s)'
        if result['appointments']:
            text += (
                f'. Atenção: {len(result["appointments"])} paciente(s) já marcado(s) em dia '
                'bloqueado — remarque pela agenda.'
            )
        messages.success(request, text + '.')
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class LocalHolidayCreateView(ScheduleConfigView):
    def post(self, request, membership_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        form = LocalHolidayForm(request.POST)
        if not form.is_valid():
            return render(
                request, 'scheduling/settings.html',
                ScheduleSettingsView()._context(request, doctor, holiday_form=form),
            )
        holiday = Holiday(
            tenant_id=request.access_context.tenant_id,
            date=form.cleaned_data['date'], name=form.cleaned_data['name'],
            scope=form.cleaned_data['scope'],
            state=(form.cleaned_data.get('state') or '').upper(),
            city=form.cleaned_data.get('city') or '',
            recurring=form.cleaned_data.get('recurring') or False,
            source='manual',
        )
        holiday.full_clean()
        holiday.save()
        messages.success(request, f'{holiday.name} cadastrado como feriado local.')
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class LocalHolidayDeleteView(ScheduleConfigView):
    def post(self, request, membership_id, holiday_id):
        doctor = _doctor_to_configure_or_404(request, membership_id)
        holiday = get_object_or_404(
            Holiday, id=holiday_id, tenant_id=request.access_context.tenant_id, source='manual',
        )
        name = holiday.name
        holiday.delete()
        messages.success(request, f'{name} removido dos feriados locais.')
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


# --------------------------------------------------------------------------
# Reservas
# --------------------------------------------------------------------------

def _first_error(form):
    """A primeira falha do formulário, dizendo **qual** campo falhou.

    O modal da agenda envia e a resposta é um redirect para a grade, então o
    erro aparece como aviso da página — longe do campo que o causou. Sem o
    nome do campo, "Este campo é obrigatório." obriga a adivinhar qual, e a
    janela onde o valor seria digitado já fechou. O rótulo é o que liga o
    aviso de volta ao campo.
    """
    for name, errors in form.errors.items():
        if not errors:
            continue
        if name == '__all__':
            return errors[0]
        label = form.fields[name].label or name
        return f'{label}: {errors[0]}'
    return 'Não foi possível concluir: confira os dados informados.'


def _agenda_redirect(request, doctor, day, anchor=''):
    base = request.POST.get('return_to') or reverse('scheduling:week')
    url = f'{base}?physician={doctor.id}&date={day.isoformat()}'
    return redirect(f'{url}#{anchor}' if anchor else url)


class QuickBookingView(TenantScopedView):
    """Marca no horário clicado da grade.

    Aceita paciente já cadastrado ou faz o pré-cadastro com nome e telefone —
    que é o que a secretária tem na ligação. O fim do atendimento vem da
    duração do tipo escolhido, não digitado.
    """

    def post(self, request, membership_id):
        doctor = _doctor_or_404(request, membership_id)
        form = QuickBookingForm(request.POST)
        if not form.is_valid():
            messages.error(request, _first_error(form))
            day = _parse_date(request.POST.get('date'))
            return _agenda_redirect(request, doctor, day)

        starts_at = form.cleaned_data['starts_at']
        day = timezone.localtime(starts_at).date()

        # Puxado da lista de espera: caminho próprio, para o de sempre (logo
        # abaixo) continuar exatamente como era.
        if form.cleaned_data.get('espera_id'):
            return self._puxar_da_espera(request, doctor, form, starts_at, day)

        if form.cleaned_data.get('patient_id'):
            patient = scope_to_tenant(
                Patient.objects.all(), request.access_context,
            ).filter(id=form.cleaned_data['patient_id']).first()
            if patient is None:
                messages.error(request, 'Paciente não encontrado nesta organização.')
                return _agenda_redirect(request, doctor, day)
        else:
            # Pré-cadastro ao telefone também ocupa vaga do plano. A
            # mensagem vem pronta de `PlanLimitReached` — escrevê-la aqui a
            # faria divergir da do cadastro completo no primeiro ajuste.
            try:
                patient = services.quick_register_patient(
                    request.access_context, form.cleaned_data['new_name'],
                    form.cleaned_data.get('new_phone', ''),
                    note=form.cleaned_data.get('note', ''),
                    email=form.cleaned_data.get('new_email', ''),
                    accepts_messages=form.cleaned_data.get('contact_accepts_messages', True),
                )
            except PlanLimitReached as limite:
                messages.error(request, limite.message())
                return _agenda_redirect(request, doctor, day)

        try:
            appointment = services.reserve_from_grid(
                request.access_context, patient, doctor, starts_at,
                form.cleaned_data['appointment_type'],
                is_overbook=form.cleaned_data.get('is_overbook') or False,
                override_reason=form.cleaned_data.get('override_reason', ''),
                override_by=_own_membership(request),
            )
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        except IntegrityError:
            # So o choque de horario cai aqui. `ExclusionConstraint`
            # (`scheduling_appointment_no_overlap`) e o que recusa duas
            # reservas sobrepostas quando duas pessoas marcam ao mesmo
            # tempo, e e a unica falha que justifica esta mensagem.
            #
            # Era `except Exception`, e a mensagem era esta mesma: banco
            # fora do ar, erro de programacao e entrada estranha viravam
            # "o horario acabou de ser ocupado". A secretaria tentava de
            # novo num horario que estava livre, indefinidamente, e o
            # defeito nao aparecia em lugar nenhum.
            messages.error(
                request,
                'Este horário acabou de ser ocupado por outra reserva. Escolha outro.',
            )
            return _agenda_redirect(request, doctor, day)

        local = timezone.localtime(appointment.starts_at)
        stage = ''
        if patient.registration_stage == 'preliminary':
            stage = ' Pré-cadastro: a ficha completa é pedida no check-in.'
        # Marcado pela busca, e não puxado da espera: a espera não se
        # encerra sozinha (o horário pode ser outro assunto), mas a
        # secretária fica sabendo que o nome continua lá.
        from .espera import esperando
        aviso_espera = ''
        if esperando(request.access_context.tenant_id, patient.id):
            aviso_espera = (' Este paciente continua na lista de espera — '
                            'retire-o de lá se este horário resolve.')
        messages.success(
            request,
            f'{patient.full_name} marcado para {local.strftime("%d/%m/%Y às %H:%M")} '
            f'({appointment.get_type_display()}).{stage}{aviso_espera}',
        )
        return _agenda_redirect(request, doctor, day)

    def _puxar_da_espera(self, request, doctor, form, starts_at, day):
        """Marca o paciente da lista de espera e encerra a espera, numa transação.

        A espera é relida e travada **dentro** da mesma transação da
        consulta: se o horário for recusado, ela continua aguardando; se
        outra pessoa puxou o mesmo nome um instante antes, esta é recusada
        sem marcar um segundo horário.
        """
        from django.db import transaction

        from . import espera

        ctx = request.access_context
        ator = _own_membership(request)
        try:
            with transaction.atomic():
                entrada = espera.para_puxar(ctx, form.cleaned_data['espera_id'], doctor)
                escolhido = form.cleaned_data.get('patient_id')
                if escolhido and escolhido != entrada.patient_id:
                    raise espera.EsperaError(
                        'O paciente escolhido não é o da lista de espera. Abra o horário de novo.'
                    )
                patient = entrada.patient
                appointment = services.reserve_from_grid(
                    ctx, patient, doctor, starts_at,
                    form.cleaned_data['appointment_type'],
                    is_overbook=form.cleaned_data.get('is_overbook') or False,
                    override_reason=form.cleaned_data.get('override_reason', ''),
                    override_by=ator,
                )
                espera.marcar_agendada(ctx, entrada, appointment, ator=ator)
        except (espera.EsperaError, services.SchedulingError) as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        except IntegrityError:
            messages.error(
                request,
                'Este horário acabou de ser ocupado por outra reserva. Escolha outro.',
            )
            return _agenda_redirect(request, doctor, day)

        local = timezone.localtime(appointment.starts_at)
        messages.success(
            request,
            f'{patient.full_name} marcado para {local.strftime("%d/%m/%Y às %H:%M")} '
            f'({appointment.get_type_display()}) e retirado da lista de espera.',
        )
        return _agenda_redirect(request, doctor, day)


class AppointmentActionView(TenantScopedView):
    def post(self, request, appointment_id, action):
        appointment = get_object_or_404(
            scope_to_tenant(
                __import__('scheduling.models', fromlist=['Appointment']).Appointment.objects.all(),
                request.access_context,
            ), id=appointment_id,
        )
        day = timezone.localtime(appointment.starts_at).date()
        doctor = appointment.physician_membership
        try:
            if action == 'confirm':
                services.transition_appointment(appointment, AppointmentStatus.CONFIRMED, request.user.id)
                messages.success(request, 'Presença confirmada com o paciente.')
            elif action == 'unconfirm':
                services.transition_appointment(appointment, AppointmentStatus.SCHEDULED, request.user.id)
                messages.success(request, 'Confirmação desfeita: o horário voltou a "Agendado".')
            elif action == 'check-in':
                services.check_in(appointment, request.user.id)
                # Check-in é o momento em que o paciente está na recepção: é
                # quando o pré-cadastro tem de virar cadastro completo, então
                # a tela vai direto para a ficha.
                if appointment.patient.registration_stage == 'preliminary':
                    messages.info(
                        request,
                        f'{appointment.patient.full_name} chegou. Complete o cadastro: '
                        'o pré-cadastro só tem nome e telefone.',
                    )
                    return redirect('patients:update', patient_id=appointment.patient_id)
                messages.success(request, f'{appointment.patient.full_name} chegou.')
                return redirect('patients:detail', patient_id=appointment.patient_id)
            elif action == 'start':
                services.start_appointment(appointment, request.user.id)
                messages.success(request, 'Atendimento iniciado.')
            elif action == 'complete':
                services.complete_appointment(appointment, request.user.id)
                messages.success(request, 'Atendimento concluído.')
            elif action == 'no-show':
                services.mark_no_show(appointment, request.user.id)
                messages.success(request, 'Falta registrada.')
            elif action == 'cancel':
                from django.db import transaction

                from . import espera

                with transaction.atomic():
                    services.cancel_appointment(
                        appointment, request.user.id, reason=request.POST.get('reason', ''),
                    )
                    # Quem cancela decide se o paciente volta à lista de
                    # espera (revisão de 2026-11-02, W6). A consulta que veio
                    # da lista devolve a espera ao topo; a outra entra no fim.
                    volta = None
                    if request.POST.get('por_na_espera') == '1':
                        try:
                            _entrada, volta = espera.por_na_lista_ao_cancelar(
                                request.access_context, appointment,
                            )
                        except espera.EsperaError as exc:
                            messages.warning(request, f'Horário liberado, mas: {exc}')
                            return _agenda_redirect(request, doctor, day)
                if volta == 'devolvida':
                    messages.success(request, 'Horário liberado. O paciente voltou ao topo da lista de espera.')
                elif volta == 'incluida':
                    messages.success(request, 'Horário liberado. O paciente entrou no fim da lista de espera.')
                else:
                    messages.success(request, 'Horário liberado.')
            else:
                raise Http404
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
        return _agenda_redirect(request, doctor, day)


class SendConfirmationView(TenantScopedView):
    """Enfileira a confirmação do horário por SMS ou e-mail.

    Reenvio é permitido: mensagem não chega, e a secretária precisa poder
    mandar de novo. Cada envio fica registrado como uma entrega própria.

    **Quem envia é o worker, e não esta view.** Ela chamava
    `send_appointment_confirmation` dentro da requisição, e isso
    funcionava na clínica que informou a própria chave do SMSDEV — essa
    fica cifrada no banco, e o processo `app` sabe decifrá-la. Na clínica
    que depende da chave **da instalação** não funcionava, porque o `app`
    não recebe esse secret: ele é do worker, por desenho (§2). O SMS era
    recusado com `SmsChannelDisabled` e nada saía.

    Com uma clínica só, e ela com chave própria, o defeito não tinha como
    aparecer. Apareceu no dia em que a segunda clínica — plano Completo,
    sem chave própria — tentou enviar.

    É o mesmo par de causa e sintoma que `deliver_document_task` já havia
    corrigido na entrega de documento; a confirmação da agenda era a
    última entrega que ainda saía de dentro da requisição.
    """

    def post(self, request, appointment_id, channel):
        from communications.models import DeliveryChannel
        from communications.services import confirmation_contacts
        from communications.tasks import send_confirmation_task

        from .models import Appointment

        if channel not in (DeliveryChannel.SMS, DeliveryChannel.EMAIL):
            raise Http404
        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context), id=appointment_id,
        )
        day = timezone.localtime(appointment.starts_at).date()
        doctor = appointment.physician_membership
        label = 'SMS' if channel == DeliveryChannel.SMS else 'E-mail'

        # A falta de contato é conferida aqui, e não só no worker, pelo
        # mesmo motivo do reenvio de documento: é o único desfecho que a
        # pessoa na tela pode resolver agora, e descobri-lo por uma linha
        # numa lista minutos depois é descobrir tarde.
        contatos = [c for c in confirmation_contacts(appointment, channel) if c is not None]
        if not contatos:
            campo = 'e-mail' if channel == DeliveryChannel.EMAIL else 'telefone'
            messages.error(
                request,
                f'Nenhum contato deste paciente tem {campo} cadastrado. '
                'Inclua o contato na ficha do paciente.',
            )
            return _agenda_redirect(request, doctor, day)

        destino = (
            contatos[0].phone if channel == DeliveryChannel.SMS else contatos[0].email
        )
        send_confirmation_task.delay(
            str(appointment.id), channel, request.user.id, str(contatos[0].id),
        )
        messages.success(
            request,
            f'{label} de confirmação a caminho de {destino}. O envio sai pelo worker; '
            'o resultado aparece na lista de entregas do agendamento em instantes.',
        )
        return _agenda_redirect(request, doctor, day)


class WhatsAppReminderView(TenantScopedView):
    """Abre a conversa com o paciente no WhatsApp da clínica (1.39).

    Monta o texto da clínica com os dados do horário **na hora do clique** e
    redireciona para o `wa.me`; quem envia é a recepção, do número da clínica
    (ver `communications/whatsapp.py`). Abre em aba própria, e a agenda fica
    onde estava.

    `GET`, e não `POST`, por necessidade: a CSP tem `form-action 'self'`, e o
    navegador recusa o salto para outro domínio no fim de um envio de
    formulário (a mesma razão de o SNCR abrir o Gov.br por uma página). O
    `GET` não muda nada no horário — só registra na trilha que a conversa foi
    **aberta**, sem telefone nem texto. Se foi enviada, só o WhatsApp sabe.

    A rota existe, em vez de o link ir pronto na grade, para a semana não
    montar uma mensagem por horário a cada abertura da agenda.
    """

    def get(self, request, appointment_id):
        from audit.services import record_audit_event
        from communications import whatsapp

        from .models import Appointment, AppointmentStatus

        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context)
            .select_related('patient', 'tenant', 'physician_membership__user'),
            id=appointment_id,
        )
        day = timezone.localtime(appointment.starts_at).date()
        doctor = appointment.physician_membership
        if appointment.status == AppointmentStatus.CANCELLED:
            messages.error(request, 'Este horário foi cancelado: não há consulta para lembrar.')
            return _agenda_redirect(request, doctor, day)
        try:
            endereco = whatsapp.link(appointment)
        except whatsapp.SemTelefone:
            messages.error(
                request,
                'Nenhum contato deste paciente tem um celular que sirva para o WhatsApp '
                '(com DDD). Corrija o telefone na ficha do paciente.',
            )
            return _agenda_redirect(request, doctor, day)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'scheduling.whatsapp_aberto',
            object_type='appointment', object_id=appointment.id, outcome='success',
        )
        return HttpResponseRedirect(endereco)


class ChangePatientView(TenantScopedView):
    def post(self, request, appointment_id):
        from .models import Appointment

        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context), id=appointment_id,
        )
        day = timezone.localtime(appointment.starts_at).date()
        doctor = appointment.physician_membership
        form = ChangePatientForm(request.POST)
        if not form.is_valid():
            messages.error(request, _first_error(form))
            return _agenda_redirect(request, doctor, day)
        patient = scope_to_tenant(Patient.objects.all(), request.access_context).filter(
            id=form.cleaned_data['patient_id'],
        ).first()
        if patient is None:
            messages.error(request, 'Paciente não encontrado nesta organização.')
            return _agenda_redirect(request, doctor, day)
        from django.db import transaction

        from . import espera

        try:
            with transaction.atomic():
                trocado = services.change_appointment_patient(
                    request.access_context, appointment, patient,
                    form.cleaned_data['reason'], request.user.id,
                )
                # O horário que veio da lista de espera deixou de ser do
                # paciente que esperava: ele volta ao topo (W6).
                devolvida = espera.devolver_a_lista(request.access_context, trocado)
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        aviso = ''
        if devolvida is not None:
            aviso += f' {devolvida.patient.full_name}, que veio da lista de espera, voltou ao topo dela.'
        if getattr(trocado, 'forma_de_cobranca_desfeita', False):
            aviso = ' A forma de cobrança escolhida era do paciente anterior e foi desfeita; escolha de novo se precisar.'
        messages.success(request, f'Horário agora é de {patient.full_name}.{aviso}')
        return _agenda_redirect(request, doctor, day)


class ChangeAppointmentTypeView(TenantScopedView):
    """Trocar o tipo do horário marcado, a partir do modal da agenda."""

    def post(self, request, appointment_id):
        from .models import Appointment

        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context), id=appointment_id,
        )
        day = timezone.localtime(appointment.starts_at).date()
        doctor = appointment.physician_membership
        try:
            services.change_appointment_type(
                request.access_context, appointment,
                request.POST.get('appointment_type', ''), request.user.id,
            )
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        appointment.refresh_from_db()
        inicio = timezone.localtime(appointment.starts_at).strftime('%H:%M')
        fim = timezone.localtime(appointment.ends_at).strftime('%H:%M')
        messages.success(
            request,
            f'Tipo alterado para {appointment.get_type_display()}: das {inicio} às {fim}.',
        )
        return _agenda_redirect(request, doctor, day)


class AppointmentBillingView(TenantScopedView):
    """Particular ou convênio neste horário (1.30), a partir do modal da agenda.

    `GET` devolve as coberturas do paciente em JSON para o painel — só
    leitura, nada muda. `POST` grava. A recusa vem de
    `services.set_billing_mode`: só antes da chegada, só cobertura do
    próprio paciente.
    """

    def _appointment(self, request, appointment_id):
        from .models import Appointment

        return get_object_or_404(
            scope_to_tenant(Appointment.objects.select_related('patient'), request.access_context),
            id=appointment_id,
        )

    def get(self, request, appointment_id):
        appointment = self._appointment(request, appointment_id)
        return JsonResponse({
            'modo': appointment.billing_mode,
            'cobertura': str(appointment.coverage_id or ''),
            'editavel': appointment.status in ('scheduled', 'confirmed'),
            'opcoes': services.billing_options(appointment),
        })

    def post(self, request, appointment_id):
        appointment = self._appointment(request, appointment_id)
        day = timezone.localtime(appointment.starts_at).date()
        doctor = appointment.physician_membership
        escolha = request.POST.get('billing', '')
        cobertura = None
        if escolha.startswith('coverage:'):
            import uuid

            modo = 'insurance'
            try:
                cobertura = uuid.UUID(escolha.split(':', 1)[1])
            except ValueError:
                messages.error(request, 'Convênio não encontrado para este paciente.')
                return _agenda_redirect(request, doctor, day)
        else:
            modo = escolha
        try:
            services.set_billing_mode(
                request.access_context, appointment, modo, cobertura, request.user.id,
            )
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        rotulo = {'private': 'particular', 'insurance': 'convênio'}.get(modo, 'não informada')
        messages.success(request, f'Forma de cobrança deste horário: {rotulo}.')
        return _agenda_redirect(request, doctor, day)


class RescheduleAppointmentView(TenantScopedView):
    """Remarcar olhando o mês, não digitando data e hora.

    Quem remarca está ao telefone com o paciente e precisa **ver** onde há
    vaga. O formulário anterior pedia dois `datetime` digitados: para saber
    se 14h de quinta estava livre era preciso sair da tela, olhar a agenda e
    voltar. Aqui o mês mostra a contagem de livres por dia, clicar num dia
    lista os horários que **cabem** nesta consulta, e clicar num horário
    remarca.

    A duração é a da consulta que está sendo remarcada e não é editável:
    remarcar é mudar o quando, não o quanto.
    """

    def _appointment(self, request, appointment_id):
        from .models import Appointment

        return get_object_or_404(
            scope_to_tenant(
                Appointment.objects.select_related(
                    'patient', 'physician_membership__user',
                    'physician_membership__user__physician_profile',
                ),
                request.access_context,
            ),
            id=appointment_id,
        )

    def _context(self, request, appointment, **overrides):
        current = timezone.localtime(appointment.starts_at)
        # A lista oferece onde cabe a duração do tipo, que é a que o POST grava.
        minutes = services.duration_for(appointment.physician_membership_id, appointment.type)

        month_ref = _parse_date(request.GET.get('month'), default=current.date().replace(day=1))
        month_start = month_ref.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        grid_start = month_start - timedelta(days=month_start.weekday())
        grid_end = next_month + timedelta(days=(7 - next_month.weekday()) % 7)

        days = []
        cursor = grid_start
        while cursor < grid_end:
            days.append(cursor)
            cursor += timedelta(days=1)

        doctor_id = appointment.physician_membership_id
        summary = month_summary(doctor_id, days)
        today = timezone.localdate()

        selected = None
        if request.GET.get('date'):
            selected = _parse_date(request.GET.get('date'))

        weeks, week = [], []
        for day in days:
            counts = summary.get(day, {})
            week.append({
                'date': day,
                'in_month': day.month == month_start.month,
                'is_today': day == today,
                'is_past': day < today,
                'is_current': day == current.date(),
                'is_selected': day == selected,
                'free': counts.get('free', 0),
                'booked': counts.get('booked', 0),
                'works': counts.get('works', False),
            })
            if len(week) == 7:
                weeks.append(week)
                week = []

        slots = []
        if selected is not None:
            slots = [
                {'start': start, 'end': end}
                for start, end in available_slots(doctor_id, selected, minutes=minutes)
            ]

        base = reverse('scheduling:reschedule', args=[appointment.id])
        previous_month = (month_start - timedelta(days=1)).replace(day=1)
        context = {
            'appointment': appointment,
            'current': current,
            'minutes': minutes,
            'month_start': month_start,
            'weeks': weeks,
            'today': today,
            'selected_day': selected,
            'slots': slots,
            'prev_month_url': f'{base}?month={previous_month.isoformat()}',
            'next_month_url': f'{base}?month={next_month.isoformat()}',
            'this_month_url': f'{base}?month={today.replace(day=1).isoformat()}',
            'day_url_base': base,
            'form': RescheduleAppointmentForm(initial={
                'starts_at': appointment.starts_at, 'ends_at': appointment.ends_at,
                'row_version': appointment.row_version,
            }),
        }
        context.update(overrides)
        return context

    def get(self, request, appointment_id):
        appointment = self._appointment(request, appointment_id)
        return render(request, 'scheduling/reschedule.html', self._context(request, appointment))

    def post(self, request, appointment_id):
        from django.forms.fields import DateTimeField

        from .availability import fits

        appointment = self._appointment(request, appointment_id)
        doctor = appointment.physician_membership
        original_day = timezone.localtime(appointment.starts_at).date()
        minutes = services.duration_for(doctor.id, appointment.type)

        # O clique num horário da lista manda apenas o início; o fim vem da
        # duração **do tipo**, como em toda outra porta. Até a 1.14.2 vinha
        # da duração que a consulta tinha, e com isso uma consulta gravada
        # com a duração errada (um retorno de 80 min, do tempo em que trocar
        # o tipo não mexia no fim) carregava o erro para cada remarcação.
        raw_start = request.POST.get('starts_at')
        raw_end = request.POST.get('ends_at')
        row_version = request.POST.get('row_version') or appointment.row_version
        if raw_start and not raw_end:
            parsed = DateTimeField(required=False).clean(raw_start)
            if parsed is not None:
                raw_end = (parsed + timedelta(minutes=minutes)).isoformat()

        form = RescheduleAppointmentForm({
            'starts_at': raw_start, 'ends_at': raw_end, 'row_version': row_version,
        })
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return render(
                request, 'scheduling/reschedule.html', self._context(request, appointment),
            )

        if int(form.cleaned_data['row_version']) != appointment.row_version:
            messages.error(
                request,
                'Este horário mudou desde que você abriu a tela. Recarregue antes de '
                'remarcar — outra pessoa pode ter remarcado ou cancelado.',
            )
            return redirect('scheduling:reschedule', appointment_id=appointment.id)

        new_start = form.cleaned_data['starts_at']
        new_end = form.cleaned_data['ends_at']
        day_param = timezone.localtime(new_start).date().isoformat()
        back = f'{reverse("scheduling:reschedule", args=[appointment.id])}?date={day_param}'

        ok, reason = fits(doctor.id, new_start, new_end, ignorar=appointment.id)
        if not ok:
            messages.error(request, reason)
            return redirect(back)
        try:
            appointment = services.reschedule_appointment(
                request.access_context, appointment, new_start, new_end, request.user.id,
            )
        except services.SchedulingError as exc:
            # Cancelada ou mudada por outra pessoa enquanto esta tela
            # estava aberta: a recusa diz o porquê, em vez de "o erro foi
            # registrado", que é para defeito e não para regra.
            messages.error(request, str(exc))
            return redirect(back)
        except IntegrityError:
            # Ver o comentario da criacao de reserva: so o choque de
            # horario cai aqui.
            messages.error(
                request, 'Este horário acabou de ser ocupado por outra reserva. Escolha outro.',
            )
            return redirect(back)
        except Exception:
            # Qualquer outra coisa e defeito, e defeito se registra. A
            # mensagem nao inventa causa: diz que nao deu e que alguem foi
            # avisado, que e a verdade.
            logger.exception('Falha ao remarcar a reserva %s', appointment.id)
            messages.error(
                request,
                'Não foi possível remarcar agora. O erro foi registrado — '
                'tente de novo em instantes.',
            )
            return redirect(back)

        local = timezone.localtime(appointment.starts_at)
        messages.success(
            request,
            f'{appointment.patient.full_name} remarcado de '
            f'{original_day.strftime("%d/%m")} para {local.strftime("%d/%m/%Y às %H:%M")}.',
        )
        if getattr(appointment, 'forma_de_cobranca_desfeita', False):
            messages.warning(
                request,
                'O convênio escolhido não está vigente na nova data, e a escolha foi desfeita. '
                'Confira a forma de cobrança no horário antes da chegada do paciente.',
            )
        return _agenda_redirect(request, doctor, local.date())


class ReserveAppointmentView(TenantScopedView):
    """Reserva pelo formulário completo, para quando já se sabe o horário."""

    def get(self, request):
        patient_id = request.GET.get('patient_id')
        form = ReserveAppointmentForm(
            tenant_id=request.access_context.tenant_id, initial={'patient_id': patient_id},
        )
        return render(request, 'scheduling/reserve.html', {'form': form})

    def post(self, request):
        form = ReserveAppointmentForm(request.POST, tenant_id=request.access_context.tenant_id)
        if not form.is_valid():
            return render(request, 'scheduling/reserve.html', {'form': form})
        patient = get_object_or_404(
            scope_to_tenant(Patient.objects.all(), request.access_context),
            id=form.cleaned_data['patient_id'],
        )
        try:
            appointment = services.reserve_from_grid(
                request.access_context, patient, form.cleaned_data['physician_membership'],
                form.cleaned_data['starts_at'], form.cleaned_data['appointment_type'],
                is_overbook=form.cleaned_data['is_overbook'],
                override_reason=form.cleaned_data['override_reason'],
                override_by=_own_membership(request),
            )
        except Exception as exc:
            form.add_error(None, str(exc))
            return render(request, 'scheduling/reserve.html', {'form': form})
        day = timezone.localtime(appointment.starts_at).date()
        messages.success(request, f'{patient.full_name} marcado.')
        return redirect(
            f'{reverse("scheduling:week")}?physician={appointment.physician_membership_id}'
            f'&date={day.isoformat()}'
        )


class AvailabilitySlotsView(TenantScopedView):
    """Horários livres de um médico num dia, em JSON.

    Recebe o tipo de atendimento porque a resposta depende dele: uma
    primeira consulta de 80 minutos só cabe onde há duas células livres
    seguidas.
    """

    def get(self, request):
        physician_id = request.GET.get('physician_membership_id')
        day = _parse_date(request.GET.get('date'))
        appointment_type = request.GET.get('type')
        if not physician_id:
            return JsonResponse({'slots': []})
        doctor = _doctor_or_404(request, physician_id)
        minutes = None
        if appointment_type in AppointmentType.values:
            minutes = type_durations(doctor.id)[appointment_type]
        slots = available_slots(doctor.id, day, minutes=minutes)
        return JsonResponse({'slots': [
            {'starts_at': start.isoformat(), 'ends_at': end.isoformat(),
             'label': timezone.localtime(start).strftime('%H:%M')}
            for start, end in slots
        ]})


class SecretaryDeskView(TenantScopedView):
    """Balcão do dia: quem chega, quem chegou, o que está pendente.

    Complementa a grade em vez de repetir: aqui a ordem é a do dia, com os
    botões de chegada e confirmação à mão, e o pré-cadastro sinalizado — é o
    que a recepção precisa ver sem escolher médico nem semana.
    """

    def get(self, request):
        day = _parse_date(request.GET.get('date'))
        from .models import Appointment

        appointments = list(
            scope_to_tenant(Appointment.objects.all(), request.access_context)
            .filter(starts_at__date=day)
            .exclude(status=AppointmentStatus.CANCELLED)
            .select_related(
                'patient', 'physician_membership__user',
                # O nome mostrado cai no perfil profissional quando a conta
                # nao tem nome (`accounts.User.get_full_name`). Sem isto, a
                # grade do dia faria uma consulta por agendamento.
                'physician_membership__user__physician_profile',
            )
            # O telefone ao lado do nome e o botão do WhatsApp leem os
            # contatos de cada paciente; sem isto, uma consulta por linha.
            .prefetch_related('patient__contacts')
            .order_by('starts_at')
        )
        pending = [
            appointment for appointment in appointments
            if appointment.patient.registration_stage == 'preliminary'
        ]
        return render(request, 'scheduling/desk.html', {
            'appointments': appointments, 'day': day, 'today': timezone.localdate(),
            'prev_day': day - timedelta(days=1), 'next_day': day + timedelta(days=1),
            'doctors': _doctors(request),
            'pending_registration': pending,
            'counts': {
                'total': len(appointments),
                'arrived': sum(1 for a in appointments if a.status in (
                    AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_PROGRESS,
                    AppointmentStatus.COMPLETED,
                )),
                'confirmed': sum(1 for a in appointments if a.status == AppointmentStatus.CONFIRMED),
            },
        })


class MonthStatisticsView(TenantScopedView):
    """Estatísticas do mês, para os quatro papéis.

    `SCHEDULE`, e não capacidade clínica nem gerencial: a tela mostra
    **contagens** — quantas primeiras consultas, quantos horários sobraram
    — e nenhum nome de paciente. É informação de operação do consultório, e
    quem opera o consultório é a recepção tanto quanto o médico.

    Os indicadores de `reporting` continuam exigindo
    `MANAGERIAL_DASHBOARD`: aqueles cruzam faturamento, e dinheiro é outra
    conversa.
    """

    def get(self, request):
        from .estatisticas import do_mes, limites_do_mes

        doctors = _doctors(request)
        medico = request.GET.get('physician') or ''
        if medico not in {str(d.id) for d in doctors}:
            medico = ''

        hoje = timezone.localdate()
        try:
            ano = int(request.GET.get('ano') or hoje.year)
            mes = int(request.GET.get('mes') or hoje.month)
            # `date()` recusa mês fora de 1..12; o ano fica numa faixa que
            # não produz calendário absurdo nem varredura de grade enorme.
            if not 1 <= mes <= 12 or not 2000 <= ano <= 2100:
                raise ValueError
        except (TypeError, ValueError):
            ano, mes = hoje.year, hoje.month

        dados = do_mes(
            request.access_context.tenant_id, ano, mes, doctors,
            physician_membership_id=medico or None,
        )
        _, _, (ano_ant, mes_ant) = limites_do_mes(ano, mes)
        proximo = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        return render(request, 'scheduling/estatisticas.html', {
            **dados,
            'doctors': doctors,
            'physician_id': medico,
            'ano': ano, 'mes': mes,
            'anterior': {'ano': ano_ant, 'mes': mes_ant},
            'proximo': {'ano': proximo[0], 'mes': proximo[1]},
            'hoje': hoje,
        })


class AttendanceStatementView(TenantScopedView):
    """Declaração de comparecimento, emitida no balcão e impressa na hora.

    **A capacidade é a da agenda, e isso não é lapso.** Declaração de
    comparecimento não é atestado: o atestado afirma incapacidade para o
    trabalho, que é juízo clínico; a declaração afirma que a pessoa esteve
    aqui das 14h às 16h30, que é fato administrativo de quem registrou a
    chegada e a saída. Ver `scheduling/declaracao.py`.

    `GET` mostra a folha com os horários do agendamento, para conferir e
    corrigir. `POST` é o "emitir": grava o ato na trilha e devolve a mesma
    folha pedindo impressão. A separação existe para que ajustar o horário
    três vezes não deixe três emissões registradas, e para que atualizar a
    página não emita de novo.

    Nada é guardado como arquivo — foi o que se pediu, e é o certo: o papel
    se imprime e acaba. O que fica é o registro de que saiu, e com quais
    horários.
    """

    def get(self, request, appointment_id):
        return self._folha(request, appointment_id, imprimir=False)

    def post(self, request, appointment_id):
        return self._folha(request, appointment_id, imprimir=True)

    def _folha(self, request, appointment_id, imprimir):
        from tenancy.models import ClinicProfile

        from .declaracao import horarios, registrar_emissao
        from .models import Appointment

        dados_brutos = request.POST if request.method == 'POST' else request.GET
        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context)
            .select_related('patient', 'physician_membership__user',
                            'physician_membership__user__physician_profile'),
            id=appointment_id,
        )
        dados = horarios(
            appointment,
            dados_brutos.get('entrada', ''), dados_brutos.get('saida', ''),
        )
        acompanhante = (dados_brutos.get('acompanhante') or '').strip()[:120]

        # Horário invertido não vira papel: sairia dizendo "das 16h às 14h"
        # na mão de um departamento pessoal.
        emitido = imprimir and not dados['invertido']
        if emitido:
            registrar_emissao(
                request.access_context, appointment, dados,
                _own_membership(request), acompanhante=acompanhante,
            )

        return render(request, 'scheduling/declaracao.html', {
            'appointment': appointment,
            'patient': appointment.patient,
            'dados': dados,
            'acompanhante': acompanhante,
            'clinica': ClinicProfile.objects.filter(
                tenant_id=request.access_context.tenant_id,
            ).first(),
            'tenant': appointment.tenant,
            'imprimir': emitido,
            'emitida_em': timezone.localtime(),
        })


class ReturnQueueView(TenantScopedView):
    """A fila de retornos: quem o médico mandou voltar, e quando.

    Tela da recepção, e não do consultório. Quem decide "volta em seis
    meses" é o médico, ao fechar o atendimento; quem transforma isso em
    horário marcado é a secretária, e ela precisa de uma lista ordenada por
    vencimento com o atrasado no topo -- não de um relatório.

    **Capacidade de agenda, e não capacidade clínica.** A lista mostra
    nome, médico e data: é a mesma informação que a grade do dia já mostra.
    Exigir `READ_CLINICAL` aqui tiraria a tela exatamente de quem faz o
    trabalho.

    O filtro por médico existe porque a clínica com três médicos vira três
    filas na prática -- quem liga precisa saber para qual agenda está
    oferecendo horário antes de discar.
    """

    def get(self, request):
        from .returns import fila

        ctx = request.access_context
        # Conferido contra os médicos da clínica, e não passado direto ao
        # filtro: um `?physician=lixo` viraria `ValidationError` e erro 500,
        # e um UUID de outra clínica não pode sequer ser tentado.
        doctors = _doctors(request)
        medico = request.GET.get('physician') or ''
        if medico not in {str(d.id) for d in doctors}:
            medico = ''
        historico = request.GET.get('resolvidos') == '1'
        registros = list(fila(
            ctx.tenant_id,
            physician_membership_id=medico or None,
            incluir_resolvidos=historico,
        ))
        hoje = timezone.localdate()
        return render(request, 'scheduling/retornos.html', {
            'registros': registros,
            'doctors': doctors,
            'physician_id': medico,
            'historico': historico,
            'hoje': hoje,
            'atrasados': sum(1 for r in registros if r.status == 'pending' and r.due_on < hoje),
            'proximos': sum(1 for r in registros if r.status == 'pending' and r.due_on >= hoje),
        })


class ReturnResolveView(TenantScopedView):
    """Dar baixa em uma linha da fila: agendado, concluído ou dispensado.

    Três saídas e não duas porque "não vai voltar" é desfecho legítimo --
    paciente que mudou de cidade, que teve alta, que morreu. Sem
    "Dispensado", esses nomes ficariam na lista para sempre, e uma lista que
    não esvazia deixa de ser lida.

    O `status` chega pelo POST e é conferido contra as escolhas do modelo
    **antes** de gravar: sem isso, um POST à mão gravaria qualquer string no
    campo e a linha sumiria da fila por não bater com nenhum filtro.
    """

    def post(self, request, return_id):
        from .models import ReturnStatus, ScheduledReturn
        from .returns import resolver

        registro = get_object_or_404(
            scope_to_tenant(ScheduledReturn.objects.all(), request.access_context),
            id=return_id,
        )
        status = request.POST.get('status') or ''
        if status not in ReturnStatus.values or status == ReturnStatus.PENDING:
            messages.error(request, 'Situação inválida para o retorno.')
            return redirect('scheduling:returns')
        resolver(
            request.access_context, registro, status, _own_membership(request),
            note=request.POST.get('note', ''),
        )
        messages.success(
            request,
            f'Retorno de {registro.patient.full_name}: {registro.get_status_display().lower()}.',
        )
        # Volta para a fila com o mesmo filtro que a secretária estava
        # vendo. Redirecionar para a lista "limpa" faria ela reescolher o
        # médico a cada baixa, e são dezenas de baixas numa manhã.
        # Remontado a partir de campos conhecidos, e não copiado do POST:
        # devolver ao cliente uma URL que ele mesmo escreveu é o caminho
        # curto para um redirecionamento aberto.
        filtro = urlencode({
            chave: valor for chave, valor in (
                ('physician', request.POST.get('physician', '')),
                ('resolvidos', '1' if request.POST.get('resolvidos') == '1' else ''),
            ) if valor
        })
        destino = reverse('scheduling:returns')
        return redirect(f'{destino}?{filtro}' if filtro else destino)

# --------------------------------------------------------------------------
# Lista de espera (1.31)
# --------------------------------------------------------------------------

def _uuid_ou_none(valor):
    import uuid

    try:
        return uuid.UUID(str(valor)) if valor else None
    except ValueError:
        return None


def _filtro_medico(doctors, source, chave='physician'):
    """O médico do filtro, conferido contra os da clínica (lixo vira "todos").

    Nos POSTs o filtro vem em `filtro`, e não em `physician`: no formulário
    de incluir e no de editar, `physician` é o médico **da espera**.
    """
    medico = source.get(chave) or ''
    return medico if medico in {str(d.id) for d in doctors} else ''


def _espera_redirect(request):
    """Volta à lista com o filtro que estava, remontado de campos conhecidos.

    Não copia uma URL do POST — mesma razão da fila de retornos: devolver ao
    cliente um endereço que ele mesmo escreveu é redirecionamento aberto.
    """
    filtro = urlencode({
        chave: valor for chave, valor in (
            ('physician', _filtro_medico(_doctors(request), request.POST, 'filtro')),
            ('encerradas', '1' if request.POST.get('encerradas') == '1' else ''),
        ) if valor
    })
    destino = reverse('scheduling:espera')
    return redirect(f'{destino}?{filtro}' if filtro else destino)


def _medico_da_espera(request, valor):
    """O médico escolhido no formulário, ou `None` (= qualquer médico)."""
    if not valor:
        return None
    for doctor in _doctors(request):
        if doctor.id == valor:
            return doctor
    raise Http404


def _espera_ou_404(request, espera_id):
    from .models import PacienteEmEspera

    return get_object_or_404(
        scope_to_tenant(PacienteEmEspera.objects.select_related('patient'), request.access_context),
        id=espera_id,
    )


class EsperaListView(TenantScopedView):
    """A lista de espera: quem pediu horário e ainda não tem, na ordem da recepção.

    **Capacidade de agenda**, como a fila de retornos: secretária, médico,
    dono e gestor montam e reordenam. A tela mostra nome, contato, médico e
    a observação da recepção — o que a grade já mostra, e nada do
    prontuário.

    O selo "tem horário em…" é a ponte com a agenda: quem foi marcado pela
    busca (e não puxado daqui) aparece avisando, para a secretária retirar
    o nome em vez de ligar à toa.
    """

    def get(self, request):
        from .espera import lista
        from .forms import EsperaForm
        from .models import OCCUPYING_STATUSES, Appointment

        ctx = request.access_context
        doctors = _doctors(request)
        medico = _filtro_medico(doctors, request.GET)
        encerradas = request.GET.get('encerradas') == '1'
        registros = lista(ctx.tenant_id, physician_membership_id=medico or None,
                          incluir_encerradas=encerradas)
        aguardando = [r for r in registros if r.status == 'aguardando']
        # O próximo horário de quem aguarda, numa consulta só.
        proximos = {}
        if aguardando:
            for appt in (
                Appointment.objects
                .filter(tenant_id=ctx.tenant_id, patient_id__in=[r.patient_id for r in aguardando],
                        status__in=OCCUPYING_STATUSES, starts_at__gte=timezone.now())
                .order_by('starts_at')
                .only('patient_id', 'starts_at')
            ):
                proximos.setdefault(appt.patient_id, appt.starts_at)
        hoje = timezone.localdate()
        for registro in registros:
            registro.proximo_horario = proximos.get(registro.patient_id)
            registro.dias_na_lista = (hoje - timezone.localtime(registro.created_at).date()).days
        return render(request, 'scheduling/espera.html', {
            'registros': registros,
            'total_aguardando': len(aguardando),
            'doctors': doctors,
            'physician_id': medico,
            'encerradas': encerradas,
            'form': EsperaForm(),
            'type_choices': AppointmentType.choices,
        })


class EsperaIncluirView(TenantScopedView):
    def post(self, request):
        from django.db import transaction

        from . import espera
        from .forms import EsperaForm

        ctx = request.access_context
        form = EsperaForm(request.POST)
        if not form.is_valid():
            messages.error(request, _first_error(form))
            return _espera_redirect(request)
        try:
            medico = _medico_da_espera(request, form.cleaned_data.get('physician'))
        except Http404:
            messages.error(request, 'Médico não encontrado nesta organização.')
            return _espera_redirect(request)
        try:
            # O pré-cadastro e a inclusão juntos: recusada a inclusão, não
            # sobra paciente criado à toa.
            with transaction.atomic():
                if form.cleaned_data.get('patient_id'):
                    patient = scope_to_tenant(Patient.objects.all(), ctx).filter(
                        id=form.cleaned_data['patient_id']).first()
                    if patient is None:
                        raise espera.EsperaError('Paciente não encontrado nesta organização.')
                else:
                    patient = services.quick_register_patient(
                        ctx, form.cleaned_data['new_name'],
                        form.cleaned_data.get('new_phone', ''),
                        email=form.cleaned_data.get('new_email', ''),
                        accepts_messages=form.cleaned_data.get('contact_accepts_messages', True),
                    )
                entrada = espera.incluir(
                    ctx, patient, physician_membership=medico,
                    appointment_type=form.cleaned_data.get('appointment_type') or '',
                    observacao=form.cleaned_data.get('observacao', ''),
                    ator=_own_membership(request),
                )
        except PlanLimitReached as limite:
            messages.error(request, limite.message())
            return _espera_redirect(request)
        except espera.EsperaError as exc:
            messages.error(request, str(exc))
            return _espera_redirect(request)
        messages.success(
            request, f'{patient.full_name} entrou na lista de espera, em {entrada.posicao}º lugar.',
        )
        return _espera_redirect(request)


class EsperaMoverView(TenantScopedView):
    """Subir, descer ou levar a uma posição. Só POST."""

    def post(self, request, espera_id):
        from . import espera

        ctx = request.access_context
        entrada = _espera_ou_404(request, espera_id)
        medico = _filtro_medico(_doctors(request), request.POST, 'filtro')
        try:
            direcao = request.POST.get('direcao') or ''
            if direcao:
                espera.mover_vizinho(ctx, entrada, direcao,
                                     physician_membership_id=_uuid_ou_none(medico))
            else:
                try:
                    posicao = int(request.POST.get('posicao') or '')
                except ValueError:
                    raise espera.EsperaError('Informe a posição com um número.')
                destino = espera.mover_para(ctx, entrada, posicao)
                messages.success(request, f'{entrada.patient.full_name} agora em {destino}º lugar.')
        except espera.EsperaError as exc:
            messages.error(request, str(exc))
        return _espera_redirect(request)


class EsperaEditarView(TenantScopedView):
    def post(self, request, espera_id):
        from . import espera
        from .forms import EsperaEditarForm

        ctx = request.access_context
        entrada = _espera_ou_404(request, espera_id)
        form = EsperaEditarForm(request.POST)
        if not form.is_valid():
            messages.error(request, _first_error(form))
            return _espera_redirect(request)
        try:
            escolhido = form.cleaned_data.get('physician')
            # Espera de médico que saiu da equipe: ele não está mais na lista
            # de médicos, e editar só a observação trocava a espera para
            # "qualquer médico" sem ninguém pedir (revisão de 2026-11-02,
            # W10). O mesmo médico de antes continua valendo; trocar por
            # outro segue passando pela lista de quem atende hoje.
            if escolhido and escolhido == entrada.physician_membership_id:
                medico = entrada.physician_membership
            else:
                medico = _medico_da_espera(request, escolhido)
            espera.editar(
                ctx, entrada, physician_membership=medico,
                appointment_type=form.cleaned_data.get('appointment_type') or '',
                observacao=form.cleaned_data.get('observacao', ''),
            )
        except Http404:
            messages.error(request, 'Médico não encontrado nesta organização.')
            return _espera_redirect(request)
        except espera.EsperaError as exc:
            messages.error(request, str(exc))
            return _espera_redirect(request)
        messages.success(request, f'Espera de {entrada.patient.full_name} atualizada.')
        return _espera_redirect(request)


class EsperaRetirarView(TenantScopedView):
    def post(self, request, espera_id):
        from . import espera

        entrada = _espera_ou_404(request, espera_id)
        try:
            espera.retirar(request.access_context, entrada,
                           motivo=request.POST.get('motivo', ''), ator=_own_membership(request))
        except espera.EsperaError as exc:
            messages.error(request, str(exc))
            return _espera_redirect(request)
        messages.success(request, f'{entrada.patient.full_name} saiu da lista de espera.')
        return _espera_redirect(request)


class EsperaOpcoesView(TenantScopedView):
    """As esperas que o modal de marcar oferece, em JSON, na ordem da lista.

    Buscadas ao abrir o modal, e não desenhadas com a grade: a lista muda
    durante o dia (outra pessoa reordena, puxa um nome), e o modal precisa
    mostrar a de agora. E a grade da semana tem número de consultas medido
    (`check_semana_em_lote`) — esta não entra na conta dela.
    """

    def get(self, request):
        from .espera import opcoes_do_modal

        medico = _uuid_ou_none(request.GET.get('physician'))
        if medico is None:
            raise Http404
        doctor = _doctor_or_404(request, medico)
        tipos = dict(AppointmentType.choices)
        return JsonResponse({'results': [
            {
                'id': str(e.id), 'posicao': e.posicao,
                'patient_id': str(e.patient_id), 'full_name': e.patient.full_name,
                'record_number': e.patient.record_number,
                'appointment_type': e.appointment_type,
                'appointment_type_label': tipos.get(e.appointment_type, ''),
                'observacao': e.observacao,
                'qualquer_medico': e.physician_membership_id is None,
            }
            for e in opcoes_do_modal(request.access_context.tenant_id, doctor.id)
        ]})


# Compatibilidade com as rotas antigas da agenda.
DayView = AgendaDayView
WeekView = AgendaWeekView
MonthView = AgendaMonthView


class AgendaPorEmailView(TenantScopedView):
    """Ligar ou desligar a agenda de amanhã por e-mail (1.36).

    O vínculo vem na rota, e não da sessão: o link sai no e-mail de uma
    clínica, e quem atende em duas pode estar com a outra aberta. Só o
    **próprio** médico mexe na própria opção — o vínculo de outra pessoa é
    404, como o de um id que não existe, sem dizer qual dos dois foi.
    Desligar e religar são um clique cada: é preferência de quem recebe, e
    não há nada do outro lado que se perca.
    """

    def _vinculo(self, request, membership_id):
        from tenancy.models import Membership, MembershipStatus, Role

        vinculo = Membership.objects.filter(
            id=membership_id, user=request.user, status=MembershipStatus.ACTIVE,
            roles__contains=[Role.DOCTOR],
        ).select_related('tenant').first()
        if vinculo is None:
            raise Http404
        return vinculo

    def get(self, request, membership_id):
        from django.conf import settings as dj_settings

        vinculo = self._vinculo(request, membership_id)
        return render(request, 'scheduling/agenda_por_email.html', {
            'vinculo': vinculo,
            'clinica': vinculo.tenant.trade_name or vinculo.tenant.legal_name,
            'hora': dj_settings.AGENDA_POR_EMAIL_HORA,
        })

    def post(self, request, membership_id):
        from audit.services import record_audit_event

        vinculo = self._vinculo(request, membership_id)
        ligar = request.POST.get('ligar') == '1'
        if vinculo.agenda_por_email != ligar:
            vinculo.agenda_por_email = ligar
            vinculo.save(update_fields=['agenda_por_email', 'updated_at'])
            record_audit_event(
                request.user, vinculo.tenant, 'scheduling.agenda_por_email_' + ('ligada' if ligar else 'desligada'),
                object_type='membership', object_id=vinculo.id, outcome='success',
            )
        messages.success(
            request,
            'Pronto: a agenda do dia seguinte volta a chegar por e-mail.' if ligar
            else 'Pronto: a agenda do dia seguinte não será mais enviada por e-mail.',
        )
        return redirect('scheduling:agenda-por-email', membership_id=vinculo.id)
