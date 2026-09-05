import uuid

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Invalidate restored sessions and hold external work for reconciliation.'

    def add_arguments(self, parser):
        parser.add_argument('--operator-email', required=True)
        parser.add_argument('--reason', required=True)

    def handle(self, *args, **options):
        if not settings.NEURODOC_RECOVERY_MODE or any([
            settings.EMAIL_ENABLED, settings.SMS_ENABLED, settings.AI_ENABLED,
        ]):
            raise CommandError('Recovery mode and disabled external channels are required')
        operator = get_user_model().objects.filter(
            email__iexact=options['operator_email'], is_active=True,
            is_staff=True, is_superuser=True,
        ).first()
        if operator is None:
            raise CommandError('An active technical administrator must be identified')
        reason = options['reason'].strip()
        if not 10 <= len(reason) <= 500:
            raise CommandError('Provide a recovery reason of 10 to 500 characters')
        now = timezone.now()
        counts = {}
        with transaction.atomic():
            counts['sessions'] = Session.objects.all().delete()[0]
            counts['signing'] = apps.get_model('documents', 'SigningSession')._base_manager.update(
                revoked_at=now, encrypted_unlock_material=b'', updated_at=now,
            )
            counts['tokens'] = apps.get_model('communications', 'DocumentAccessToken')._base_manager.update(
                revoked_at=now, otp_hash='', updated_at=now,
            )
            counts['ai_jobs'] = apps.get_model('ai', 'AIJob')._base_manager.filter(
                status__in=['queued', 'running', 'stalled'],
            ).update(status='cancelled', cancel_requested_at=now, updated_at=now)
            counts['deliveries'] = apps.get_model('communications', 'Delivery')._base_manager.filter(
                status__in=['pending', 'queued', 'processing', 'accepted', 'unknown', 'failed'],
            ).update(status='needs_reconciliation', next_attempt_at=None, updated_at=now)
            counts['events'] = apps.get_model('events', 'OutboxEvent')._base_manager.exclude(
                status='completed',
            ).update(status='held_restored', locked_until=None, updated_at=now)
            apps.get_model('audit', 'AuditEvent')._base_manager.create(
                actor=operator, tenant_id=None, action='platform.recovery_prepared',
                object_type='platform', object_id=uuid.uuid4(), purpose=reason,
                outcome='success', request_id=uuid.uuid4(), integrity_metadata=counts,
            )
        self.stdout.write('Recovery state prepared; reconcile held work before normal operation.')
