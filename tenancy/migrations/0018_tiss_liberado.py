"""Liberação do faturamento TISS por clínica (1.30). Aditiva: nasce `False`."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0017_barrar_consulta_antiga'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='tiss_liberado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenant',
            name='tiss_nota',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
