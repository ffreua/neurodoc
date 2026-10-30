"""Vigência por código TUSS (1.30): duas colunas nulas, aditivas.

Releases antigas ficam com as datas nulas — a sincronização da época as
descartava, e inventá-las agora seria pior que admitir que não existem.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalogs', '0009_portaria344'),
    ]

    operations = [
        migrations.AddField(
            model_name='procedurecode',
            name='starts_on',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='procedurecode',
            name='ends_on',
            field=models.DateField(blank=True, null=True),
        ),
    ]
