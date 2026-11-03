"""Atendimentos migrados do iClin: `finalized_at` passa a ser a data da anotação.

A migração de 2026-11-02 gravou `finalized_at` com a hora em que rodou, e
com isso a exportação do acervo dizia "finalizado em 02/11/2026" para uma
consulta de 2013, e ordenar por fechamento punha 2013 acima de outubro
(revisão de 2026-11-02, W9). O conteúdo e o `content_hash` não mudam — o
hash não inclui datas —, e a data da migração continua registrada na
`finalization_justification` de cada um.

Só toca em linha com `legacy_id` do iClin: nenhum atendimento escrito no
NeuroDoc tem esse campo preenchido.
"""

from django.db import migrations
from django.db.models import F


def fechar_na_data_da_anotacao(apps, schema_editor):
    Encounter = apps.get_model('clinical', 'Encounter')
    Encounter.objects.filter(legacy_id__startswith='iclin:').update(finalized_at=F('occurred_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('clinical', '0011_encounter_legacy_id'),
    ]

    operations = [
        migrations.RunPython(fechar_na_data_da_anotacao, migrations.RunPython.noop),
    ]
