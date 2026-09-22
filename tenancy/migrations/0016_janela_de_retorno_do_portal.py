"""Ate quando a ultima consulta ainda autoriza um pedido pelo portal.

Escrita a mao a partir de `makemigrations --dry-run --verbosity 3`: o
sistema de arquivos do conteiner e somente leitura.

Dois campos, e a diferenca entre eles e o ponto:

- `ClinicProfile.patient_portal_max_months` -- o padrao da clinica, com
  `default=6`. Clinica que ja tinha o portal ligado passa a valer seis
  meses sem ninguem configurar nada, que e o comportamento seguro: sem
  padrao, o portal continuaria aceitando pedido de quem nao consulta ha
  cinco anos.
- `Membership.patient_portal_max_months` -- a janela do medico para os
  pacientes dele, **nula** por padrao. Nulo significa "siga a clinica", e
  e o que permite o dono mudar o padrao e a mudanca valer para quem nao
  se manifestou. Preencher tudo com 6 aqui congelaria cada medico no
  valor de hoje.
"""
from django.db import migrations, models

ESCOLHAS = [
    (3, '3 meses'), (4, '4 meses'), (6, '6 meses'), (9, '9 meses'),
    (12, '12 meses'), (15, '15 meses'), (18, '18 meses'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0015_contrato_advogada'),
    ]

    operations = [
        migrations.AddField(
            model_name='clinicprofile',
            name='patient_portal_max_months',
            field=models.PositiveSmallIntegerField(choices=ESCOLHAS, default=6),
        ),
        migrations.AddField(
            model_name='membership',
            name='patient_portal_max_months',
            field=models.PositiveSmallIntegerField(blank=True, choices=ESCOLHAS, null=True),
        ),
    ]
