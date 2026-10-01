from django.db import migrations, models


class Migration(migrations.Migration):
    """Acrescenta o tipo de tarefa `patient_report`.

    Só mexe em `choices`: nenhuma linha existente muda de valor, e o banco
    não tem constraint de enumeração aqui — o `choices` do Django é
    validação de aplicação. Por isso a migração não precisa de reversão
    própria nem de janela de manutenção.
    """

    dependencies = [
        ('ai', '0006_alter_aijob_kind_alter_chatmessage_role_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aijob',
            name='kind',
            field=models.CharField(
                choices=[
                    ('encounter_summary', 'Resumo do atendimento'),
                    ('patient_summary', 'Resumo do paciente'),
                    ('diagnostic_support', 'Apoio ao raciocínio diagnóstico'),
                    ('lab_extraction', 'Leitura de laudo laboratorial'),
                    ('report_transcription', 'Transcrição de laudo'),
                    ('patient_report', 'Relatório do paciente'),
                ],
                max_length=40,
            ),
        ),
    ]
