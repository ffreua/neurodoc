"""Dispositivo confiável (2026-11-18): só expansão, uma tabela nova.

Ver `accounts/dispositivo_confiavel.py`. Nenhuma linha existente muda, e
ninguém passa a entrar sem o código com esta migração: a clínica nasce
proibindo (`tenancy.0024`).
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_alter_physicianprofile_verification_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='DispositivoConfiavel',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('senha_marca', models.CharField(max_length=64)),
                ('totp_device_id', models.BigIntegerField()),
                ('descricao', models.CharField(max_length=80)),
                ('user_agent', models.CharField(blank=True, max_length=300)),
                ('ip_protegido', models.CharField(blank=True, max_length=64)),
                ('termo_versao', models.CharField(max_length=10)),
                ('termo_sha256', models.CharField(max_length=64)),
                ('termo_texto', models.TextField()),
                ('ultimo_uso_em', models.DateTimeField(blank=True, null=True)),
                ('revogado_em', models.DateTimeField(blank=True, null=True)),
                ('revogado_motivo', models.CharField(blank=True, choices=[
                    ('pela_pessoa', 'Revogado pela própria pessoa'),
                    ('todos_pela_pessoa', 'Todos revogados pela própria pessoa'),
                    ('senha_trocada', 'A senha foi trocada'),
                    ('segundo_fator_refeito', 'O segundo fator foi refeito'),
                    ('mfa_resetado', 'O responsável resetou o segundo fator'),
                    ('clinica_proibiu', 'A organização deixou de permitir'),
                ], max_length=40)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='dispositivos_confiaveis', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'revogado_em'], name='accounts_dispconf_user_idx')],
                'constraints': [models.CheckConstraint(
                    condition=(
                        models.Q(revogado_em__isnull=True, revogado_motivo='')
                        | (models.Q(revogado_em__isnull=False) & ~models.Q(revogado_motivo=''))
                    ),
                    name='accounts_dispconf_revogado_com_motivo',
                )],
            },
        ),
    ]
