"""O prazo configuravel vira uma escolha de barrar ou nao.

Escrita a mao a partir de `makemigrations --dry-run --verbosity 3`: o
sistema de arquivos do conteiner e somente leitura.

A `0016` tinha acabado de criar `patient_portal_max_months` com sete
opcoes -- 3, 4, 6, 9, 12, 15 e 18 meses. O prazo saiu porque ele brigava
com a propria tela: a Resolucao CFM n 2.314/2022, art. 6, 2, fixa
"intervalos nao superiores a 180 dias", e uma clinica que escolhesse doze
ou dezoito meses faria a tela de bloqueio citar uma resolucao que diz 180
dias logo acima do prazo que a contraria -- com o paciente lendo as duas
coisas na mesma folha.

Agora o prazo e o da norma, e o que se escolhe e barrar ou nao:

- `patient_portal_requires_recent_visit` na clinica, `default=True`, que e
  o comportamento que as duas normas sustentam.
- o mesmo campo no vinculo, **anulavel**, com tres estados: sim, nao, e
  nulo para "siga a clinica" -- e o nulo que permite o responsavel mudar
  o padrao e a mudanca valer para quem nao se manifestou.

Sem migracao de dados. A `0016` nao chegou a ser publicada, e o unico
banco que a aplicou e o de desenvolvimento: nao ha prazo escolhido por
ninguem para converter. Uma conversao "12 meses vira barrar=False"
inventaria uma decisao que nenhum medico tomou.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0016_janela_de_retorno_do_portal'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='clinicprofile',
            name='patient_portal_max_months',
        ),
        migrations.RemoveField(
            model_name='membership',
            name='patient_portal_max_months',
        ),
        migrations.AddField(
            model_name='clinicprofile',
            name='patient_portal_requires_recent_visit',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='membership',
            name='patient_portal_requires_recent_visit',
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
