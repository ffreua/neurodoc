"""O estado "enviando" da entrega (auditoria de 2026-10-09, ND-1121-016).

Só a lista de escolhas muda: a coluna continua `varchar(20)`, e nenhuma
linha existente é tocada.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('communications', '0008_delivery_canal_indisponivel'),
    ]

    operations = [
        migrations.AlterField(
            model_name='delivery',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Na fila'),
                    ('sending', 'Enviando'),
                    ('accepted', 'Aceita pelo provedor'),
                    ('delivered', 'Entregue'),
                    ('unknown', 'Sem confirmação'),
                    ('failed', 'Falhou'),
                    ('no_contact', 'Sem contato cadastrado'),
                    ('channel_unavailable', 'Canal indisponível'),
                    ('needs_reconciliation', 'Aguardando reconciliação'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
