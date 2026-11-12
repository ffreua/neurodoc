"""A página seguinte do rascunho da TUSS, guardada em vez de deduzida.

Coluna nova e nula: nenhum dado tocado, nenhuma leitura antiga quebra.
Ver o comentário do campo em `catalogs/models.py`.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalogs', '0013_cid11'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogrelease',
            name='proxima_pagina',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
