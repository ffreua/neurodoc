from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0006_historico_financeiro'),
    ]

    operations = [
        migrations.AddField(
            model_name='receivable',
            name='doctor_share_paid_amount',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=12, null=True,
            ),
        ),
    ]
