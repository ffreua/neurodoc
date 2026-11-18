"""O modelo das tarefas pesadas da IA da instalação. Ver o campo."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0003_installationsettings_reserva_de_ia'),
    ]

    operations = [
        migrations.AddField(
            model_name='installationsettings',
            name='ai_model_pesado',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
