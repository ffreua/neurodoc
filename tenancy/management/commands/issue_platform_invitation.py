from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tenancy.invitations import issue_invitation
from tenancy.models import InvitationPurpose


class Command(BaseCommand):
    help = 'Issue an initial platform invitation (owner-only action, per section 4).'

    def add_arguments(self, parser):
        parser.add_argument('--issued-by-email', required=True)
        parser.add_argument('--email-binding', default='')
        parser.add_argument('--ttl-days', type=int, default=7)

    def handle(self, *args, **options):
        issuer = get_user_model().objects.filter(
            email__iexact=options['issued_by_email'], is_active=True,
            is_staff=True, is_superuser=True,
        ).first()
        if issuer is None:
            raise CommandError('An active technical administrator must be identified')
        invitation, raw_token = issue_invitation(
            InvitationPurpose.PLATFORM, issued_by=issuer,
            ttl_days=options['ttl_days'], email_binding=options['email_binding'],
        )
        self.stdout.write(f'Invitation token: {raw_token}')
        self.stdout.write(f'Expires at: {invitation.expires_at.isoformat()}')
