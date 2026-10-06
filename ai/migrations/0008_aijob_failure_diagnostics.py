from django.db import migrations, models


class Migration(migrations.Migration):
    """Guarda por que a saída da IA foi recusada, em termos de forma.

    `expand`: acrescenta uma coluna com padrão, não toca em linha
    existente e não remove nada. Job antigo fica com `{}`, que é o mesmo
    que a tela trata como "sem detalhe técnico" — nenhuma retroescrita é
    necessária nem desejável, porque a forma da resposta daqueles jobs se
    perdeu junto com a resposta.

    O conteúdo da coluna é nome de campo e tipo JSON, nunca valor do
    laudo — ver o comentário em `AIJob.failure_diagnostics`, onde está a
    razão de ser assim e a alternativa recusada.
    """

    dependencies = [
        ('ai', '0007_aijob_relatorio_do_paciente'),
    ]

    operations = [
        migrations.AddField(
            model_name='aijob',
            name='failure_diagnostics',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
