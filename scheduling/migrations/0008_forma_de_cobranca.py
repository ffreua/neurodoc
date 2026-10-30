"""Forma de cobranca por agendamento (1.30). Aditiva: vazio = nao informado, a regra antiga."""

import django.db.models.deletion
from django.db import migrations, models

from base.db import composite_tenant_foreign_key


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0013_naturalidade_padrao_brasil'),
        ('scheduling', '0007_duracao_segue_o_tipo'),
        ('tenancy', '0018_tiss_liberado'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='billing_mode',
            field=models.CharField(blank=True, choices=[('private', 'Particular'), ('insurance', 'Convênio')], default='', max_length=12, verbose_name='forma de cobrança'),
        ),
        migrations.AddField(
            model_name='appointment',
            name='coverage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='patients.patientcoverage'),
        ),
        migrations.AddConstraint(
            model_name='appointment',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('billing_mode', 'insurance'), ('coverage__isnull', False)), models.Q(models.Q(('billing_mode', 'insurance'), _negated=True), ('coverage__isnull', True)), _connector='OR'), name='scheduling_appointment_billing_coverage'),
        ),
        composite_tenant_foreign_key(
            'scheduling_appointment', 'coverage_id', 'patients_patientcoverage',
            'scheduling_appointment_tenant_coverage_fk',
        ),
    ]
