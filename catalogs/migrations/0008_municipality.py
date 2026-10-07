import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    """Catalogo de municipios do IBGE, para a naturalidade do paciente.

    `expand`: tabela nova, nenhuma existente tocada. Nasce vazia e e
    preenchida por `import_municipios`, que roda no worker -- a busca
    devolve lista vazia enquanto isso, e o campo do paciente continua
    aceitando texto digitado.

    Referencia global, sem `tenant`: municipio do IBGE e o mesmo para
    todas as clinicas, como CID-10 e TUSS.
    """

    dependencies = [
        ('catalogs', '0007_alter_medicationproduct_substance'),
    ]

    operations = [
        migrations.CreateModel(
            name='Municipality',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('ibge_code', models.CharField(max_length=7, unique=True)),
                ('name', models.CharField(max_length=120)),
                ('name_ascii', models.CharField(max_length=120)),
                ('uf', models.CharField(max_length=2)),
            ],
            options={'ordering': ['name', 'uf']},
        ),
        migrations.AddIndex(
            model_name='municipality',
            index=models.Index(fields=['name_ascii'], name='catalogs_municipio_nome_idx'),
        ),
        migrations.AddIndex(
            model_name='municipality',
            index=models.Index(fields=['uf'], name='catalogs_municipio_uf_idx'),
        ),
    ]
