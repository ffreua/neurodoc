"""Marca de teleatendimento no agendamento (1.43).

Aditiva: a coluna nasce falsa em todo horário que já existe, e com o padrão
**no banco** -- a versão anterior do código, que não conhece o campo,
continua marcando horário durante a troca de versão e depois de um rollback.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0010_agendaporemailenvio'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='teleatendimento',
            field=models.BooleanField(db_default=False, default=False, verbose_name='teleatendimento'),
        ),
    ]
