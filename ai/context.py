import dataclasses
import uuid

from clinical.models import Encounter
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus
from tenancy.plans import has_clinical_ai, plan_label


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
    membership = (
        Membership.objects
        .select_related('tenant')
        .filter(
            id=access_context.membership_id, tenant_id=access_context.tenant_id,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )
    if membership is None:
        raise AIAuthorizationDenied('Seu vínculo com esta clínica não está ativo.')
    # O plano da clinica, conferido aqui e nao so na tela.
    #
    # Esta funcao e o ponto por onde passa **todo** trabalho de IA: a
    # criacao do job, a reconferencia imediatamente antes da chamada ao
    # provedor, e o resumo automatico de `ai/handlers.py` -- que nasce de
    # um evento, sem tela nenhuma e sem ninguem clicando. Deixar o gate so
    # em `capabilities_for` fecharia as portas que tem tela e deixaria
    # aquela aberta, gastando a chave da instalacao numa clinica que nao
    # contratou a IA.
    #
    # E, pela mesma razao que o vinculo e relido aqui, o plano tambem: um
    # rebaixamento entre enfileirar e executar e o mesmo caso de um vinculo
    # revogado no meio, e a ultima chance de recusar e esta.
    if not has_clinical_ai(membership.tenant.plan):
        raise AIAuthorizationDenied(
            f'O plano {plan_label(membership.tenant.plan)} não inclui o apoio clínico por IA.'
        )

    patient = None
    if patient_id:
        patient = Patient.objects.filter(tenant_id=access_context.tenant_id, id=patient_id).first()
        if patient is None:
            raise AIAuthorizationDenied('Este paciente não é desta clínica.')

    encounter = None
    if encounter_id:
        encounter = Encounter.objects.filter(tenant_id=access_context.tenant_id, id=encounter_id).first()
        if encounter is None:
            raise AIAuthorizationDenied('Este atendimento não é desta clínica.')
        if patient is not None and encounter.patient_id != patient.id:
            raise AIAuthorizationDenied('Este atendimento não é deste paciente.')

    return AIAuthorization(
        tenant_id=access_context.tenant_id, user_id=access_context.user_id, membership_id=membership.id,
        patient_id=patient.id if patient else None, encounter_id=encounter.id if encounter else None,
    )
