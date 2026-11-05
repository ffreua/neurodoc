"""A agenda de amanhã por e-mail (1.36): a opção, ligada por padrão.

Só acrescenta, com padrão **no banco**: a réplica antiga, que não conhece o
campo, segue criando vínculo na janela da publicação (ver a 0021).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0022_degustacao'),
    ]

    operations = [
        migrations.AddField(
            model_name='membership',
            name='agenda_por_email',
            field=models.BooleanField(db_default=True, default=True),
        ),
    ]
