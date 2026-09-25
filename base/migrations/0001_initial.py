"""A configuracao da instalacao que se vira sem deploy.

Escrita a mao a partir de `makemigrations --dry-run --verbosity 3`: o
sistema de arquivos do conteiner e somente leitura.

Primeira migration do app `base` -- ate aqui ele so tinha modelos
abstratos (`TimestampedModel`, `TenantModel`), que nao criam tabela.

A tabela guarda **uma linha**, garantida pelo `unique=True` num campo de
valor fixo. Duas chaves moram nela: a lista de enderecos de API liberados e
o interruptor do ensaio da coleta de lixo. As duas existiam so no `.env`,
e o defeito disso nao e conveniencia -- e que **desligar demorava um ciclo
de deploy**. Trava que so se solta republicando nao serve de freio de
emergencia.
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InstallationSettings',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('singleton', models.BooleanField(default=True, editable=False, unique=True)),
                ('ai_base_url_allowlist', models.TextField(blank=True)),
                ('documents_gc_dry_run', models.BooleanField(default=True)),
                ('documents_gc_note', models.CharField(blank=True, max_length=255)),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'configuração da instalação',
                'verbose_name_plural': 'configurações da instalação',
            },
        ),
    ]
