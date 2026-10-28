from django.db import migrations, models


class Migration(migrations.Migration):
    """Dois tipos de documento novos, que nascem de modelo: pedido de
    exames por categoria e solicitação de cirurgia.

    `expand`: só as opções do campo mudam (nenhuma DDL — `choices` não
    existe no banco). A versão anterior continua lendo a tabela; um
    documento dos tipos novos aberto por ela só não teria o PDF redesenhado.
    """

    dependencies = [
        ('documents', '0008_laudos_enviados_pelo_portal'),
    ]

    operations = [
        migrations.AlterField(
            model_name='medicaldocument',
            name='kind',
            field=models.CharField(choices=[('prescription', 'Receita'), ('report', 'Relatório'), ('request', 'Pedido de exame'), ('referral', 'Encaminhamento'), ('exam_request', 'Pedido de exames'), ('surgery_request', 'Solicitação de cirurgia')], max_length=40),
        ),
    ]
