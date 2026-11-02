"""CNPJ ou CPF na organização (2026-11).

O `UNIQUE` simples do `cnpj` sai e volta como restrição parcial (só sobre o
que não está vazio), porque a organização de pessoa física tem `cnpj`
vazio — e duas vazias não podem colidir. A terceira restrição garante que
há exatamente um dos dois. Toda organização existente tem CNPJ, então as
três valem sobre os dados de hoje sem tocar em linha nenhuma.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0019_periodicidade_do_pagamento'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenant',
            name='cnpj',
            field=models.CharField(blank=True, max_length=14),
        ),
        migrations.AddField(
            model_name='tenant',
            name='cpf',
            field=models.CharField(blank=True, default='', max_length=11),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name='tenant',
            constraint=models.UniqueConstraint(
                condition=models.Q(('cnpj', ''), _negated=True), fields=('cnpj',),
                name='tenant_cnpj_unico',
                violation_error_message='Este CNPJ já está cadastrado em outra clínica.',
            ),
        ),
        migrations.AddConstraint(
            model_name='tenant',
            constraint=models.UniqueConstraint(
                condition=models.Q(('cpf', ''), _negated=True), fields=('cpf',),
                name='tenant_cpf_unico',
                violation_error_message='Este CPF já está cadastrado em outra organização.',
            ),
        ),
        migrations.AddConstraint(
            model_name='tenant',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(models.Q(('cnpj', ''), _negated=True), ('cpf', '')),
                    models.Q(('cnpj', ''), models.Q(('cpf', ''), _negated=True)),
                    _connector='OR',
                ),
                name='tenant_cnpj_ou_cpf',
                violation_error_message='Informe o CNPJ ou o CPF da organização — um dos dois, e só um.',
            ),
        ),
    ]
