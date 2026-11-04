"""Degustação do Completo (1.35, `tenancy/degustacao.py`).

Só acrescenta: dez colunas, todas aceitando vazio ou com padrão **no
banco** (`db_default`). Na janela da publicação a réplica antiga ainda
atende e grava clínica, convite e aceite sem conhecer estes campos; sem o
padrão no banco, esse INSERT daria erro — foi o caso da 0020/0021.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0021_tenant_cpf_db_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='contractacceptance',
            name='degustacao_ate',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='contractacceptance',
            name='degustacao_plano',
            field=models.CharField(blank=True, db_default='', default='', max_length=40),
        ),
        migrations.AddField(
            model_name='invitation',
            name='degustacao',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name='tenant',
            name='degustacao_ate',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tenant',
            name='degustacao_avisada_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tenant',
            name='degustacao_encerrada_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tenant',
            name='degustacao_inicio',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tenant',
            name='degustacao_medico_mantido',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='tenancy.membership'),
        ),
        migrations.AddField(
            model_name='tenant',
            name='degustacao_retirados',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name='tenant',
            name='degustacao_sms',
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
    ]
