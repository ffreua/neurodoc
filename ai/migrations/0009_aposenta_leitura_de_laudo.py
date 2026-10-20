"""Encerra o que a leitura de laudo por IA deixou pendente (1.18).

A leitura de laudo saiu do sistema (`ai/models.py::TIPOS_APOSENTADOS`).
Os jobs e artefatos antigos ficam no banco -- são histórico, e a trilha de
auditoria aponta para eles --, mas nada deles pode continuar esperando:

- job na fila ou rodando vira **cancelado**, com a explicação. O worker já
  cancelaria ao recebê-lo; aqui é para o que nunca mais chegaria;
- rascunho **pendente de revisão** vira **rejeitado**. A tela do job
  continuaria oferecendo "Aceitar" para um rascunho que não tem mais para
  onde ir — a tela de exames que o incorporava saiu.

Nada é apagado. O reverso não desfaz: devolver um rascunho a "pendente"
só reabriria a porta que se quis fechar.
"""
from django.db import migrations
from django.utils import timezone

TIPOS = ('lab_extraction', 'report_transcription')
MOTIVO = (
    'A leitura de laudo por IA foi retirada do sistema. O exame continua '
    'registrado; inclua os valores e o laudo à mão.'
)


def encerrar(apps, schema_editor):
    AIJob = apps.get_model('ai', 'AIJob')
    AIArtifact = apps.get_model('ai', 'AIArtifact')
    AIJob.objects.filter(kind__in=TIPOS, status__in=('queued', 'running')).update(
        status='cancelled', status_detail=MOTIVO,
    )
    AIArtifact.objects.filter(job__kind__in=TIPOS, review_state='pending').update(
        review_state='rejected', reviewed_at=timezone.now(),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0008_aijob_failure_diagnostics'),
    ]

    operations = [
        migrations.RunPython(encerrar, migrations.RunPython.noop),
    ]
