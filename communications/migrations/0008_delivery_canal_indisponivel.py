from django.db import migrations, models


class Migration(migrations.Migration):
    """`channel_unavailable`: o canal nao pode enviar, e isso nao e "sem contato".

    So mexe em `choices`, que no Django e validacao de aplicacao -- o
    banco nao tem enumeracao aqui. Nenhuma linha muda de valor.

    **As linhas antigas nao sao reescritas**, e e uma escolha. Uma
    entrega gravada como `no_contact` em setembro pode ter sido
    exatamente isso -- paciente sem telefone -- ou pode ter sido o canal
    indisponivel: os dois casos caiam no mesmo valor, e nao ha no
    registro o que os separe. Reclassificar em bloco inventaria uma
    certeza que nao existe. O que `DeliveryAttempt.sanitized_error`
    guarda (`channel_disabled`, `tenant_inactive`) continua la para quem
    precisar olhar caso a caso.
    """

    dependencies = [
        ('communications', '0007_retorno_como_alvo_de_entrega'),
    ]

    operations = [
        migrations.AlterField(
            model_name='delivery',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Na fila'),
                    ('accepted', 'Aceita pelo provedor'),
                    ('delivered', 'Entregue'),
                    ('unknown', 'Sem confirmação'),
                    ('failed', 'Falhou'),
                    ('no_contact', 'Sem contato cadastrado'),
                    ('channel_unavailable', 'Canal indisponível'),
                    ('needs_reconciliation', 'Aguardando reconciliação'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
