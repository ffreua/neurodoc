from crm.models import CRMCard
from finance.models import Receivable
from scheduling.models import Appointment

MAX_ROWS = 20


class ToolScopeError(Exception):
    pass


def get_crm_status(authorization):
    """Administrative-only: stage name, assignee, due date and the free-text
    administrative summary -- never a diagnosis, and never routed to a
    clinical encounter's own text fields (CRMCard carries no clinical
    field to begin with, see crm/models.py).
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    card = CRMCard.objects.filter(
        tenant_id=authorization.tenant_id, patient_id=authorization.patient_id,
    ).order_by('-created_at').first()
    if card is None:
        return None
    return {
        'stage': card.stage.name, 'assigned_to': card.assigned_membership_id is not None,
        'due_at': card.due_at.isoformat() if card.due_at else None,
        'administrative_summary': card.administrative_summary,
    }


def get_upcoming_appointments(authorization, limit=MAX_ROWS):
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    limit = min(int(limit), MAX_ROWS)
    appointments = Appointment.objects.filter(
        tenant_id=authorization.tenant_id, patient_id=authorization.patient_id,
    ).order_by('-starts_at')[:limit]
    return [
        {'starts_at': a.starts_at.isoformat(), 'status': a.status, 'type': a.type}
        for a in appointments
    ]


def get_billing_status(authorization, limit=MAX_ROWS):
    """Amounts and status only -- never the clinical encounter it
    originated from beyond its own id, and never a diagnosis/certificate.
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    limit = min(int(limit), MAX_ROWS)
    receivables = Receivable.objects.filter(
        tenant_id=authorization.tenant_id, patient_id=authorization.patient_id,
    ).order_by('-competence_date')[:limit]
    return [
        {
            'charge_kind': r.charge_kind, 'expected_amount': str(r.expected_amount),
            'charged_amount': str(r.charged_amount), 'status': r.status,
            'competence_date': r.competence_date.isoformat(),
        }
        for r in receivables
    ]
