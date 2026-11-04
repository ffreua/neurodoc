from django.db import migrations, models

TIPOS = [
    ('RCE', 'Receita de Controle Especial'),
    ('RET', 'Receita Sujeita à Retenção'),
    ('NRA', 'Notificação de Receita A'),
    ('NRB', 'Notificação de Receita B'),
    ('NRB2', 'Notificação de Receita B2'),
]


class Migration(migrations.Migration):
    """Notificação de Receita A, B e B2 (1.34).

    `expand`: o tipo passa de 3 para 4 caracteres ("NRB2") — no PostgreSQL,
    alargar um `varchar` não reescreve a tabela — e entram três colunas que
    aceitam vazio. O código anterior continua funcionando com o esquema
    novo durante a troca das réplicas. Ver `docs/sncr/DECISOES.md`, D9.
    """

    dependencies = [
        ('sncr', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pedidonumeracao', name='tipo',
            field=models.CharField(choices=TIPOS, max_length=4),
        ),
        migrations.AlterField(
            model_name='bloconumeracao', name='tipo',
            field=models.CharField(choices=TIPOS, max_length=4),
        ),
        migrations.AlterField(
            model_name='numerosncr', name='tipo',
            field=models.CharField(choices=TIPOS, max_length=4),
        ),
        migrations.AlterField(
            model_name='pedidonumeracao', name='cnpj',
            field=models.CharField(blank=True, max_length=14),
        ),
        migrations.AlterField(
            model_name='pedidonumeracao', name='estado',
            field=models.CharField(choices=[
                ('aguardando_login', 'Aguardando o login no Gov.br'),
                ('enviando', 'Enviando à Anvisa'),
                ('concluido', 'Bloco recebido'),
                ('recusado', 'Recusado pela Anvisa'),
                ('falhou', 'Não enviado'),
                ('incerto', 'Resultado incerto'),
                ('expirado', 'Login não concluído'),
                ('perdido', 'Dado por perdido'),
            ], default='aguardando_login', max_length=20),
        ),
        migrations.AddField(
            model_name='pedidonumeracao', name='quantidade',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='bloconumeracao', name='saldo_visa',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='saldo na Vigilância Sanitária'),
        ),
    ]
