"""Os PDFs que o sistema gerou para documento médico passam a ser clínicos.

Nasciam administrativos (auditoria de 2026-10-09, ND-1121-001): apareciam
com nome e botão de baixar para quem não lê prontuário -- o rascunho
inclusive -- e ficavam fora da guarda de vinte anos. O código novo já os
gera clínicos; esta migração corrige os que existiam.

Dois grupos, e o segundo é o que um filtro só pela relação perderia:

1. o PDF para o qual um `MedicalDocument` aponta (rascunho, papel ou
   assinado);
2. o **rascunho órfão**: emitir em papel troca o `pdf_attachment` do
   documento pelo PDF do papel, e o rascunho anterior continua ligado ao
   paciente, com "RASCUNHO SEM VALIDADE" e o conteúdo clínico. Ele é
   reconhecido pelo nome que `documents.issuance` dá aos arquivos que gera
   -- tipo, id do documento e o sufixo --, que upload nenhum produz.

Só dados, e só em uma direção: a volta não devolve nada a administrativo,
porque reabrir o acesso por rollback seria pior que o defeito.
"""
import re

from django.db import migrations

GERADO = re.compile(r'^[a-z_]+_[0-9a-f-]{36}_(draft|papel)\.pdf$|^[a-z_]+_.+_signed\.pdf$')


def classificar(apps, schema_editor):
    Attachment = apps.get_model('documents', 'Attachment')
    MedicalDocument = apps.get_model('documents', 'MedicalDocument')

    ids = set()
    for pdf_id, assinado_id in MedicalDocument.objects.values_list('pdf_attachment_id', 'signed_pdf_attachment_id'):
        ids.update(i for i in (pdf_id, assinado_id) if i)
    for anexo_id, nome in (
        Attachment.objects.filter(mime='application/pdf', classification='administrative')
        .values_list('id', 'original_name')
    ):
        if GERADO.match(nome or ''):
            ids.add(anexo_id)
    Attachment.objects.filter(id__in=ids).exclude(classification='clinical').update(classification='clinical')


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0006_alter_medicaldocument_encounter_and_more'),
    ]

    operations = [
        migrations.RunPython(classificar, migrations.RunPython.noop),
    ]
