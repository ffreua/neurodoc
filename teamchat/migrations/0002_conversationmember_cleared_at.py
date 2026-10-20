"""Até quando cada pessoa apagou a conversa (1.19).

Só acrescenta uma coluna que aceita vazio: a 1.18 continua rodando sobre o
banco migrado, e quem nunca apagou nada fica com o campo em branco.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teamchat', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversationmember',
            name='cleared_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
