"""Padrão no banco para `Tenant.cpf` (revisão de 2026-11-02).

A 0020 criou a coluna NOT NULL sem padrão no banco — o Django apaga o
padrão depois do `AddField`. O código anterior à 1.32, que não conhece o
campo, faz INSERT sem ele: na janela da publicação (a réplica antiga ainda
atende) ou depois de um rollback, todo cadastro de organização dava erro
500. Com `db_default`, o banco preenche o vazio.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0020_tenant_cpf'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenant',
            name='cpf',
            field=models.CharField(blank=True, db_default='', default='', max_length=11),
        ),
    ]
