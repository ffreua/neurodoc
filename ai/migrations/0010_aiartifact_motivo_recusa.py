"""Motivo da recusa no rascunho da IA, e não na trilha. Ver o campo."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0009_aposenta_leitura_de_laudo'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiartifact',
            name='motivo_recusa',
            field=models.TextField(blank=True, default=''),
        ),
    ]
