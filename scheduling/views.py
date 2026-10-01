import logging
from datetime import datetime, time, timedelta

from django.contrib import messages
from django.db import IntegrityError
from django.http import Http404, JsonResponse
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
    ChangePatientForm, DoctorChoiceForm, LocalHolidayForm, QuickBookingForm,
    RescheduleAppointmentForm, ReserveAppointmentForm, ScheduleBlockForm, TypeDurationForm,
    WeeklyScheduleForm,
)
from .models import (
    AppointmentStatus, AppointmentType, AvailabilityRule, Holiday, ScheduleBlock,
    ScheduleBlockKind,
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


def _booking_context(doctor, day):
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
            **_booking_context(doctor, week_start),
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
            **_booking_context(doctor, day),
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
                'blocked': bool(counts.get('blocked')) and not counts.get('free'),
                'works': counts.get('works', False),
                'cells': counts.get('cells', []),
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
        booking_context = _booking_context(doctor, month_start) if doctor is not None else {}
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
        result = publishing.publish_weekly_schedule(request.access_context, doctor, form.cleaned_data)
        ends_on = form.cleaned_data.get('ends_on')
        until = f'até {ends_on.strftime("%d/%m/%Y")}' if ends_on else 'sem prazo'
        messages.success(
            request,
            f'Agenda publicada: {len(result["created"])} dia(s) da semana, {until}.'
            + (f' {result["replaced"]} regra(s) anterior(es) encerrada(s).' if result['replaced'] else ''),
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
        messages.success(
            request,
            'Horário removido da grade.' if outcome == 'deleted'
            else 'Horário encerrado a partir de hoje; a agenda passada continua como era.',
        )
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


class SendConfirmationView(TenantScopedView):
    """Envia a confirmação do horário por SMS ou e-mail.

    Reenvio é permitido: mensagem não chega, e a secretária precisa poder
    mandar de novo. Cada envio fica registrado como uma entrega própria.
    """

    def post(self, request, appointment_id, channel):
        from communications.models import DeliveryChannel
        from communications.services import NoUsableContact, send_appointment_confirmation

        from .models import Appointment

        if channel not in (DeliveryChannel.SMS, DeliveryChannel.EMAIL):
            raise Http404
        appointment = get_object_or_404(
            scope_to_tenant(Appointment.objects.all(), request.access_context), id=appointment_id,
        )
        day = timezone.localtime(appointment.starts_at).date()
        doctor = appointment.physician_membership
        try:
            delivery = send_appointment_confirmation(
                request.access_context, appointment, channel, request.user.id,
            )
        except NoUsableContact as exc:
            messages.error(request, str(exc))
            return _agenda_redirect(request, doctor, day)

        label = 'SMS' if channel == DeliveryChannel.SMS else 'E-mail'
        destino = (
            delivery.contact.phone if channel == DeliveryChannel.SMS else delivery.contact.email
        )
        if delivery.status == 'accepted':
            messages.success(
                request, f'{label} de confirmação enviado para {destino}.',
            )
        elif delivery.status == 'no_contact':
            messages.warning(
                request,
                f'O canal de {label} está desligado nesta instalação ou nas configurações '
                'da clínica. Nada foi enviado.',
            )
        else:
            erro = delivery.attempts.order_by('-attempt_number').first()
            detalhe = f' ({erro.sanitized_error})' if erro and erro.sanitized_error else ''
            messages.error(
                request,
                f'Não foi possível enviar o {label} para {destino}{detalhe}. '
                'Confira as configurações de mensageria.',
            )
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
            messages.error(request, _first_error(form))
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
        minutes = int((appointment.ends_at - appointment.starts_at).total_seconds() // 60)

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
        minutes = int((appointment.ends_at - appointment.starts_at).total_seconds() // 60)

        # O clique num horário da lista manda apenas o início; o fim vem da
        # duração da própria consulta. Digitar o fim à mão numa remarcação
        # seria a chance de encurtar a consulta sem querer.
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

        ok, reason = fits(doctor.id, new_start, new_end)
        if not ok:
            messages.error(request, reason)
            return redirect(back)
        try:
            services.reschedule_appointment(
                request.access_context, appointment, new_start, new_end, request.user.id,
            )
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

# Compatibilidade com as rotas antigas da agenda.
DayView = AgendaDayView
WeekView = AgendaWeekView
MonthView = AgendaMonthView
