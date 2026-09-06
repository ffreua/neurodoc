from django.contrib import admin

from .models import Appointment, AvailabilityRule, ScheduleBlock


@admin.register(AvailabilityRule)
class AvailabilityRuleAdmin(admin.ModelAdmin):
    list_display = ['physician_membership', 'weekday', 'local_start', 'local_end', 'tenant']
    list_filter = ['tenant', 'weekday']


@admin.register(ScheduleBlock)
class ScheduleBlockAdmin(admin.ModelAdmin):
    list_display = ['physician_membership', 'kind', 'start_at', 'end_at']
    list_filter = ['tenant', 'kind']


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ['patient', 'physician_membership', 'starts_at', 'status', 'is_overbook']
    list_filter = ['tenant', 'status']
    search_fields = ['patient__full_name']
