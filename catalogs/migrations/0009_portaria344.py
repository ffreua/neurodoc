import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Lista oficial das substâncias controladas (Portaria SVS/MS 344/1998).

    `expand`: duas tabelas novas e um valor novo na escolha do sistema do
    catálogo (só metadado; nenhuma linha existente muda). Nascem vazias e
    são preenchidas por `import_portaria344`, que roda no worker. Nada no
    NeuroDoc as consulta ainda: é a base da classificação da receita
    eletrônica do SNCR (decisão D7, `docs/sncr/DECISOES.md`).

    Referência global, sem `tenant`, como CID-10, TUSS e CMED.
    """

    dependencies = [
        ('catalogs', '0008_municipality'),
    ]

    operations = [
        migrations.AlterField(
            model_name='catalogrelease',
            name='system',
            field=models.CharField(choices=[
                ('CID10', 'CID-10'), ('TUSS', 'TUSS'), ('CMED', 'CMED/Anvisa (medicamentos)'),
                ('P344', 'Portaria 344/98 (substâncias controladas)'),
            ], max_length=10),
        ),
        migrations.CreateModel(
            name='ControlledList',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('code', models.CharField(max_length=4, verbose_name='lista')),
                ('title', models.CharField(blank=True, max_length=300, verbose_name='título')),
                ('receituario', models.CharField(max_length=40, verbose_name='receituário')),
                ('receituario_texto', models.CharField(blank=True, max_length=300, verbose_name='receituário (texto do anexo)')),
                ('adendo', models.TextField(blank=True, verbose_name='adendo')),
                ('position', models.PositiveSmallIntegerField(default=0, verbose_name='ordem')),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='controlled_lists', to='catalogs.catalogrelease')),
            ],
            options={
                'verbose_name': 'lista de substâncias controladas',
                'verbose_name_plural': 'listas de substâncias controladas',
                'constraints': [models.UniqueConstraint(fields=('release', 'code'), name='catalogs_controlledlist_release_code_uniq')],
            },
        ),
        migrations.CreateModel(
            name='ControlledSubstance',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('number', models.PositiveSmallIntegerField(verbose_name='número na lista')),
                ('name', models.CharField(max_length=500, verbose_name='substância')),
                ('synonyms', models.TextField(blank=True, verbose_name='sinônimos')),
                ('search_text', models.TextField(blank=True, default='')),
                ('controlled_list', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='substances', to='catalogs.controlledlist')),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='controlled_substances', to='catalogs.catalogrelease')),
            ],
            options={
                'verbose_name': 'substância controlada',
                'verbose_name_plural': 'substâncias controladas',
                'constraints': [models.UniqueConstraint(fields=('controlled_list', 'number'), name='catalogs_controlledsubstance_list_number_uniq')],
            },
        ),
    ]
