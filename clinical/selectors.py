from django.http import Http404

from tenancy.selectors import scope_to_tenant

from .models import Encounter


def patient_timeline(context, patient):
    """Chronological encounters for this patient, scoped to the tenant.

    Clinical access-grant scoping (PatientAccessGrant) is not modeled yet;
    tenant scoping plus the caller's own view-level permission check are the
    isolation boundary until that model exists.
    """
    return (
        scope_to_tenant(Encounter.objects.all(), context)
        .filter(patient=patient)
        .select_related('physician_membership__user')
        .order_by('occurred_at')
    )


def get_encounter_or_404(context, encounter_id):
    encounter = scope_to_tenant(Encounter.objects.all(), context).filter(id=encounter_id).first()
    if encounter is None:
        raise Http404
    return encounter
