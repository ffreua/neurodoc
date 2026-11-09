from django.db import migrations, models


class Migration(migrations.Migration):
    """Primeira consulta e seguimento (1.41): só acrescenta.

    Os dois campos nascem com padrão — `primeira` e evolução vazia —, que é
    exatamente como todo atendimento anterior foi escrito. Nenhuma linha é
    reescrita, e o hash dos finalizados não muda (ver
    `Encounter.compute_content_hash`).
    """

    dependencies = [
        ('clinical', '0012_migrados_fechados_na_data_do_iclin'),
    ]

    operations = [
        migrations.AddField(
            model_name='encounter',
            name='estrutura',
            field=models.CharField(
                choices=[('primeira', 'Primeira consulta'), ('seguimento', 'Seguimento e retorno')],
                default='primeira', max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='encounter',
            name='evolucao',
            field=models.TextField(blank=True, max_length=20000),
        ),
    ]
