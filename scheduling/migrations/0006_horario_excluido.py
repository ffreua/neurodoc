from django.db import migrations, models

MOTIVO_DA_1_14 = 'Horário excluído pela agenda'


def converte(apps, schema_editor):
    """Os bloqueios gravados pelo botão Excluir na 1.14 passam ao tipo
    próprio, e somem da grade como quem os gravou queria.

    Reconhecidos pelo motivo, que só aquele botão escrevia; um bloqueio
    digitado à mão em Configurar horários com esse mesmo texto viraria
    horário excluído também -- o que é, de fato, o que ele dizia ser.
    """
    ScheduleBlock = apps.get_model('scheduling', 'ScheduleBlock')
    ScheduleBlock.objects.filter(kind='block', reason=MOTIVO_DA_1_14).update(kind='removed_slot')


def desfaz(apps, schema_editor):
    ScheduleBlock = apps.get_model('scheduling', 'ScheduleBlock')
    ScheduleBlock.objects.filter(kind='removed_slot').update(kind='block', reason=MOTIVO_DA_1_14)


class Migration(migrations.Migration):
    """Horário excluído como tipo próprio de `ScheduleBlock`.

    `expand`: só acrescenta uma escolha ao campo (nenhuma mudança de
    coluna no banco) e reclassifica linhas. O rollback da imagem continua
    seguro: a 1.14 lê `removed_slot` como um tipo qualquer que não é
    atendimento extra, ou seja, como bloqueio -- que é como ela já os
    tratava.
    """

    dependencies = [
        ('scheduling', '0005_intervalo_recorrente'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scheduleblock',
            name='kind',
            field=models.CharField(
                choices=[
                    ('block', 'Bloqueio'), ('vacation', 'Férias'), ('holiday', 'Feriado'),
                    ('extra_availability', 'Atendimento extra'),
                    ('removed_slot', 'Horário excluído'),
                ],
                max_length=40,
            ),
        ),
        migrations.RunPython(converte, desfaz),
    ]
