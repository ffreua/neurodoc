"""A CID-11 entra na lista de sistemas de catálogo (1.44).

Só a lista de valores do campo muda; não há coluna nova nem dado tocado.
A carga da CID-11 não é feita aqui, pelo mesmo motivo da CID-10 — ver
`catalogs/provisioning.py`: quem provisiona é a subida, que confere o
estado e tenta de novo, e não uma migração que constaria como aplicada
mesmo se a leitura da planilha falhasse.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalogs', '0012_dominios_descartaveis'),
    ]

    operations = [
        migrations.AlterField(
            model_name='catalogrelease',
            name='system',
            field=models.CharField(
                choices=[
                    ('CID10', 'CID-10'), ('CID11', 'CID-11'), ('TUSS', 'TUSS'),
                    ('CMED', 'CMED/Anvisa (medicamentos)'),
                    ('P344', 'Portaria 344/98 (substâncias controladas)'),
                ],
                max_length=10,
            ),
        ),
    ]
