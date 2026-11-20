"""As telas que passaram do limite de tempo, para o console. Ver `TelaLenta`."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0004_installationsettings_modelo_pesado'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelaLenta',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('criada_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('rota', models.CharField(max_length=150)),
                ('metodo', models.CharField(max_length=10)),
                ('status', models.PositiveSmallIntegerField()),
                ('milissegundos', models.PositiveIntegerField()),
                ('consultas', models.PositiveIntegerField()),
            ],
            options={
                'indexes': [models.Index(fields=['rota', 'criada_em'], name='base_telalenta_rota_idx')],
            },
        ),
    ]
