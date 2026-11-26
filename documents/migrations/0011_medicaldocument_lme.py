from django.db import migrations, models


class Migration(migrations.Migration):
    """O tipo de documento LME (laudo do medicamento de alto custo, CEAF).

    `expand`: só as opções do campo mudam (nenhuma DDL — `choices` não
    existe no banco). A versão anterior continua lendo a tabela; uma LME
    aberta por ela só não teria o PDF redesenhado.
    """

    dependencies = [
        ('documents', '0010_medicaldocument_motivo_retificacao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='medicaldocument',
            name='kind',
            field=models.CharField(choices=[('prescription', 'Receita'), ('report', 'Relatório'), ('request', 'Pedido de exame'), ('referral', 'Encaminhamento'), ('exam_request', 'Pedido de exames'), ('surgery_request', 'Solicitação de cirurgia'), ('lme', 'LME — medicamento especializado')], max_length=40),
        ),
    ]
