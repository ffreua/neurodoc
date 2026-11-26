"""Exame trazido de outra consulta, por vínculo (2026-11-26): só acrescenta.

Uma tabela nova e nada mais. Nenhuma linha existente muda, e o hash dos
atendimentos finalizados não muda: o vínculo não entra em
`Encounter.compute_content_hash`, como medicação e hipótese também não.

As chaves compostas `(tenant_id, fk)` seguem a `0009`: o banco recusa o
vínculo que aponte para consulta ou exame de outra clínica, mesmo que um bug
de aplicação tente gravá-lo. Que o exame seja **do mesmo paciente** é
conferido no aceite (`carry_forward.review_carry_forward_item`).
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models

from base.db import composite_tenant_foreign_key


class Migration(migrations.Migration):

    dependencies = [
        ('clinical', '0013_encounter_estrutura_evolucao'),
        ('tenancy', '0024_tenant_dispositivo_confiavel_permitido'),
    ]

    operations = [
        migrations.CreateModel(
            name='EncounterExamLink',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('row_version', models.BigIntegerField(default=1)),
                ('encounter', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exam_links', to='clinical.encounter')),
                ('exam_result', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='links', to='clinical.examresult')),
                ('linked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='tenancy.membership')),
                ('source_encounter', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='clinical.encounter')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.tenant')),
            ],
            options={
                'abstract': False,
                'constraints': [models.UniqueConstraint(fields=('tenant', 'id'), name='clinical_encounterexamlink_tenant_id_uniq'), models.UniqueConstraint(fields=('tenant', 'encounter', 'exam_result'), name='clinical_examlink_unique')],
            },
        ),
        composite_tenant_foreign_key(
            'clinical_encounterexamlink', 'encounter_id', 'clinical_encounter',
            'clinical_examlink_tenant_encounter_fk',
        ),
        composite_tenant_foreign_key(
            'clinical_encounterexamlink', 'exam_result_id', 'clinical_examresult',
            'clinical_examlink_tenant_examresult_fk',
        ),
        composite_tenant_foreign_key(
            'clinical_encounterexamlink', 'source_encounter_id', 'clinical_encounter',
            'clinical_examlink_tenant_source_fk',
        ),
        composite_tenant_foreign_key(
            'clinical_encounterexamlink', 'linked_by_id', 'tenancy_membership',
            'clinical_examlink_tenant_linked_by_fk',
        ),
    ]
