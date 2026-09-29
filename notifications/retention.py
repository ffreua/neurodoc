"""Retenção curta da caixa de avisos.

Notificação é sinal transitório, não trilha de auditoria. O fato que a
originou continua no prontuário, na entrega ou no registro de auditoria; manter
o sino para sempre só duplica identificação de paciente e faz a caixa crescer
sem limite.
"""
from django.db.models import Q
from django.utils import timezone

from .models import Notification

READ_RETENTION_DAYS = 7
UNREAD_RETENTION_DAYS = 15


def purge_expired_notifications(now=None):
    """Apaga lidas há 7 dias e não lidas criadas há 15 dias."""
    reference = now or timezone.now()
    expired = Notification.objects.filter(
        Q(read_at__lt=reference-timezone.timedelta(days=READ_RETENTION_DAYS))
        | Q(
            read_at__isnull=True,
            created_at__lt=reference-timezone.timedelta(days=UNREAD_RETENTION_DAYS),
        )
    )
    total = expired.count()
    expired.delete()
    return {'notifications': total}
