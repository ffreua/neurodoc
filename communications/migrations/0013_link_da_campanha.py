import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    """Os links da campanha e quantas vezes cada um foi clicado.

    Só acrescenta uma tabela. O link é o mesmo para todos os destinatários:
    a contagem é por link, não por pessoa.
    """

    dependencies = [
        ('communications', '0012_campanha_html'),
        ('tenancy', '0024_tenant_dispositivo_confiavel_permitido'),
    ]

    operations = [
        migrations.CreateModel(
            name='CampaignLink',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('url', models.URLField(max_length=2000)),
                ('token', models.CharField(max_length=32, unique=True)),
                ('clicks', models.PositiveIntegerField(default=0)),
                ('last_click_at', models.DateTimeField(blank=True, null=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='links', to='communications.marketingcampaign')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.tenant')),
            ],
            options={
                'abstract': False,
                'constraints': [models.UniqueConstraint(fields=('tenant', 'id'), name='communications_campaignlink_tenant_id_uniq'), models.UniqueConstraint(fields=('campaign', 'url'), name='comm_campaign_link_url_uniq')],
            },
        ),
    ]
