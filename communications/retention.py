"""Retenção do log técnico de entregas.

O documento, agendamento e contato são permanentes pelos seus próprios
prazos. A entrega guarda apenas o diagnóstico transitório do transporte e
suas tentativas; depois de quinze dias ela já não participa de reconciliação e
não deve impedir a correção ou exclusão de um contato por `PROTECT`.
"""
from django.db import transaction
from django.db.models import Subquery
from django.utils import timezone

from .models import Delivery, DeliveryAttempt

DELIVERY_RETENTION_DAYS = 15


@transaction.atomic
def purge_expired_deliveries(now=None):
    """Apaga entregas com mais de 15 dias, removendo tentativas primeiro."""
    reference = now or timezone.now()
    expired = Delivery.objects.filter(
        created_at__lt=reference-timezone.timedelta(days=DELIVERY_RETENTION_DAYS),
    )
    deliveries = expired.count()
    if not deliveries:
        return {'deliveries': 0, 'attempts': 0}

    expired_ids = Subquery(expired.values('id'))
    attempts_query = DeliveryAttempt.objects.filter(delivery_id__in=expired_ids)
    attempts = attempts_query.count()
    attempts_query.delete()
    expired.delete()
    return {'deliveries': deliveries, 'attempts': attempts}
