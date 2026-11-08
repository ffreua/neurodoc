# O texto do WhatsApp da recepção (1.39). Só acrescenta uma coluna com
# padrão vazio: nenhuma linha muda de sentido, e a versão anterior do código
# continua rodando sobre o banco migrado (expand, sem contract).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('communications', '0010_entrega_do_exame'),
    ]

    operations = [
        migrations.AddField(
            model_name='messagingsettings',
            name='whatsapp_texto',
            field=models.TextField(blank=True, default=''),
        ),
    ]
