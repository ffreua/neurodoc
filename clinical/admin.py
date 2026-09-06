from django.contrib import admin

from .models import (
    CarryForwardItem, ClinicalAmendment, Encounter, EncounterDiagnosis, ExaminationFinding,
)


@admin.register(Encounter)
class EncounterAdmin(admin.ModelAdmin):
    list_display = ['patient', 'physician_membership', 'occurred_at', 'status']
    list_filter = ['tenant', 'status']
    search_fields = ['patient__full_name']


@admin.register(ExaminationFinding)
class ExaminationFindingAdmin(admin.ModelAdmin):
    list_display = ['encounter', 'domain', 'item_code', 'side', 'state']
    list_filter = ['domain', 'state']


@admin.register(EncounterDiagnosis)
class EncounterDiagnosisAdmin(admin.ModelAdmin):
    list_display = ['encounter', 'code_snapshot', 'certainty', 'rank']


@admin.register(CarryForwardItem)
class CarryForwardItemAdmin(admin.ModelAdmin):
    list_display = ['target_encounter', 'source_encounter', 'field_path', 'review_action']
    list_filter = ['review_action']


@admin.register(ClinicalAmendment)
class ClinicalAmendmentAdmin(admin.ModelAdmin):
    list_display = ['encounter', 'author', 'authored_at']
