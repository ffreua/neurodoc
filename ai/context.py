import dataclasses
import uuid

from clinical.models import Encounter
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus


class AIAuthorizationDenied(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class AIAuthorization:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    patient_id: uuid.UUID | None
    encounter_id: uuid.UUID | None


def build_ai_authorization(access_context, patient_id=None, encounter_id=None):
    """Re-validated from the database every time an AI job is created *and*
    again right before a Celery task actually does any work -- a
    membership revoked between enqueue and execution, or a patient_id that
    doesn't belong to this tenant, must never let data into the job.
    """
    membership = Membership.objects.filter(
        id=access_context.membership_id, tenant_id=access_context.tenant_id, status=MembershipStatus.ACTIVE,
    ).first()
    if membership is None:
        raise AIAuthorizationDenied('Membership is not active in this tenant')

    patient = None
    if patient_id:
        patient = Patient.objects.filter(tenant_id=access_context.tenant_id, id=patient_id).first()
        if patient is None:
            raise AIAuthorizationDenied('Patient does not belong to this tenant')

    encounter = None
    if encounter_id:
        encounter = Encounter.objects.filter(tenant_id=access_context.tenant_id, id=encounter_id).first()
        if encounter is None:
            raise AIAuthorizationDenied('Encounter does not belong to this tenant')
        if patient is not None and encounter.patient_id != patient.id:
            raise AIAuthorizationDenied('Encounter does not belong to the given patient')

    return AIAuthorization(
        tenant_id=access_context.tenant_id, user_id=access_context.user_id, membership_id=membership.id,
        patient_id=patient.id if patient else None, encounter_id=encounter.id if encounter else None,
    )
