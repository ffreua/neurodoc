from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from tenancy.models import Role

from .models import FinancialAdjustment, Payment, Receivable
from .payments import quantize_brl


FINANCIAL_HISTORY_ROLES = frozenset({Role.OWNER, Role.MANAGER})


def can_manage_financial_history(access_context):
    return bool(
        access_context
        and FINANCIAL_HISTORY_ROLES.intersection(access_context.permissions)
    )


def _assert_manager(membership, tenant_id):
    if (
        membership is None
        or str(membership.tenant_id) != str(tenant_id)
        or not FINANCIAL_HISTORY_ROLES.intersection(membership.roles or [])
    ):
        raise PermissionDenied


def _locked_receivable(receivable, membership):
    _assert_manager(membership, receivable.tenant_id)
    return Receivable.objects.select_for_update().get(
        id=receivable.id, tenant_id=membership.tenant_id,
    )


@transaction.atomic
def update_fiscal_document_number(receivable, number, actor_id):
    receivable = Receivable.objects.select_for_update().get(
        id=receivable.id, tenant_id=receivable.tenant_id,
    )
    receivable.fiscal_document_number = (number or '').strip()[:100]
    receivable.row_version += 1
    receivable.save(update_fields=[
        'fiscal_document_number', 'row_version', 'updated_at',
    ])
    record_audit_event(
        actor_id, receivable.tenant_id, 'finance.fiscal_document_updated',
        object_type='receivable', object_id=receivable.id, outcome='success',
        integrity_metadata={'present': bool(receivable.fiscal_document_number)},
    )
    return receivable


@transaction.atomic
def mark_doctor_share_paid(receivable, membership, at=None):
    receivable = _locked_receivable(receivable, membership)
    if receivable.archived_at is not None:
        raise ValueError('Cobrança arquivada não pode receber novo fechamento.')
    if receivable.doctor_share_paid_at is not None:
        return receivable
    receivable.doctor_share_paid_at = at or timezone.now()
    receivable.doctor_share_paid_amount = quantize_brl(
        receivable.fee_snapshot.get('doctor_share_amount') or 0,
    )
    receivable.doctor_share_paid_by = membership
    receivable.row_version += 1
    receivable.save(update_fields=[
        'doctor_share_paid_at', 'doctor_share_paid_amount', 'doctor_share_paid_by',
        'row_version', 'updated_at',
    ])
    record_audit_event(
        membership.user_id, receivable.tenant_id, 'finance.doctor_share_paid',
        object_type='receivable', object_id=receivable.id, outcome='success',
        integrity_metadata={
            'amount': str(receivable.doctor_share_paid_amount),
        },
    )
    return receivable


@transaction.atomic
def undo_doctor_share_paid(receivable, membership):
    receivable = _locked_receivable(receivable, membership)
    if receivable.doctor_share_paid_at is None:
        return receivable
    receivable.doctor_share_paid_at = None
    receivable.doctor_share_paid_amount = None
    receivable.doctor_share_paid_by = None
    receivable.row_version += 1
    receivable.save(update_fields=[
        'doctor_share_paid_at', 'doctor_share_paid_amount', 'doctor_share_paid_by',
        'row_version', 'updated_at',
    ])
    record_audit_event(
        membership.user_id, receivable.tenant_id, 'finance.doctor_share_reopened',
        object_type='receivable', object_id=receivable.id, outcome='success',
    )
    return receivable


@transaction.atomic
def archive_all_financial_history(tenant, membership):
    _assert_manager(membership, tenant.id)
    now = timezone.now()
    count = Receivable.objects.select_for_update().filter(
        tenant=tenant, archived_at__isnull=True,
    ).update(archived_at=now, archived_by=membership, updated_at=now)
    record_audit_event(
        membership.user_id, tenant.id, 'finance.history_archived',
        object_type='financial_history', object_id=None, outcome='success',
        integrity_metadata={'receivables': count},
    )
    return count


@transaction.atomic
def restore_all_financial_history(tenant, membership):
    _assert_manager(membership, tenant.id)
    now = timezone.now()
    count = Receivable.objects.select_for_update().filter(
        tenant=tenant, archived_at__isnull=False,
    ).update(archived_at=None, archived_by=None, updated_at=now)
    record_audit_event(
        membership.user_id, tenant.id, 'finance.history_restored',
        object_type='financial_history', object_id=None, outcome='success',
        integrity_metadata={'receivables': count},
    )
    return count


@transaction.atomic
def delete_all_financial_history(tenant, membership):
    _assert_manager(membership, tenant.id)
    receivables = Receivable.objects.select_for_update().filter(tenant=tenant)
    receivable_ids = list(receivables.values_list('id', flat=True))
    adjustments = FinancialAdjustment.objects.filter(tenant=tenant)
    payments = Payment.objects.filter(tenant=tenant)
    counts = {
        'adjustments': adjustments.count(),
        'payments': payments.count(),
        'receivables': len(receivable_ids),
    }
    adjustments.delete()
    payments.delete()
    Receivable.objects.filter(id__in=receivable_ids, tenant=tenant).delete()
    record_audit_event(
        membership.user_id, tenant.id, 'finance.history_permanently_deleted',
        object_type='financial_history', object_id=None, outcome='success',
        integrity_metadata=counts,
    )
    return counts
