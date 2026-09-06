from clinical.models import Encounter, EncounterDiagnosis, ExaminationFinding

MAX_ENCOUNTERS = 20
MAX_FINDINGS = 100
MAX_DIAGNOSES = 50


class ToolScopeError(Exception):
    pass


def get_patient_timeline(authorization, limit=MAX_ENCOUNTERS):
    """Revalidates scope on every call -- an authorization without a
    patient in scope can never enumerate any patient's encounters, no
    matter what the caller (or a compromised prompt) asks for.
    """
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    limit = min(int(limit), MAX_ENCOUNTERS)
    encounters = Encounter.objects.filter(
        tenant_id=authorization.tenant_id, patient_id=authorization.patient_id,
    ).order_by('-occurred_at')[:limit]
    return [
        {
            'encounter_id': str(e.id), 'occurred_at': e.occurred_at.isoformat(), 'status': e.status,
            'chief_complaint': e.chief_complaint, 'hpi': e.hpi, 'plan_text': e.plan_text,
        }
        for e in encounters
    ]


def get_examination_findings(authorization, encounter_id, limit=MAX_FINDINGS):
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    encounter = Encounter.objects.filter(
        tenant_id=authorization.tenant_id, id=encounter_id, patient_id=authorization.patient_id,
    ).first()
    if encounter is None:
        raise ToolScopeError('Encounter is not in scope for this authorization')
    limit = min(int(limit), MAX_FINDINGS)
    findings = ExaminationFinding.objects.filter(
        tenant_id=authorization.tenant_id, encounter=encounter,
    ).order_by('domain', 'item_code')[:limit]
    return [
        {
            'domain': f.domain, 'item_code': f.item_code, 'side': f.side, 'state': f.state,
            'qualifier': f.qualifier, 'note': f.note,
        }
        for f in findings
    ]


def get_diagnoses(authorization, encounter_id, limit=MAX_DIAGNOSES):
    if authorization.patient_id is None:
        raise ToolScopeError('Authorization has no patient in scope')
    encounter = Encounter.objects.filter(
        tenant_id=authorization.tenant_id, id=encounter_id, patient_id=authorization.patient_id,
    ).first()
    if encounter is None:
        raise ToolScopeError('Encounter is not in scope for this authorization')
    limit = min(int(limit), MAX_DIAGNOSES)
    diagnoses = EncounterDiagnosis.objects.filter(
        tenant_id=authorization.tenant_id, encounter=encounter,
    ).order_by('rank')[:limit]
    return [
        {'code': d.code_snapshot, 'description': d.description_snapshot, 'certainty': d.certainty}
        for d in diagnoses
    ]
