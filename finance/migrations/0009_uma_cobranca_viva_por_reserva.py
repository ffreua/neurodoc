"""Uma cobrança **viva** por reserva de exame (revisão de 2026-11-02, T12).

A restrição valia para toda cobrança da reserva, inclusive a cancelada; com
ela, trocar a forma de cobrança do exame realizado não tinha como criar a
cobrança nova. A cancelada passa a ficar de fora, e continua no banco.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0008_cobranca_do_exame'),
    ]

    operations = [
        migrations.RemoveConstraint(model_name='receivable', name='finance_receivable_reserva_uniq'),
        migrations.AddConstraint(
            model_name='receivable',
            constraint=models.UniqueConstraint(
                condition=models.Q(('reserva_exame__isnull', False), models.Q(('status', 'cancelled'), _negated=True)),
                fields=('tenant', 'reserva_exame', 'charge_kind'),
                name='finance_receivable_reserva_uniq',
            ),
        ),
    ]
