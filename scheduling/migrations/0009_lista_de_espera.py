"""Lista de espera da agenda (1.31). Aditiva: tabela nova, nada existente muda.

As chaves compostas impedem, no banco, a espera de uma clinica apontar
paciente, medico ou consulta de outra (ver `base/db.py`).
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models

from base.db import composite_tenant_foreign_key


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0013_naturalidade_padrao_brasil'),
        ('scheduling', '0008_forma_de_cobranca'),
        ('tenancy', '0019_periodicidade_do_pagamento'),
    ]

    operations = [
        migrations.CreateModel(
            name='PacienteEmEspera',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('appointment_type', models.CharField(blank=True, choices=[('first_visit', 'Primeira consulta'), ('follow_up', 'Seguimento'), ('return_visit', 'Retorno'), ('procedure', 'Procedimento'), ('other', 'Outro')], max_length=40)),
                ('posicao', models.PositiveIntegerField(default=0)),
                ('status', models.CharField(choices=[('aguardando', 'Aguardando'), ('agendado', 'Agendado'), ('retirado', 'Retirado da lista')], default='aguardando', max_length=20)),
                ('observacao', models.CharField(blank=True, max_length=255)),
                ('resolvido_em', models.DateTimeField(blank=True, null=True)),
                ('motivo_saida', models.CharField(blank=True, max_length=255)),
                ('appointment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='esperas_atendidas', to='scheduling.appointment')),
                ('criado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenancy.membership')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='esperas', to='patients.patient')),
                ('physician_membership', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='esperas', to='tenancy.membership')),
                ('resolvido_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenancy.membership')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.tenant')),
            ],
            options={
                'ordering': ['posicao', 'created_at'],
                'abstract': False,
                'indexes': [models.Index(fields=['tenant', 'status', 'posicao'], name='scheduling_espera_fila_idx')],
                'constraints': [models.UniqueConstraint(fields=('tenant', 'id'), name='scheduling_pacienteemespera_tenant_id_uniq'), models.UniqueConstraint(condition=models.Q(('status', 'aguardando')), fields=('tenant', 'patient'), name='scheduling_espera_uma_por_paciente')],
            },
        ),
        composite_tenant_foreign_key('scheduling_pacienteemespera', 'patient_id', 'patients_patient', 'scheduling_espera_tenant_patient_fk'),
        composite_tenant_foreign_key('scheduling_pacienteemespera', 'physician_membership_id', 'tenancy_membership', 'scheduling_espera_tenant_physician_fk'),
        composite_tenant_foreign_key('scheduling_pacienteemespera', 'appointment_id', 'scheduling_appointment', 'scheduling_espera_tenant_appointment_fk'),
    ]
