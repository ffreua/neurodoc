"""Guarda, na ficha, de qual registro do sistema antigo ela veio.

Aditiva e sem efeito para quem já usa: coluna nova, vazia em toda ficha
existente, e a restrição de unicidade só vale para quem a tem preenchida.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0010_nome_em_caixa_alta'),
        ('tenancy', '0017_barrar_consulta_antiga'),
    ]

    operations = [
        migrations.AddField(
            model_name='patient',
            name='legacy_id',
            field=models.CharField(blank=True, db_index=True, max_length=60),
        ),
        migrations.AddConstraint(
            model_name='patient',
            constraint=models.UniqueConstraint(
                condition=models.Q(('legacy_id', ''), _negated=True),
                fields=('tenant', 'legacy_id'),
                name='patients_patient_tenant_legacy_id_uniq',
            ),
        ),
    ]
