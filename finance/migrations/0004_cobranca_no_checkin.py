import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone

from base.db import composite_tenant_foreign_key


def backfill_checkins(apps, schema_editor):
    """Liga pares inequívocos e cobra check-ins já realizados, sem duplicar."""
    AppointmentState = apps.get_model('scheduling', 'Appointment')
    EncounterState = apps.get_model('clinical', 'Encounter')
    ReceivableState = apps.get_model('finance', 'Receivable')

    appointment_ids = AppointmentState.objects.filter(
        status__in=['checked_in', 'in_progress', 'completed'],
    ).values_list('id', flat=True)
    for appointment_id in appointment_ids.iterator():
        appointment = AppointmentState.objects.get(id=appointment_id)
        candidates = EncounterState.objects.filter(
            tenant_id=appointment.tenant_id,
            patient_id=appointment.patient_id,
            physician_membership_id=appointment.physician_membership_id,
            appointment_id__isnull=True,
            occurred_at__date=timezone.localtime(appointment.starts_at).date(),
        )
        if candidates.count() == 1:
            encounter = candidates.first()
            EncounterState.objects.filter(id=encounter.id).update(appointment_id=appointment.id)
        else:
            encounter = EncounterState.objects.filter(appointment_id=appointment.id).first()
        if encounter is not None:
            ReceivableState.objects.filter(
                tenant_id=appointment.tenant_id,
                encounter_id=encounter.id,
                appointment_id__isnull=True,
            ).update(appointment_id=appointment.id)

    # Usa a mesma resolução de honorário do fluxo online. Nesta migração o
    # esquema novo já existe, portanto o modelo corrente é compatível.
    from finance.receivables import create_receivable_for_appointment
    from scheduling.models import Appointment

    for appointment in Appointment.objects.filter(
        status__in=['checked_in', 'in_progress', 'completed'],
    ).select_related('tenant', 'patient', 'physician_membership').iterator():
        create_receivable_for_appointment(appointment, actor_id=None)


def reverse_backfill(apps, schema_editor):
    Receivable = apps.get_model('finance', 'Receivable')
    appointment_only = Receivable.objects.filter(encounter_id__isnull=True)
    if appointment_only.filter(payments__isnull=False).exists():
        raise RuntimeError('Não é seguro reverter: há pagamento em cobrança originada no check-in.')
    appointment_only.delete()


class Migration(migrations.Migration):
    dependencies = [
        ('clinical', '0009_fk_composta_por_inquilino'),
        ('finance', '0003_tipo_de_atendimento_no_honorario'),
        ('scheduling', '0003_alter_appointment_type_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='receivable',
            name='finance_receivable_origin_uniq',
        ),
        migrations.AlterField(
            model_name='receivable',
            name='encounter',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='receivables', to='clinical.encounter',
            ),
        ),
        migrations.AddField(
            model_name='receivable',
            name='appointment',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='receivables', to='scheduling.appointment',
            ),
        ),
        migrations.RunPython(backfill_checkins, reverse_backfill),
        migrations.AddConstraint(
            model_name='receivable',
            constraint=models.CheckConstraint(
                condition=models.Q(('encounter__isnull', False), ('appointment__isnull', False), _connector='OR'),
                name='finance_receivable_has_origin',
            ),
        ),
        migrations.AddConstraint(
            model_name='receivable',
            constraint=models.UniqueConstraint(
                condition=models.Q(('encounter__isnull', False)),
                fields=('tenant', 'encounter', 'charge_kind'),
                name='finance_receivable_encounter_uniq',
            ),
        ),
        migrations.AddConstraint(
            model_name='receivable',
            constraint=models.UniqueConstraint(
                condition=models.Q(('appointment__isnull', False)),
                fields=('tenant', 'appointment', 'charge_kind'),
                name='finance_receivable_appointment_uniq',
            ),
        ),
        composite_tenant_foreign_key(
            'finance_receivable', 'appointment_id', 'scheduling_appointment',
            'finance_receivable_tenant_appointment_fk',
        ),
    ]
