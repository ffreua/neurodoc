from django.db import migrations, models


class Migration(migrations.Migration):
    """Naturalidade do paciente: país, cidade e UF de nascimento.

    `expand`: tres colunas com padrao, nenhuma linha existente tocada.

    **`birth_country` nasce com `default='BR'` e as fichas antigas ficam
    com string vazia**, e a diferenca e proposital. `AddField` com
    `default` preenche as linhas existentes -- o que diria, de todas as
    2.231 fichas ja cadastradas, que o paciente nasceu no Brasil. Ninguem
    declarou isso. O padrao vale para a ficha **nova**, onde e o palpite
    certo e a pessoa corrige se for o caso; para a ficha antiga, vazio e
    a verdade: nao se perguntou.

    Dai o `preserve_default=False` com `default=''` na operacao: o banco
    preenche o que ja existe com vazio, e o modelo segue com 'BR' para o
    que vier depois.
    """

    dependencies = [
        ('patients', '0011_ficha_vinda_de_outro_sistema'),
    ]

    operations = [
        migrations.AddField(
            model_name='patient',
            name='birth_country',
            field=models.CharField(blank=True, default='', max_length=2),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='patient',
            name='birth_city',
            field=models.CharField(blank=True, default='', max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='patient',
            name='birth_state',
            field=models.CharField(blank=True, default='', max_length=2),
            preserve_default=False,
        ),
    ]
