from django.contrib import admin

from .models import CRMCard, CRMStage, CRMTransition


@admin.register(CRMStage)
class CRMStageAdmin(admin.ModelAdmin):
    list_display = ['name', 'order', 'active', 'tenant']
    list_filter = ['tenant', 'active']


@admin.register(CRMCard)
class CRMCardAdmin(admin.ModelAdmin):
    list_display = ['patient', 'stage', 'assigned_membership', 'due_at', 'tenant']
    list_filter = ['stage', 'tenant']


@admin.register(CRMTransition)
class CRMTransitionAdmin(admin.ModelAdmin):
    list_display = ['card', 'from_stage', 'to_stage', 'actor', 'created_at']
