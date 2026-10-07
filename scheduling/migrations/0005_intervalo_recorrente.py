import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Pausa semanal dentro da janela de atendimento -- o almoco.

    `expand`: tabela nova, nada existente tocado. Nasce vazia, e agenda
    sem pausa continua exatamente como esta.

    Nao se confunde com `ScheduleBlock`, que ja existia: aquele e
    bloqueio de **data** (ferias, congresso, feriado) e tem
    `start_at`/`end_at` com dia; este tem dia da semana e vigencia, como
    a regra que ele recorta. Com `ScheduleBlock`, um almoco exigiria 52
    linhas por ano.

    Nem com `AvailabilityRule.buffer_minutes`, que reserva minutos
    **depois de cada** atendimento para a consulta que estourou nao
    empurrar a seguinte.
    """

    dependencies = [
        ('tenancy', '0001_initial'),
        ('scheduling', '0004_retorno_previsto'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecurringBreak',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('weekday', models.PositiveSmallIntegerField()),
                ('local_start', models.TimeField()),
                ('local_end', models.TimeField()),
                ('starts_on', models.DateField()),
                ('ends_on', models.DateField(blank=True, null=True)),
                ('reason', models.CharField(blank=True, max_length=80)),
                ('physician_membership', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='recurring_breaks', to='tenancy.membership',
                )),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to='tenancy.tenant',
                )),
            ],
            options={'ordering': ['weekday', 'local_start']},
        ),
        migrations.AddIndex(
            model_name='recurringbreak',
            index=models.Index(
                fields=['physician_membership', 'weekday'],
                name='sched_pausa_medico_dia_idx',
            ),
        ),
        # `UNIQUE(tenant_id, id)` de `TenantModel`: e o que habilita a
        # chave estrangeira composta, para a linha nao conseguir apontar
        # para objeto de outro inquilino nem por bug de aplicacao. Toda
        # tabela de inquilino carrega esta restricao (ver `base/db.py`).
        migrations.AddConstraint(
            model_name='recurringbreak',
            constraint=models.UniqueConstraint(
                fields=('tenant', 'id'),
                name='scheduling_recurringbreak_tenant_id_uniq',
            ),
        ),
    ]
