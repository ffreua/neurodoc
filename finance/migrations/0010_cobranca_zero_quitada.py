"""A cobrança de valor zero que ficou "Em aberto" passa a quitada.

Desde 2026-11-12 ela nasce quitada (`finance.receivables.situacao_inicial`).
As de antes — o retorno sem custo — ficaram "Em aberto" para sempre, porque
não há pagamento de zero a lançar. Só as que nunca receberam nada nem
tiveram ajuste: as outras, a situação já é refeita por quem as tocou.
"""
from django.db import migrations


def quitar(apps, schema_editor):
    Receivable = apps.get_model('finance', 'Receivable')
    (
        Receivable.objects.filter(charged_amount=0, status='pending')
        .filter(payments__isnull=True, adjustments__isnull=True)
        .update(status='paid')
    )


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0009_uma_cobranca_viva_por_reserva'),
    ]

    operations = [
        migrations.RunPython(quitar, migrations.RunPython.noop),
    ]
