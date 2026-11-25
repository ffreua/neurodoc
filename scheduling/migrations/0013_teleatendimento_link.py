"""Link do vídeo do teleatendimento (1.58).

Aditiva: a coluna nasce vazia em todo horário que já existe, e com o padrão
**no banco** -- a versão anterior do código, que não conhece o campo,
continua marcando horário durante a troca de versão e depois de um rollback,
como na marca de teleatendimento (0011).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0012_espera_consulta_marcada'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='teleatendimento_link',
            field=models.URLField(
                blank=True, db_default='', default='', max_length=500,
                verbose_name='link do vídeo',
            ),
        ),
    ]
