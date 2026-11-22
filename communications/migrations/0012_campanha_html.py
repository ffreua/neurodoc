from django.db import migrations, models


class Migration(migrations.Migration):
    """O corpo em HTML da campanha, e o texto simples opcional ao lado dele."""

    dependencies = [
        ('communications', '0011_whatsapp_texto'),
    ]

    operations = [
        migrations.AlterField(
            model_name='marketingcampaign',
            name='body_text',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='marketingcampaign',
            name='body_html',
            field=models.TextField(blank=True, default=''),
        ),
    ]
