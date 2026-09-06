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


def set_patient_coverage(context, patient, plan_id, member_number='', starts_on=None, ends_on=None):
    """Garante a cobertura informada no cadastro e a marca como a ativa.

    Reaproveita a cobertura que já existe para o mesmo plano em vez de
    empilhar uma duplicata a cada edição do cadastro — o histórico
    financeiro resolve a cobertura por data (`finance.receivables`), e duas
    linhas do mesmo plano tornariam esse resultado ambíguo.
    """
    plan = HealthPlan.objects.filter(id=plan_id, tenant_id=context.tenant_id).first()
    if plan is None:
        raise ValidationError('Plan does not belong to this tenant')
    coverage = patient.coverages.filter(plan=plan).order_by('-created_at').first()
    if coverage is None:
        coverage = PatientCoverage(tenant_id=context.tenant_id, patient=patient, plan=plan)
    coverage.member_number = member_number
    coverage.starts_on = starts_on
    coverage.ends_on = ends_on
    coverage.full_clean()
    coverage.save()
    if patient.active_coverage_id != coverage.id:
        patient.active_coverage = coverage
        patient.save(update_fields=['active_coverage', 'updated_at'])
    return coverage
