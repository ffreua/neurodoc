from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tenancy.invitations import issue_invitation
from tenancy.limits import describe_limit, granted_limits
from tenancy.models import InvitationPurpose
from tenancy.plans import PlanCode, plan_label


class Command(BaseCommand):
    help = 'Issue an initial platform invitation (owner-only action, per section 4).'

    def add_arguments(self, parser):
        parser.add_argument('--issued-by-email', required=True)
        parser.add_argument('--email-binding', default='')
        parser.add_argument('--ttl-days', type=int, default=7)
        parser.add_argument(
            '--plan', default=PlanCode.FREE, choices=[c for c, _ in PlanCode.choices],
            help='Plano que este convite garante à organização criada.',
        )
        parser.add_argument(
            '--max-patients', type=int, default=None,
            help='Limite de pacientes acima ou abaixo do plano. Omitido, vale o do plano.',
        )
        parser.add_argument(
            '--max-doctors', type=int, default=None,
            help='Limite de médicos acima ou abaixo do plano. Omitido, vale o do plano.',
        )
        parser.add_argument(
            '--plan-note', default='',
            help='Por que este plano (contrato, cortesia, piloto). Vai para a organização.',
        )

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
            plan=options['plan'],
            patient_limit_override=options['max_patients'],
            doctor_limit_override=options['max_doctors'],
            plan_note=options['plan_note'],
        )
        pacientes, medicos = granted_limits(
            invitation.plan, invitation.patient_limit_override, invitation.doctor_limit_override,
        )
        self.stdout.write(f'Invitation token: {raw_token}')
        self.stdout.write(f'Expires at: {invitation.expires_at.isoformat()}')
        self.stdout.write(
            f'Plano: {plan_label(invitation.plan)} — '
            f'{describe_limit(pacientes)} pacientes, {describe_limit(medicos)} médicos'
        )
