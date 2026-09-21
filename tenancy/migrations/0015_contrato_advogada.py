"""O que a redacao da advogada exige a mais do registro de aceite.

Escrita a mao a partir de `makemigrations --dry-run --verbosity 3`: o
sistema de arquivos do conteiner e somente leitura, entao o Django gera o
corpo e nos o gravamos aqui no host.

Separada da `0014`, e nao dobrada dentro dela, porque as tres colunas tem
uma origem que vale registrar: elas nasceram de clausulas do contrato, e
nao de uma ideia nossa.

- `text` -- clausula 2.3: "uma copia do conteudo contratual efetivamente
  aceito permanecera vinculada ao respectivo registro de contratacao". O
  hash sozinho prova que um texto e aquele texto, mas nao devolve o texto.
- `representation_declared` -- clausula 2.2, "i": declaracao de que o
  aceitante possui poderes para contratar em nome da CONTRATANTE.
- `price_annual_cents` -- clausula 2.2, "h": plano **e condicoes
  comerciais** aplicaveis.

Sem migracao de dados. Os aceites anteriores ficam sem copia e sem
declaracao de poderes, de proposito: preencher uma copia retroativa seria
arquivar como aceito um texto que aquela clinica nao viu, e marcar
poderes declarados seria inventar uma declaracao que ninguem fez. O
console mostra a lacuna, e ela se resolve no aceite da proxima versao.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0014_contractacceptance'),
    ]

    operations = [
        migrations.AddField(
            model_name='contractacceptance',
            name='price_annual_cents',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='contractacceptance',
            name='representation_declared',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='contractacceptance',
            name='text',
            field=models.TextField(blank=True),
        ),
    ]
