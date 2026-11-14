"""Vigência do plano pago e renovação pelo sistema (1.47, contrato 2.2).

Só acrescenta: colunas no pedido (a clínica que renova e o aceite da
renovação) e a tabela de vigências. Nenhuma
clínica ganha período por esta migração — de propósito (ver o docstring de
`Vigencia`): entre as anteriores à 1.47 há cortesia e condição combinada, e o
console as registra uma a uma.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contratacao', '0001_initial'),
        ('tenancy', '0023_membership_agenda_por_email'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='pedidos_de_renovacao', to='tenancy.tenant'),
        ),
        migrations.AddField(
            model_name='pedido',
            name='solicitado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(model_name='pedido', name='aceite_em',
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='pedido', name='aceite_sha256',
                            field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name='pedido', name='aceite_texto',
                            field=models.TextField(blank=True)),
        migrations.AddField(model_name='pedido', name='aceite_user_agent',
                            field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name='pedido', name='poderes_declarados',
                            field=models.BooleanField(default=False)),
        migrations.CreateModel(
            name='Vigencia',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('plano', models.CharField(max_length=16)),
                ('periodicidade', models.CharField(
                    choices=[('anual', 'Anual'), ('semestral', 'Semestral'), ('trimestral', 'Trimestral')],
                    max_length=12)),
                ('inicio', models.DateTimeField()),
                ('fim', models.DateTimeField(db_index=True)),
                ('valor_centavos', models.PositiveIntegerField(blank=True, null=True)),
                ('origem', models.CharField(choices=[
                    ('aceite', 'Contratação (aceite do contrato)'),
                    ('renovacao', 'Renovação paga pelo sistema'),
                    ('console', 'Registrada no console'),
                ], max_length=12)),
                ('nota', models.CharField(blank=True, max_length=255)),
                ('aviso_30_em', models.DateTimeField(blank=True, null=True)),
                ('aviso_15_em', models.DateTimeField(blank=True, null=True)),
                ('aviso_vencido_em', models.DateTimeField(blank=True, null=True)),
                ('rebaixada_em', models.DateTimeField(blank=True, null=True)),
                ('medicos_retirados', models.JSONField(blank=True, default=list)),
                ('aceite', models.OneToOneField(blank=True, null=True,
                                                on_delete=django.db.models.deletion.SET_NULL,
                                                related_name='vigencia', to='tenancy.contractacceptance')),
                ('pedido', models.OneToOneField(blank=True, null=True,
                                                on_delete=django.db.models.deletion.PROTECT,
                                                related_name='vigencia', to='contratacao.pedido')),
                ('registrado_por', models.ForeignKey(blank=True, null=True,
                                                     on_delete=django.db.models.deletion.SET_NULL,
                                                     related_name='+', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                             to='tenancy.tenant')),
            ],
            options={
                'verbose_name': 'vigência',
                'verbose_name_plural': 'vigências',
                'ordering': ['-fim'],
                'abstract': False,
                'constraints': [
                    models.UniqueConstraint(fields=('tenant', 'id'),
                                            name='contratacao_vigencia_tenant_id_uniq'),
                    models.CheckConstraint(condition=models.Q(('fim__gt', models.F('inicio'))),
                                           name='contratacao_vigencia_fim_depois_do_inicio'),
                ],
            },
        ),
    ]
