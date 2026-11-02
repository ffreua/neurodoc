from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinical', '0010_encounter_neurological_exam_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='encounter',
            name='legacy_id',
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddConstraint(
            model_name='encounter',
            constraint=models.UniqueConstraint(
                condition=~models.Q(legacy_id=''), fields=('tenant', 'legacy_id'),
                name='clinical_encounter_tenant_legacy_id_uniq',
            ),
        ),
    ]
