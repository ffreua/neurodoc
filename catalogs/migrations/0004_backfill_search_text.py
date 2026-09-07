"""Preenche `search_text` no que já estava importado.

Vai como migração de dados, e não como comando manual, porque toda
instalação que já tem catálogo importado precisa disto para a busca da tela
funcionar — e uma busca que devolve zero resultado sem explicação é pior que
uma busca que não existe.

Só recalcula coluna derivada: código, descrição e release ficam intactos, e
nenhum registro clínico que aponta para um código é afetado.
"""

from django.db import migrations

BATCH = 2000


def _normalize(text):
    import unicodedata

    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).upper()


def backfill(apps, schema_editor):
    for model_name in ('DiagnosisCode', 'ProcedureCode'):
        model = apps.get_model('catalogs', model_name)
        pending = model.objects.filter(search_text='').only('id', 'code', 'description')
        buffer = []
        for row in pending.iterator(chunk_size=BATCH):
            row.search_text = _normalize(f'{row.code} {row.description}')
            buffer.append(row)
            if len(buffer) >= BATCH:
                model.objects.bulk_update(buffer, ['search_text'])
                buffer = []
        if buffer:
            model.objects.bulk_update(buffer, ['search_text'])


def noop(apps, schema_editor):
    """Reverter é esvaziar uma coluna derivada — sem perda de informação."""
    for model_name in ('DiagnosisCode', 'ProcedureCode'):
        apps.get_model('catalogs', model_name).objects.update(search_text='')


class Migration(migrations.Migration):
    dependencies = [
        ('catalogs', '0003_diagnosiscode_search_text_procedurecode_search_text'),
    ]
    operations = [migrations.RunPython(backfill, noop)]
