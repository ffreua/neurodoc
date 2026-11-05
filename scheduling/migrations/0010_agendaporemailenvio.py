"""A agenda de amanhã por e-mail (1.36): o registro de cada envio.

Tabela nova, que o código anterior não lê nem escreve. O `UNIQUE` de
(médico, dia) é o que impede o segundo e-mail quando a tarefa roda duas
vezes (`scheduling/agenda_por_email.py`).
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0009_lista_de_espera'),
        ('tenancy', '0023_membership_agenda_por_email'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgendaPorEmailEnvio',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('dia', models.DateField()),
                ('horarios', models.PositiveIntegerField(default=0)),
                ('enviado_em', models.DateTimeField(blank=True, null=True)),
                ('erro', models.CharField(blank=True, max_length=255)),
                ('membership', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.membership')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.tenant')),
            ],
            options={
                'abstract': False,
                'constraints': [models.UniqueConstraint(fields=('tenant', 'id'), name='scheduling_agendaporemailenvio_tenant_id_uniq'), models.UniqueConstraint(fields=('membership', 'dia'), name='scheduling_agenda_email_unica')],
            },
        ),
    ]
