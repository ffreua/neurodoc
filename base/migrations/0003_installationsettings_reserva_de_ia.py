"""O provedor de IA reserva da instalação.

Só acrescenta colunas, todas com padrão: a reserva nasce **desligada** e
vazia, e nenhuma linha existente muda de comportamento. A versão anterior
do sistema continua rodando sobre o banco migrado (expand-only).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0002_installationsettings_provedor_de_ia'),
    ]

    operations = [
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_ativa',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_provider',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_model',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_base_url',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_chave_cifrada',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_chave_meta',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_chave_dica',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_modelos',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_check_ok',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_check_detail',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_usos',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_reserva_usada_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='installationsettings', name='ai_alerta_enviado_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
