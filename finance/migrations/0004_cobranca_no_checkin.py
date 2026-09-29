import django.db.models.deletion
from django.db import migrations, models

from base.db import composite_tenant_foreign_key


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
