from django.core.management.base import BaseCommand

from documents.signing_sessions import cleanup_orphan_keys


class Command(BaseCommand):
    """Run every 5 minutes by a host-level timer against the `app` service
    (never by Celery beat: the worker does not mount /run/neurodoc-signing,
    per PRD section 8). Also invoked immediately by revoke actions.
    """
    help = 'Removes tmpfs signing keys that have no matching active SigningSession.'

    def handle(self, *args, **options):
        removed = cleanup_orphan_keys()
        self.stdout.write(f'Removed {removed} orphan signing key(s).')
