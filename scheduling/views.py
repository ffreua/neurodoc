from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from patients.models import Patient
from tenancy.selectors import scope_to_tenant

from . import publishing, services
from .availability import (
    appointments_on, available_slots, day_grid, slot_minutes_for, suggested_slot_minutes,
    type_durations, week_grid,
)
from .forms import (
    ChangePatientForm, DoctorChoiceForm, LocalHolidayForm, QuickBookingForm,
    RescheduleAppointmentForm, ReserveAppointmentForm, ScheduleBlockForm, TypeDurationForm,
    WeeklyScheduleForm,
)
from .models import (
    AppointmentStatus, AppointmentType, AvailabilityRule, Holiday, ScheduleBlock,
    ScheduleBlockKind,
)


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _parse_date(value, default=None):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return default or timezone.now().date()


def _doctors(request):
    from tenancy.models import Membership, MembershipStatus, Role

    return list(
        Membership.objects.filter(
            tenant_id=request.access_context.tenant_id, status=MembershipStatus.ACTIVE,
            roles__contains=[Role.DOCTOR],
        ).select_related('user').order_by('user__first_name', 'user__email')
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

        today = timezone.now().date()
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
        durations = type_durations(doctor.id)
        step = slot_minutes_for(doctor.id, week_start) or suggested_slot_minutes(doctor.id)
        context.update({
            'times': times, 'columns': columns,
            'durations': [
                {'value': value, 'label': label, 'minutes': durations[value],
                 'cells': max(1, -(-durations[value] // step)) if step else 1}
                for value, label in AppointmentType.choices
            ],
            'slot_minutes': step,
            'has_schedule': bool(times),
            'booking_form': QuickBookingForm(),
            'change_form': ChangePatientForm(),
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
        today = timezone.now().date()
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
            'has_schedule': bool(cells),
            'booking_form': QuickBookingForm(),
            'change_form': ChangePatientForm(),
            'free': sum(1 for cell in cells if cell['status'] == 'free'),
            'busy': sum(1 for cell in cells if cell['status'] == 'busy'),
        })
        return render(request, 'scheduling/agenda_day.html', context)


class AgendaMonthView(TenantScopedView):
    """Mês em blocos, para achar a semana — não para marcar."""

    def get(self, request):
        doctors = _doctors(request)
        doctor = _selected_doctor(request, doctors)
        day = _parse_date(request.GET.get('date'))
        month_start = day.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        grid_start = month_start - timedelta(days=month_start.weekday())
        grid_end = next_month + timedelta(days=(7 - next_month.weekday()) % 7)

        by_date = {}
        blocked = set()
        if doctor is not None:
            from .models import OCCUPYING_STATUSES, Appointment

            for appointment in Appointment.objects.filter(
                physician_membership=doctor, status__in=list(OCCUPYING_STATUSES),
                starts_at__date__gte=grid_start, starts_at__date__lt=grid_end,
            ):
                key = timezone.localtime(appointment.starts_at).date()
                by_date[key] = by_date.get(key, 0) + 1
            for block in ScheduleBlock.objects.filter(
                physician_membership=doctor, start_at__date__lt=grid_end,
                end_at__date__gte=grid_start,
            ).exclude(kind=ScheduleBlockKind.EXTRA_AVAILABILITY):
                cursor = timezone.localtime(block.start_at).date()
                last = timezone.localtime(block.end_at).date()
                while cursor <= last:
                    blocked.add(cursor)
                    cursor += timedelta(days=1)

        weekdays_with_rules = set()
        if doctor is not None:
            weekdays_with_rules = set(
                AvailabilityRule.objects.filter(physician_membership=doctor)
                .filter(publishing.models_ends_on_ok(grid_start))
                .values_list('weekday', flat=True)
            )

        weeks, week = [], []
        cursor = grid_start
        today = timezone.now().date()
        while cursor < grid_end:
            week.append({
                'date': cursor,
                'in_month': cursor.month == month_start.month,
                'is_today': cursor == today,
                'count': by_date.get(cursor, 0),
                'blocked': cursor in blocked,
                'works': cursor.weekday() in weekdays_with_rules,
            })
            cursor += timedelta(days=1)
            if len(week) == 7:
                weeks.append(week)
                week = []
        return render(request, 'scheduling/agenda_month.html', {
            'doctors': doctors, 'doctor': doctor, 'view_mode': 'month',
            'month_start': month_start, 'weeks': weeks, 'today': today,
            **_nav_urls(
                'scheduling:month', doctor, month_start,
                (month_start - timedelta(days=1)).replace(day=1), next_month,
                today.replace(day=1),
            ),
        })


# --------------------------------------------------------------------------
# Configuração da agenda pelo médico
# --------------------------------------------------------------------------

class ScheduleSettingsView(TenantScopedView):
    """Tela em que o médico monta a própria grade e publica por um período."""

    def _context(self, request, doctor, **overrides):
        today = timezone.now().date()
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
        # Feriados nacionais do horizonte, calculados na abertura da tela: são
        # aritmética, não têm custo, e evitam a tela abrir vazia pedindo que
        # alguém rode um comando antes.
        publishing.ensure_national_holidays(
            request.access_context,
            range(timezone.now().year, timezone.now().year + 3),
        )
        return render(request, 'scheduling/settings.html', self._context(request, doctor))


class ScheduleSettingsSaveView(TenantScopedView):
    """Publica a grade semanal do médico."""

    def post(self, request, membership_id):
        doctor = _doctor_or_404(request, membership_id)
        form = WeeklyScheduleForm(request.POST)
        if not form.is_valid():
            return render(
                request, 'scheduling/settings.html',
                ScheduleSettingsView()._context(request, doctor, schedule_form=form),
            )
        result = publishing.publish_weekly_schedule(request.access_context, doctor, form.cleaned_data)
        ends_on = form.cleaned_data.get('ends_on')
        until = f'até {ends_on.strftime("%d/%m/%Y")}' if ends_on else 'sem prazo'
        messages.success(
            request,
            f'Agenda publicada: {len(result["created"])} dia(s) da semana, {until}.'
            + (f' {result["replaced"]} regra(s) anterior(es) encerrada(s).' if result['replaced'] else ''),
        )
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class TypeDurationSaveView(TenantScopedView):
    def post(self, request, membership_id):
        doctor = _doctor_or_404(request, membership_id)
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


class RuleDeleteView(TenantScopedView):
    def post(self, request, membership_id, rule_id):
        doctor = _doctor_or_404(request, membership_id)
        rule = get_object_or_404(
            AvailabilityRule, id=rule_id, physician_membership=doctor,
            tenant_id=request.access_context.tenant_id,
        )
        outcome = publishing.remove_rule(request.access_context, doctor, rule)
        messages.success(
            request,
            'Horário removido da grade.' if outcome == 'deleted'
            else 'Horário encerrado a partir de hoje; a agenda passada continua como era.',
        )
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class BlockCreateView(TenantScopedView):
    def post(self, request, membership_id):
        doctor = _doctor_or_404(request, membership_id)
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


class BlockDeleteView(TenantScopedView):
    def post(self, request, membership_id, block_id):
        doctor = _doctor_or_404(request, membership_id)
        block = get_object_or_404(
            ScheduleBlock, id=block_id, physician_membership=doctor,
            tenant_id=request.access_context.tenant_id,
        )
        block.delete()
        messages.success(request, 'Removido da agenda.')
        return redirect(f'{reverse("scheduling:settings")}?physician={doctor.id}')


class HolidayReviewView(TenantScopedView):
    """Aplica as decisões de feriado: o que bloquear e o que atender.

    Trabalha como um conjunto de interruptores sobre o período: o que vem
    marcado fica bloqueado, o que não vem tem o bloqueio de feriado removido.
    Desmarcar quer dizer "vou atender nesse dia".
    """

    def post(self, request, membership_id):
        doctor = _doctor_or_404(request, membership_id)
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


class LocalHolidayCreateView(TenantScopedView):
    def post(self, request, membership_id):
        doctor = _doctor_or_404(request, membership_id)
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


class LocalHolidayDeleteView(TenantScopedView):
    def post(self, request, membership_id, holiday_id):
        doctor = _doctor_or_404(request, membership_id)
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
            first = next(iter(form.errors.values()))[0]
            messages.error(request, first)
            day = _parse_date(request.POST.get('date'))
            return _agenda_redirect(request, doctor, day)

        starts_at = form.cleaned_data['starts_at']
        day = timezone.localtime(starts_at).date()

        if form.cleaned_data.get('patient_id'):
            patient = scope_to_tenant(
                Patient.objects.all(), request.access_context,
            ).filter(id=form.cleaned_data['patient_id']).first()
            if patient is None:
                messages.error(request, 'Paciente não encontrado nesta organização.')
                return _agenda_redirect(request, doctor, day)
        else:
            patient = services.quick_register_patient(
                request.access_context, form.cleaned_data['new_name'],
                form.cleaned_data.get('new_phone', ''), note=form.cleaned_data.get('note', ''),
            )

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
        except Exception:
            messages.error(
                request,
                'Este horário acabou de ser ocupado por outra reserva. Escolha outro.',
            )
            return _agenda_redirect(request, doctor, day)

        local = timezone.localtime(appointment.starts_at)
        stage = ''
        if patient.registration_stage == 'preliminary':
            stage = ' Pré-cadastro: a ficha completa é pedida no check-in.'
        messages.success(
            request,
            f'{patient.full_name} marcado para {local.strftime("%d/%m/%Y às %H:%M")} '
            f'({appointment.get_type_display()}).{stage}',
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
                services.cancel_appointment(
                    appointment, request.user.id, reason=request.POST.get('reason', ''),
                )
                messages.success(request, 'Horário liberado.')
            else:
                raise Http404
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
        return _agenda_redirect(request, doctor, day)


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
            messages.error(request, next(iter(form.errors.values()))[0])
            return _agenda_redirect(request, doctor, day)
        patient = scope_to_tenant(Patient.objects.all(), request.access_context).filter(
            id=form.cleaned_data['patient_id'],
        ).first()
        if patient is None:
            messages.error(request, 'Paciente não encontrado nesta organização.')
            return _agenda_redirect(request, doctor, day)
        try:
            services.change_appointment_patient(
                request.access_context, appointment, patient,
                form.cleaned_data['reason'], request.user.id,
            )
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)
        messages.success(request, f'Horário agora é de {patient.full_name}.')
        return _agenda_redirect(request, doctor, day)


class RescheduleAppointmentView(TenantScopedView):
    def get(self, request, appointment_id):
        from .models import Appointment

        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context), id=appointment_id,
        )
        day = timezone.localtime(appointment.starts_at).date()
        return render(request, 'scheduling/reschedule.html', {
            'appointment': appointment,
            'form': RescheduleAppointmentForm(initial={
                'starts_at': appointment.starts_at, 'ends_at': appointment.ends_at,
                'row_version': appointment.row_version,
            }),
            'slots': available_slots(
                appointment.physician_membership_id, day,
                minutes=int((appointment.ends_at - appointment.starts_at).total_seconds() // 60),
            ),
            'day': day,
        })

    def post(self, request, appointment_id):
        from .models import Appointment

        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context), id=appointment_id,
        )
        form = RescheduleAppointmentForm(request.POST)
        if not form.is_valid():
            return render(request, 'scheduling/reschedule.html', {
                'appointment': appointment, 'form': form,
                'day': timezone.localtime(appointment.starts_at).date(),
            })
        if form.cleaned_data['row_version'] != appointment.row_version:
            messages.error(
                request,
                'Este horário mudou desde que você abriu a tela. Recarregue antes de remarcar.',
            )
            return _agenda_redirect(
                request, appointment.physician_membership,
                timezone.localtime(appointment.starts_at).date(),
            )
        try:
            services.reschedule_appointment(
                request.access_context, appointment,
                form.cleaned_data['starts_at'], form.cleaned_data['ends_at'], request.user.id,
            )
        except Exception as exc:
            form.add_error(None, str(exc))
            return render(request, 'scheduling/reschedule.html', {
                'appointment': appointment, 'form': form,
                'day': timezone.localtime(appointment.starts_at).date(),
            })
        local = timezone.localtime(appointment.starts_at)
        messages.success(request, f'Remarcado para {local.strftime("%d/%m/%Y às %H:%M")}.')
        return _agenda_redirect(
            request, appointment.physician_membership, local.date(),
        )


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
            .select_related('patient', 'physician_membership__user')
            .order_by('starts_at')
        )
        pending = [
            appointment for appointment in appointments
            if appointment.patient.registration_stage == 'preliminary'
        ]
        return render(request, 'scheduling/desk.html', {
            'appointments': appointments, 'day': day, 'today': timezone.now().date(),
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


# Compatibilidade com as rotas antigas da agenda.
DayView = AgendaDayView
WeekView = AgendaWeekView
MonthView = AgendaMonthView
