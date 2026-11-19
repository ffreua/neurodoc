"""A clínica decide se a equipe pode confiar em dispositivo (2026-11-18).

Só expansão, com padrão no banco: toda clínica existente nasce **proibindo**,
que é o comportamento de hoje (o código pedido a cada entrada). Ver
`accounts/dispositivo_confiavel.py`.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0023_membership_agenda_por_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='dispositivo_confiavel_permitido',
            field=models.BooleanField(default=False, db_default=False),
        ),
    ]
