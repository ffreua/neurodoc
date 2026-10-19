"""Laudos de exame enviados pelo paciente no portal.

Duas mudanças, as duas só de expansão (o código anterior continua rodando
sobre o banco migrado, que é o que o deploy exige):

1. `Attachment.uploaded_by` passa a aceitar nulo. Quem envia pelo portal
   não tem conta, e o anexo que já existe continua com o autor que tinha.
2. A tabela `PortalExamUpload`, com o que o paciente informa (qual exame,
   quando, onde) e o "ciente" do médico.

Ver `documents.portal_exames`.
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0007_pdf_de_documento_e_clinico'),
        ('patients', '0013_naturalidade_padrao_brasil'),
        ('tenancy', '0017_barrar_consulta_antiga'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='attachment',
            name='uploaded_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name='PortalExamUpload',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('exam_type', models.CharField(choices=[('ressonancia', 'Ressonância magnética'), ('tomografia', 'Tomografia computadorizada'), ('eletroneuromiografia', 'Eletroneuromiografia'), ('eletroencefalograma', 'Eletroencefalograma'), ('laboratorial', 'Exames laboratoriais (sangue, urina)'), ('liquor', 'Líquor'), ('doppler', 'Doppler / ultrassonografia'), ('polissonografia', 'Polissonografia'), ('potencial_evocado', 'Potencial evocado'), ('neuropsicologica', 'Avaliação neuropsicológica'), ('raio_x', 'Raio-X'), ('outro', 'Outro')], max_length=40)),
                ('exam_other', models.CharField(blank=True, max_length=120)),
                ('performed_on', models.DateField()),
                ('performed_at_place', models.CharField(max_length=160)),
                ('original_filename', models.CharField(blank=True, max_length=255)),
                ('requester_name', models.CharField(max_length=255)),
                ('requester_is_patient', models.BooleanField(default=True)),
                ('privacy_ack_at', models.DateTimeField(blank=True, null=True)),
                ('privacy_notice_version', models.CharField(blank=True, max_length=20)),
                ('origin_ip_protected', models.CharField(blank=True, max_length=64)),
                ('acknowledged_at', models.DateTimeField(blank=True, null=True)),
                ('acknowledged_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='tenancy.membership')),
                ('attachment', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='envio_portal', to='documents.attachment')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exames_do_portal', to='patients.patient')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.tenant')),
            ],
            options={
                'abstract': False,
                'indexes': [models.Index(fields=['tenant', 'patient', 'acknowledged_at'], name='documents_portalexam_pend_idx')],
                'constraints': [models.UniqueConstraint(fields=('tenant', 'id'), name='documents_portalexamupload_tenant_id_uniq')],
            },
        ),
    ]
