from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('clinical', '0009_fk_composta_por_inquilino'),
    ]

    operations = [
        migrations.AddField(
            model_name='encounter',
            name='neurological_exam_text',
            field=models.TextField(blank=True, max_length=20000),
        ),
    ]
