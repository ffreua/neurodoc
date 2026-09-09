"""Cria (ou promove) a conta de superadministrador da instalação.

`createsuperuser` do Django serve, e não basta aqui por duas razões:

- o modelo de usuário é por e-mail, e a conta precisa nascer com o e-mail
  **já confirmado** — `build_access_context` bloqueia toda a área `/app/`
  para quem não confirmou, e o superadministrador não tem convite de onde
  vir uma confirmação;
- promover uma conta que já existe é o caso comum. Quem opera o servidor
  costuma já ter um vínculo de médico ou dono numa clínica, e criar uma
  segunda conta para o mesmo humano quebra a leitura da trilha de
  auditoria: os dois conjuntos de eventos passam a ser de pessoas
  diferentes.

O console (`/app/super/`) e os painéis técnicos exigem, além de
`is_superuser`, **MFA verificada**. Este comando não configura MFA de
propósito: um segundo fator gerado por comando de servidor, e impresso no
terminal, não é um segundo fator. Configure-o pela tela do próprio
usuário, depois de entrar.
"""

import getpass

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User


class Command(BaseCommand):
    help = 'Cria ou promove a conta de superadministrador da instalação.'

    def add_arguments(self, parser):
        parser.add_argument('email', help='E-mail da conta.')
        parser.add_argument('--first-name', default='', help='Nome.')
        parser.add_argument('--last-name', default='', help='Sobrenome.')
        parser.add_argument(
            '--password', default=None,
            help='Senha. Omitido, é pedida interativamente — o que evita que ela '
                 'fique no histórico do shell.',
        )

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        if not email or '@' not in email:
            raise CommandError('Informe um e-mail válido.')

        user = User.objects.filter(email__iexact=email).first()
        criando = user is None

        if criando:
            senha = options['password'] or getpass.getpass('Senha: ')
            if not senha:
                raise CommandError('A senha não pode ser vazia.')
            user = User(
                email=email,
                first_name=options['first_name'],
                last_name=options['last_name'],
            )
            user.set_password(senha)
        elif options['password']:
            user.set_password(options['password'])

        already = user.is_superuser and user.is_staff
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        if not user.email_verified_at:
            # Sem isto a conta entra e é barrada em toda a área `/app/`,
            # inclusive no console que ela existe para abrir.
            user.email_verified_at = timezone.now()
        user.save()

        acao = 'criada' if criando else ('já era superadministrador' if already else 'promovida')
        self.stdout.write(self.style.SUCCESS(f'Conta {email} — {acao}.'))
        self.stdout.write(
            'Falta a MFA: entre em /accounts/login/, configure o segundo fator na tela '
            'do usuário e só então /app/super/ e /admin/ respondem. É deliberado — um '
            'console que lê a trilha de todas as clínicas atrás só de senha estaria a '
            'uma credencial roubada de distância.'
        )
