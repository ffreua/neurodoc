import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0005_backfill_cobrancas_checkin'),
    ]

    operations = [
        migrations.AddField(
            model_name='receivable',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='receivable',
            name='archived_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='+', to='tenancy.membership',
            ),
        ),
        migrations.AddField(
            model_name='receivable',
            name='doctor_share_paid_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='receivable',
            name='doctor_share_paid_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='+', to='tenancy.membership',
            ),
        ),
        migrations.AddField(
            model_name='receivable',
            name='fiscal_document_number',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddIndex(
            model_name='receivable',
            index=models.Index(
                fields=['tenant', 'archived_at', 'doctor_share_paid_at', 'competence_date'],
                name='fin_recv_visible_comp_idx',
            ),
        ),
    ]
