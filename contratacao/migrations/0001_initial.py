import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('tenancy', '0023_membership_agenda_por_email'),
    ]

    operations = [
        migrations.CreateModel(
            name='Configuracao',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('singleton', models.BooleanField(default=True, editable=False, unique=True)),
                ('ativo', models.BooleanField(default=False, verbose_name='checkout ligado')),
            ],
            options={
                'verbose_name': 'configuração da contratação',
                'verbose_name_plural': 'configuração da contratação',
            },
        ),
        migrations.CreateModel(
            name='EventoAsaas',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.CharField(max_length=120, unique=True)),
                ('tipo', models.CharField(db_index=True, max_length=60)),
                ('payload', models.JSONField()),
                ('recebido_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('processado_em', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('tentativas', models.PositiveSmallIntegerField(default=0)),
                ('erro', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['-recebido_em'],
            },
        ),
        migrations.CreateModel(
            name='Pedido',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('status', models.CharField(choices=[('preparando', 'Preparando o pagamento'), ('aguardando', 'Aguardando pagamento'), ('pago', 'Pago'), ('cancelado', 'Cancelado'), ('expirado', 'Expirado'), ('falhou', 'Não abriu')], db_index=True, default='preparando', max_length=12)),
                ('plano', models.CharField(max_length=16)),
                ('periodicidade', models.CharField(max_length=12)),
                ('valor_pagamento_centavos', models.PositiveIntegerField()),
                ('valor_ano_centavos', models.PositiveIntegerField()),
                ('cobrancas_previstas', models.PositiveSmallIntegerField(default=1)),
                ('nome', models.CharField(max_length=150)),
                ('email', models.EmailField(max_length=254)),
                ('contrato_versao', models.CharField(max_length=16)),
                ('origem_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('checkout_id', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('checkout_link', models.URLField(blank=True, max_length=500)),
                ('assinatura_id', models.CharField(blank=True, db_index=True, max_length=64)),
                ('cliente_asaas_id', models.CharField(blank=True, max_length=64)),
                ('falha', models.TextField(blank=True)),
                ('pago_em', models.DateTimeField(blank=True, null=True)),
                ('convite_token_cifrado', models.TextField(blank=True)),
                ('convite_token_meta', models.JSONField(blank=True, default=dict)),
                ('email_enviado_em', models.DateTimeField(blank=True, null=True)),
                ('convite', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pedido_asaas', to='tenancy.invitation')),
            ],
            options={
                'verbose_name': 'pedido de contratação',
                'verbose_name_plural': 'pedidos de contratação',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Cobranca',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('payment_id', models.CharField(max_length=64, unique=True)),
                ('assinatura_id', models.CharField(blank=True, max_length=64)),
                ('status', models.CharField(blank=True, max_length=40)),
                ('forma', models.CharField(blank=True, max_length=20)),
                ('valor', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('vencimento', models.DateField(blank=True, null=True)),
                ('ultimo_evento', models.CharField(blank=True, max_length=60)),
                ('atualizada_em', models.DateTimeField(auto_now=True)),
                ('pedido', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cobrancas', to='contratacao.pedido')),
            ],
            options={
                'ordering': ['vencimento', 'payment_id'],
            },
        ),
    ]
