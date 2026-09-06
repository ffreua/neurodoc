from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import Observation, ObservationKind


def age_at(birth_date, reference_date=None):
    if birth_date is None:
        return None
    reference_date = reference_date or timezone.now().date()
    years = reference_date.year - birth_date.year
    if (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def record_observation(context, patient, kind, numeric_value, unit, observed_at=None, source='manual'):
    observation = Observation(
        tenant_id=context.tenant_id,
        patient=patient,
        kind=kind,
        numeric_value=numeric_value,
        unit=unit,
        observed_at=observed_at or timezone.now(),
        source=source,
    )
    observation.full_clean()
    observation.save()
    return observation


def latest_observation(patient, kind):
    return (
        Observation.objects
        .filter(patient=patient, kind=kind)
        .order_by('-observed_at')
        .first()
    )


def compute_bmi(patient):
    weight = latest_observation(patient, ObservationKind.WEIGHT)
    height = latest_observation(patient, ObservationKind.HEIGHT)
    if weight is None or height is None or height.numeric_value == 0:
        return None
    bmi = weight.numeric_value / (height.numeric_value * height.numeric_value)
    return {
        'value': bmi.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP),
        'weight_kg': weight.numeric_value,
        'weight_observed_at': weight.observed_at,
        'height_m': height.numeric_value,
        'height_observed_at': height.observed_at,
    }
