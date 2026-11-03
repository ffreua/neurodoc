"""`failure` entra nas escolhas de `AuditEvent.outcome` (revisão de 2026-11-02).

Só o estado do Django muda: a coluna é `varchar(40)` sem CHECK, e as linhas
com `failure` já existem. Ver o comentário de `AuditOutcome.FAILURE`.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0003_auditevent_imutavel'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditevent',
            name='outcome',
            field=models.CharField(
                choices=[('success', 'Sucesso'), ('denied', 'Negado'), ('error', 'Erro'), ('failure', 'Falha')],
                max_length=40,
            ),
        ),
    ]
