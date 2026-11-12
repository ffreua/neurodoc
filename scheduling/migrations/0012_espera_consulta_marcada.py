"""A espera que aponta a consulta já marcada a antecipar (2026-11-12).

Aditiva e anulável: toda espera que já existe nasce sem consulta marcada,
que é exatamente o que ela era. A versão anterior do código não conhece a
coluna e continua funcionando durante a troca de versão e depois de um
rollback.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0011_teleatendimento'),
    ]

    operations = [
        migrations.AddField(
            model_name='pacienteemespera',
            name='consulta_marcada',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='esperas_para_antecipar', to='scheduling.appointment',
            ),
        ),
    ]
