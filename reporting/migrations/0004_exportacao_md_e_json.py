"""Markdown e JSON entram como formatos de exportacao.

Escrita a mao a partir de `makemigrations --dry-run --verbosity 3`: o
sistema de arquivos do conteiner e somente leitura.

So mexe em `choices`, que nao existe no banco -- a coluna continua sendo
o mesmo `varchar(20)`. A migracao existe para o estado do Django nao
divergir do modelo, e nao porque haja tabela a alterar.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reporting', '0003_alter_reportdefinition_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reportexport',
            name='kind',
            field=models.CharField(
                choices=[
                    ('csv', 'CSV'), ('pdf', 'PDF'),
                    ('md', 'Markdown'), ('json', 'JSON'),
                ],
                max_length=20,
            ),
        ),
    ]
