from django.contrib import admin

from .models import HealthPlan, Insurer, Observation, Patient, PatientContact, PatientCoverage


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'tenant', 'status', 'cpf']
    list_filter = ['status', 'tenant']
    search_fields = ['full_name', 'cpf']


@admin.register(PatientContact)
class PatientContactAdmin(admin.ModelAdmin):
    list_display = ['name', 'patient', 'relationship', 'authorized_for_documents']
    search_fields = ['name', 'patient__full_name']


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ['patient', 'kind', 'numeric_value', 'unit', 'observed_at']
    list_filter = ['kind', 'tenant']


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    list_display = ['name', 'tenant', 'active']


@admin.register(HealthPlan)
class HealthPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'insurer', 'tenant', 'active']


@admin.register(PatientCoverage)
class PatientCoverageAdmin(admin.ModelAdmin):
    list_display = ['patient', 'plan', 'member_number', 'starts_on', 'ends_on']
