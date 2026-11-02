"""Domínios de e-mail descartável e o estado da lista (2026-11)."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalogs', '0011_operadoras_ans'),
    ]

    operations = [
        migrations.CreateModel(
            name='DominioDescartavel',
            fields=[
                ('dominio', models.CharField(max_length=253, primary_key=True, serialize=False)),
            ],
            options={
                'verbose_name': 'domínio de e-mail descartável',
                'verbose_name_plural': 'domínios de e-mail descartáveis',
            },
        ),
        migrations.CreateModel(
            name='ListaDominiosDescartaveis',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('singleton', models.BooleanField(default=True, editable=False, unique=True)),
                ('total', models.PositiveIntegerField(default=0)),
                ('atualizada_em', models.DateTimeField(blank=True, null=True)),
                ('ultima_tentativa_em', models.DateTimeField(blank=True, null=True)),
                ('ultimo_erro', models.TextField(blank=True)),
                ('liberados', models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'lista de domínios descartáveis',
                'verbose_name_plural': 'lista de domínios descartáveis',
            },
        ),
    ]
