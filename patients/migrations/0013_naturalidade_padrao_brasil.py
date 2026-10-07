from django.db import migrations, models


class Migration(migrations.Migration):
    """Alinha o estado da coluna `birth_country` com o do modelo.

    Nao e cosmetica de `makemigrations`: as duas migrations juntas dizem
    exatamente o que se quis.

    A 0012 criou a coluna com `default=''` e `preserve_default=False`,
    para que as 2.231 fichas ja cadastradas ficassem **vazias** -- dizer
    'BR' nelas seria afirmar, em nome de pacientes reais, uma
    naturalidade que ninguem declarou.

    Esta aqui poe o padrao do modelo de volta (`'BR'`), que vale dali em
    diante: na ficha nova, Brasil e o palpite certo em praticamente todo
    cadastro, e quem nasceu fora corrige no mesmo campo.

    Nao toca em linha nenhuma: `default` do Django e aplicado pela
    aplicacao, nao pelo banco.
    """

    dependencies = [
        ('patients', '0012_naturalidade'),
    ]

    operations = [
        migrations.AlterField(
            model_name='patient',
            name='birth_country',
            field=models.CharField(blank=True, default='BR', max_length=2),
        ),
    ]
