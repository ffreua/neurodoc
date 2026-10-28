import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """App novo de modelos de documento.

    `expand`: só uma tabela nova, sem tenant (o modelo é do médico, ver
    `modelos/models.py`), e nenhuma existente tocada. Nada aponta para ela.
    """

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ModeloDocumento',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('tipo', models.CharField(choices=[('exames', 'Pedido de exames'), ('relatorio', 'Relatório'), ('cirurgia', 'Solicitação de cirurgia'), ('receita', 'Receita')], max_length=20)),
                ('nome', models.CharField(max_length=120)),
                ('conteudo', models.JSONField(blank=True, default=dict)),
                ('origem', models.CharField(blank=True, max_length=80)),
                ('autor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='modelos_de_documento', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'modelo de documento',
                'verbose_name_plural': 'modelos de documento',
                'ordering': ['nome'],
                'indexes': [models.Index(fields=['autor', 'tipo'], name='modelos_autor_tipo_idx')],
            },
        ),
    ]
