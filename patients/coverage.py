from django.core.exceptions import ValidationError

from .models import HealthPlan, PatientCoverage


def add_coverage(context, patient, plan_id, member_number='', starts_on=None, ends_on=None):
    plan = HealthPlan.objects.filter(id=plan_id, tenant_id=context.tenant_id).first()
    if plan is None:
        raise ValidationError('Plan does not belong to this tenant')
    coverage = PatientCoverage(
        tenant_id=context.tenant_id, patient=patient, plan=plan,
        member_number=member_number, starts_on=starts_on, ends_on=ends_on,
    )
    coverage.full_clean()
    coverage.save()
    return coverage
