from django.contrib import admin

from .models import FeeSchedule, FinancialAdjustment, Payment, Receivable


@admin.register(FeeSchedule)
class FeeScheduleAdmin(admin.ModelAdmin):
    list_display = ['payment_category', 'physician', 'plan', 'procedure', 'gross_amount', 'effective_from', 'effective_to', 'tenant']
    list_filter = ['payment_category', 'tenant']


@admin.register(Receivable)
class ReceivableAdmin(admin.ModelAdmin):
    list_display = ['patient', 'charge_kind', 'expected_amount', 'charged_amount', 'status', 'competence_date', 'tenant']
    list_filter = ['status', 'charge_kind', 'tenant']
    readonly_fields = ['fee_snapshot']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['receivable', 'amount', 'method', 'paid_at', 'tenant']
    list_filter = ['tenant']


@admin.register(FinancialAdjustment)
class FinancialAdjustmentAdmin(admin.ModelAdmin):
    list_display = ['receivable', 'type', 'amount', 'approved_by', 'tenant']
    list_filter = ['type', 'tenant']
