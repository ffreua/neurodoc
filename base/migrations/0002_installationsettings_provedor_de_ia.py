from django.db import migrations, models


class Migration(migrations.Migration):
    """O provedor de IA padrao da instalacao passa a morar no banco.

    `expand`: cinco colunas novas, todas com padrao, nenhuma linha
    existente tocada e nada removido.

    **Nao ha retroescrita, de proposito.** As colunas nascem vazias, e
    `InstallationSettings.ia_da_instalacao()` cai no `.env` enquanto
    estiverem assim. Gravar aqui o `AI_MODEL` que o `.env` traz seria
    congelar, no banco, justamente o identificador que motivou esta
    migration -- o modelo que a NVIDIA aposentou em 2026-08-26. Quem abrir
    o console escolhe um que exista, e a escolha passa a valer.
    """

    dependencies = [
        ('base', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='installationsettings',
            name='ai_provider',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='installationsettings',
            name='ai_model',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='installationsettings',
            name='ai_base_url',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='installationsettings',
            name='ai_available_models',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='installationsettings',
            name='ai_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='installationsettings',
            name='ai_check_ok',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='installationsettings',
            name='ai_check_detail',
            field=models.CharField(blank=True, max_length=300),
        ),
    ]
