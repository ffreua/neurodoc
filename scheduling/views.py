from datetime import date, datetime, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from patients.models import Patient
from tenancy.selectors import scope_to_tenant

from . import services
from .availability import available_slots
from .forms import ReserveAppointmentForm, RescheduleAppointmentForm
from .models import Appointment, AppointmentStatus


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return timezone.now().date()


class DayView(TenantScopedView):
    def get(self, request):
        day = _parse_date(request.GET.get('date'))
        appointments = scope_to_tenant(Appointment.objects.all(), request.access_context).filter(
            starts_at__date=day,
        ).select_related('patient', 'physician_membership__user').order_by('starts_at')
        return render(request, 'scheduling/day.html', {
            'day': day, 'appointments': appointments,
            'prev_day': day - timedelta(days=1), 'next_day': day + timedelta(days=1),
        })


class WeekView(TenantScopedView):
    def get(self, request):
        day = _parse_date(request.GET.get('date'))
        week_start = day - timedelta(days=day.weekday())
        days = [week_start + timedelta(days=i) for i in range(7)]
        appointments = scope_to_tenant(Appointment.objects.all(), request.access_context).filter(
            starts_at__date__gte=days[0], starts_at__date__lte=days[-1],
        ).select_related('patient', 'physician_membership__user').order_by('starts_at')
        by_day = {d: [] for d in days}
        for appt in appointments:
            by_day.setdefault(appt.starts_at.date(), []).append(appt)
        day_rows = [{'date': d, 'appointments': by_day[d]} for d in days]
        return render(request, 'scheduling/week.html', {
            'day_rows': day_rows,
            'prev_week': week_start - timedelta(days=7), 'next_week': week_start + timedelta(days=7),
        })


class MonthView(TenantScopedView):
    def get(self, request):
        day = _parse_date(request.GET.get('date'))
        month_start = day.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        appointments = scope_to_tenant(Appointment.objects.all(), request.access_context).filter(
            starts_at__date__gte=month_start, starts_at__date__lt=next_month,
        )
        counts = {}
        for appt in appointments:
            counts[appt.starts_at.date()] = counts.get(appt.starts_at.date(), 0) + 1
        day_counts = [{'date': d, 'count': c} for d, c in sorted(counts.items())]
        return render(request, 'scheduling/month.html', {
            'month_start': month_start, 'day_counts': day_counts,
            'prev_month': (month_start - timedelta(days=1)).replace(day=1), 'next_month': next_month,
        })


class ReserveAppointmentView(TenantScopedView):
    def get(self, request):
        patient_id = request.GET.get('patient_id')
        form = ReserveAppointmentForm(
            tenant_id=request.access_context.tenant_id, initial={'patient_id': patient_id},
        )
        return render(request, 'scheduling/reserve.html', {'form': form})

    def post(self, request):
        form = ReserveAppointmentForm(request.POST, tenant_id=request.access_context.tenant_id)
        if form.is_valid():
            patient = get_object_or_404(
                scope_to_tenant(Patient.objects.all(), request.access_context), id=form.cleaned_data['patient_id'],
            )
            try:
                appointment = services.reserve_appointment(
                    request.access_context, patient, form.cleaned_data['physician_membership'],
                    form.cleaned_data['starts_at'], form.cleaned_data['ends_at'], form.cleaned_data['type'],
                    is_overbook=form.cleaned_data['is_overbook'],
                    override_reason=form.cleaned_data['override_reason'],
                    override_by=None,
                )
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                return redirect('scheduling:day')
        return render(request, 'scheduling/reserve.html', {'form': form})


class AvailabilitySlotsView(TenantScopedView):
    def get(self, request):
        physician_id = request.GET.get('physician_membership_id')
        day = _parse_date(request.GET.get('date'))
        if not physician_id:
            return JsonResponse({'slots': []})
        slots = available_slots(physician_id, day)
        return JsonResponse({'slots': [
            {'starts_at': s.isoformat(), 'ends_at': e.isoformat()} for s, e in slots
        ]})


def _get_appointment(request, appointment_id):
    return get_object_or_404(
        scope_to_tenant(Appointment.objects.all(), request.access_context), id=appointment_id,
    )


class RescheduleAppointmentView(TenantScopedView):
    def get(self, request, appointment_id):
        appointment = _get_appointment(request, appointment_id)
        form = RescheduleAppointmentForm(initial={
            'starts_at': appointment.starts_at, 'ends_at': appointment.ends_at,
            'row_version': appointment.row_version,
        })
        return render(request, 'scheduling/reschedule.html', {'form': form, 'appointment': appointment})

    def post(self, request, appointment_id):
        appointment = _get_appointment(request, appointment_id)
        form = RescheduleAppointmentForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['row_version'] != appointment.row_version:
                return HttpResponse('Conflict: this appointment changed since you opened it.', status=409)
            try:
                services.reschedule_appointment(
                    request.access_context, appointment,
                    form.cleaned_data['starts_at'], form.cleaned_data['ends_at'], request.user.id,
                )
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                return redirect('scheduling:day')
        return render(request, 'scheduling/reschedule.html', {'form': form, 'appointment': appointment})


class AppointmentActionView(TenantScopedView):
    def post(self, request, appointment_id, action):
        appointment = _get_appointment(request, appointment_id)
        try:
            if action == 'confirm':
                services.transition_appointment(appointment, AppointmentStatus.CONFIRMED, request.user.id)
            elif action == 'check-in':
                services.check_in(appointment, request.user.id)
            elif action == 'start':
                services.start_appointment(appointment, request.user.id)
            elif action == 'complete':
                services.complete_appointment(appointment, request.user.id)
            elif action == 'no-show':
                services.mark_no_show(appointment, request.user.id)
            elif action == 'cancel':
                services.cancel_appointment(appointment, request.user.id, reason=request.POST.get('reason', ''))
            else:
                raise Http404
        except services.SchedulingError as exc:
            return HttpResponse(str(exc), status=409)
        return redirect('scheduling:day')


class SecretaryDeskView(TenantScopedView):
    def get(self, request):
        today = timezone.now().date()
        appointments = scope_to_tenant(Appointment.objects.all(), request.access_context).filter(
            starts_at__date=today,
        ).exclude(status=AppointmentStatus.CANCELLED).select_related(
            'patient', 'physician_membership__user',
        ).order_by('starts_at')
        return render(request, 'scheduling/desk.html', {'appointments': appointments, 'today': today})
