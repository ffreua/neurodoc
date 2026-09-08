"""Valida (ou recusa) o registro profissional de um médico.

A validação do CRM é ato da administração da plataforma, não da clínica: o
PRD separa "conceder papel médico" — que o dono faz — de "validação
profissional", e um dono que valida a si mesmo esvazia a separação. Por
isso a tela da organização cadastra o registro e o deixa pendente, e a
decisão sai daqui ou do admin do Django.

Existe como comando porque o admin do Django não está disponível em toda
instalação, e porque a operação precisa aparecer no log de auditoria com
quem decidiu — o que uma edição direta na tabela não registra.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import PhysicianProfile, User


class Command(BaseCommand):
    help = (
        'Valida ou recusa o registro profissional de um médico. '
        'Sem --status, mostra a situação atual.'
    )

    def add_arguments(self, parser):
        parser.add_argument('email', help='E-mail do médico')
        parser.add_argument(
            '--status', choices=['verified', 'rejected', 'pending'],
            help='Nova situação do registro. Omita para apenas consultar.',
        )
        parser.add_argument(
            '--by', default='',
            help='E-mail de quem decidiu, para a trilha de auditoria.',
        )

    def handle(self, *args, **options):
        profile = PhysicianProfile.objects.filter(
            user__email__iexact=options['email'],
        ).select_related('user').first()
        if profile is None:
            raise CommandError(
                f'Nenhum registro profissional para {options["email"]}. '
                'Cadastre-o primeiro em Organização → Equipe.'
            )

        if not options['status']:
            self.stdout.write(
                f'{profile.professional_name} — CRM {profile.crm_number}/'
                f'{profile.crm_state} — {profile.verification_status}'
            )
            return

        actor = None
        if options['by']:
            actor = User.objects.filter(email__iexact=options['by']).first()
            if actor is None:
                raise CommandError(f'Usuário {options["by"]} não encontrado.')

        previous = profile.verification_status
        profile.verification_status = options['status']
        profile.save(update_fields=['verification_status'])

        from audit.services import record_audit_event

        record_audit_event(
            actor, None, 'accounts.physician_verification_changed',
            object_type='physician_profile', object_id=profile.id, outcome='success',
            integrity_metadata={
                'crm': f'{profile.crm_number}/{profile.crm_state}',
                'from': previous, 'to': profile.verification_status,
            },
        )
        self.stdout.write(self.style.SUCCESS(
            f'{profile.professional_name} (CRM {profile.crm_number}/{profile.crm_state}): '
            f'{previous} → {profile.verification_status}'
        ))
