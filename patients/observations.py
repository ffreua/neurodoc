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


#: Faixas do IMC pela classificação da OMS para **adulto**. Não se aplicam a
#: criança e adolescente, que usam percentil por idade e sexo — por isso a
#: faixa não é exibida quando o paciente tem menos de 20 anos: mostrar
#: "obesidade" para uma criança de 8 anos seria uma leitura errada com cara
#: de laudo.
BMI_BANDS = (
    (Decimal('18.5'), 'Abaixo do peso', 'warning'),
    (Decimal('25'), 'Peso adequado', 'success'),
    (Decimal('30'), 'Sobrepeso', 'warning'),
    (Decimal('35'), 'Obesidade grau I', 'warning'),
    (Decimal('40'), 'Obesidade grau II', 'warning'),
    (None, 'Obesidade grau III', 'warning'),
)

ADULT_BAND_MIN_AGE = 20


def bmi_band(value, age_years):
    """Faixa e tom do IMC, ou `(None, None)` quando não se deve classificar."""
    if value is None or age_years is None or age_years < ADULT_BAND_MIN_AGE:
        return None, None
    for ceiling, label, tone in BMI_BANDS:
        if ceiling is None or value < ceiling:
            return label, tone
    return None, None


def compute_bmi(patient):
    weight = latest_observation(patient, ObservationKind.WEIGHT)
    height = latest_observation(patient, ObservationKind.HEIGHT)
    if weight is None or height is None or height.numeric_value == 0:
        return None
    bmi = (weight.numeric_value / (height.numeric_value * height.numeric_value)).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP,
    )
    band, tone = bmi_band(bmi, age_at(patient.birth_date))
    return {
        'value': bmi,
        'band': band,
        'tone': tone,
        'weight_kg': weight.numeric_value,
        'weight_observed_at': weight.observed_at,
        'height_m': height.numeric_value,
        'height_observed_at': height.observed_at,
    }


def missing_measurement_hint(patient):
    """Diz **o que** falta para o IMC, em vez de "insuficientes".

    A ficha dizia "peso/altura insuficientes", que não informa se falta o
    peso, a altura ou os dois — e é justamente o que quem está com o paciente
    na frente precisa saber para medir.
    """
    weight = latest_observation(patient, ObservationKind.WEIGHT)
    height = latest_observation(patient, ObservationKind.HEIGHT)
    if weight is None and height is None:
        return 'peso e altura não registrados'
    if weight is None:
        return 'falta o peso'
    if height is None:
        return 'falta a altura'
    return ''
