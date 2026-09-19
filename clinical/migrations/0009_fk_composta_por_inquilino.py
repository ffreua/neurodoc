"""Chave estrangeira composta `(tenant_id, fk)` no núcleo clínico.

O `base/db.py::composite_tenant_foreign_key` existe desde o começo, todo
`TenantModel` carrega o `UNIQUE(tenant_id, id)` que ele exige — e ele
estava aplicado em **um** lugar: o chat da equipe. A metade cara da defesa
descrita no CLAUDE.md e no PRD §4 nunca chegou aos modelos clínicos, que
são justamente os que não podem apontar para objeto de outra clínica.

O que isto impede: um bug de aplicação — um `encounter_id` vindo da URL
sem filtro por `tenant`, um `get_or_create` que esquece o escopo — gravar
uma linha cujo pai é de outra clínica. Com a restrição composta o banco
recusa a linha; sem ela, a consulta seguinte a devolve como se fosse da
casa. Não substitui o filtro por inquilino em cada consulta: é a rede
embaixo dele.

`MATCH SIMPLE` (o padrão) é o que se quer nas colunas opcionais: quando a
FK é nula — atendimento sem agendamento, achado sem nó do roteiro —, a
restrição não se aplica, que é exatamente o comportamento do `null=True`.

Fora desta lista ficam, de propósito, as referências a catálogo global:
`catalogs.DiagnosisCode` (CID-10) não é `TenantModel` e não tem dono.
"""

from django.db import migrations

from base.db import composite_tenant_foreign_key

#: (tabela filha, coluna, tabela pai, nome da restrição).
#: Nome com até 63 caracteres, o limite de identificador do PostgreSQL.
RELACOES = [
    ('clinical_encounter', 'patient_id', 'patients_patient',
     'clinical_encounter_tenant_patient_fk'),
    ('clinical_encounter', 'physician_membership_id', 'tenancy_membership',
     'clinical_encounter_tenant_physician_fk'),
    ('clinical_encounter', 'finalized_by_id', 'tenancy_membership',
     'clinical_encounter_tenant_finalized_by_fk'),
    ('clinical_encounter', 'appointment_id', 'scheduling_appointment',
     'clinical_encounter_tenant_appointment_fk'),

    ('clinical_encounterdiagnosis', 'encounter_id', 'clinical_encounter',
     'clinical_diagnosis_tenant_encounter_fk'),

    ('clinical_examinationfinding', 'encounter_id', 'clinical_encounter',
     'clinical_finding_tenant_encounter_fk'),
    ('clinical_examinationfinding', 'template_node_id', 'exams_examnode',
     'clinical_finding_tenant_node_fk'),

    ('clinical_carryforwarditem', 'target_encounter_id', 'clinical_encounter',
     'clinical_carryforward_tenant_target_fk'),
    ('clinical_carryforwarditem', 'source_encounter_id', 'clinical_encounter',
     'clinical_carryforward_tenant_source_fk'),
    ('clinical_carryforwarditem', 'reviewed_by_id', 'tenancy_membership',
     'clinical_carryforward_tenant_reviewer_fk'),

    ('clinical_clinicalamendment', 'encounter_id', 'clinical_encounter',
     'clinical_amendment_tenant_encounter_fk'),
    ('clinical_clinicalamendment', 'author_id', 'tenancy_membership',
     'clinical_amendment_tenant_author_fk'),

    ('clinical_medication', 'encounter_id', 'clinical_encounter',
     'clinical_medication_tenant_encounter_fk'),

    ('clinical_examresult', 'encounter_id', 'clinical_encounter',
     'clinical_examresult_tenant_encounter_fk'),
    ('clinical_examresult', 'patient_id', 'patients_patient',
     'clinical_examresult_tenant_patient_fk'),
    ('clinical_examresult', 'attachment_id', 'documents_attachment',
     'clinical_examresult_tenant_attachment_fk'),

    ('clinical_labvalue', 'exam_result_id', 'clinical_examresult',
     'clinical_labvalue_tenant_examresult_fk'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('clinical', '0008_encounter_free_text_encounter_impressions_and_more'),
        # Cada pai precisa já ter o seu `UNIQUE(tenant_id, id)`, que é o que
        # a restrição composta referencia.
        ('patients', '0001_initial'),
        ('tenancy', '0001_initial'),
        ('scheduling', '0001_initial'),
        ('exams', '0001_initial'),
        ('documents', '0001_initial'),
    ]

    operations = [
        composite_tenant_foreign_key(filha, coluna, pai, nome)
        for filha, coluna, pai, nome in RELACOES
    ]
