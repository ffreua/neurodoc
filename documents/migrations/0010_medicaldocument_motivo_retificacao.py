"""Motivo da retificação no documento, e não na trilha. Ver o campo."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0009_pedido_de_exames_e_cirurgia'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicaldocument',
            name='motivo_retificacao',
            field=models.TextField(blank=True, default=''),
        ),
    ]
