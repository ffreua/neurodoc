"""O registro do aceite do contrato de adesao.

Escrita a mao a partir de `makemigrations --dry-run --verbosity 3`: o
sistema de arquivos do conteiner e somente leitura, entao o Django gera o
corpo e nos o gravamos aqui no host.

Sem migracao de dados. As clinicas que ja existem ficam **sem** aceite, de
proposito: inventar um aceite retroativo seria registrar como assinado um
contrato que ninguem leu, e isso vale menos que nada numa discussao. O
console lista essas organizacoes em destaque, e elas aceitam a proxima
versao pelo caminho normal.
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0013_clinicprofile_dpo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ContractAcceptance',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('version', models.CharField(max_length=20)),
                ('text_sha256', models.CharField(max_length=64)),
                ('plan', models.CharField(choices=[('free', 'Gratuito'), ('basic', 'Básico'), ('complete', 'Completo'), ('custom', 'Personalizado')], default='free', max_length=40)),
                ('accepted_name', models.CharField(blank=True, max_length=255)),
                ('accepted_email', models.EmailField(max_length=254)),
                ('source_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=255)),
                ('withdrawal_deadline', models.DateTimeField()),
                ('expires_at', models.DateTimeField()),
                ('withdrawn_at', models.DateTimeField(blank=True, null=True)),
                ('emailed_at', models.DateTimeField(blank=True, null=True)),
                ('email_error', models.CharField(blank=True, max_length=255)),
                ('accepted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.tenant')),
            ],
            options={
                'abstract': False,
                'indexes': [models.Index(fields=['-created_at'], name='tenancy_contrato_recent_idx')],
                'constraints': [models.UniqueConstraint(fields=('tenant', 'id'), name='tenancy_contractacceptance_tenant_id_uniq'), models.UniqueConstraint(fields=('tenant', 'version'), name='tenancy_contract_tenant_version_uniq')],
            },
        ),
    ]
