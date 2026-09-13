"""Estado comercial da organização: encerrada, e o motivo por escrito.

`suspended` já existia e não fazia nada fora do portal do paciente.
`closed` é novo, e a diferença entre os dois é a razão de existirem:
suspensa congela (lê, imprime, exporta; não escreve) e encerrada fecha a
porta. Nenhuma das duas apaga registro.

Nada muda para quem já está no banco: toda organização existente continua
`active`, e os dois campos novos nascem vazios.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0009_lead'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='status_changed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tenant',
            name='status_note',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='tenant',
            name='status',
            field=models.CharField(
                choices=[
                    ('active', 'Ativa'),
                    ('suspended', 'Suspensa (somente leitura)'),
                    ('closed', 'Encerrada'),
                ],
                default='active', max_length=40,
            ),
        ),
    ]
