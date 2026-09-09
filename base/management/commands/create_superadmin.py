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

O console (`/instalacao/`) e os painéis técnicos exigem, além de
`is_superuser`, **MFA verificada**. Este comando não configura MFA de
propósito: um segundo fator gerado por comando de servidor, e impresso no
terminal, não é um segundo fator. Configure-o em `/accounts/mfa/setup/`,
depois de entrar.

Sobre a senha: `--invite` é o modo preferido. Ele deixa a conta **sem
senha utilizável** e imprime um link de definição de senha, de uso único e
com prazo. Senha digitada em linha de comando fica no histórico do shell,
na lista de processos enquanto o comando roda, e — quando alguém opera o
servidor por uma sessão registrada — na transcrição dela. Para a conta que
lê a trilha de auditoria de todas as clínicas, isso é caro demais para a
conveniência que compra.
"""

import getpass

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User


class Command(BaseCommand):
    help = 'Cria ou promove a conta de superadministrador da instalação.'

    def add_arguments(self, parser):
        parser.add_argument('email', help='E-mail da conta.')
        parser.add_argument('--first-name', default='', help='Nome.')
        parser.add_argument('--last-name', default='', help='Sobrenome.')
        parser.add_argument(
            '--password', default=None,
            help='Senha. Omitido e sem --invite, é pedida interativamente. '
                 'Passá-la aqui deixa a senha no histórico do shell.',
        )
        parser.add_argument(
            '--invite', action='store_true',
            help='Não define senha: deixa a conta sem senha utilizável e imprime um '
                 'link de definição de senha, de uso único e com prazo. É o modo '
                 'preferido — ver o cabeçalho deste arquivo.',
        )

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        if not email or '@' not in email:
            raise CommandError('Informe um e-mail válido.')

        user = User.objects.filter(email__iexact=email).first()
        criando = user is None

        convite = options['invite']
        if convite and options['password']:
            raise CommandError('--invite e --password se excluem: um define a senha, o '
                               'outro existe justamente para não defini-la.')

        if criando:
            user = User(
                email=email,
                first_name=options['first_name'],
                last_name=options['last_name'],
            )
            if convite:
                user.set_unusable_password()
            else:
                senha = options['password'] or getpass.getpass('Senha: ')
                if not senha:
                    raise CommandError('A senha não pode ser vazia.')
                user.set_password(senha)
        else:
            if options['first_name']:
                user.first_name = options['first_name']
            if options['last_name']:
                user.last_name = options['last_name']
            if convite:
                # Numa conta que já existe, `--invite` **não** derruba a senha
                # atual: quem já entra hoje continuaria entrando amanhã, e
                # invalidar a senha de quem está trabalhando para emitir um
                # link é troca ruim. O link é oferecido a mais, não no lugar.
                pass
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

        if convite:
            base = (settings.PUBLIC_BASE_URL or '').rstrip('/')
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            caminho = reverse('accounts:password_reset_confirm',
                              kwargs={'uidb64': uid, 'token': token})
            dias = settings.PASSWORD_RESET_TIMEOUT // 86400
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Defina a senha por este link:'))
            self.stdout.write(f'  {base}{caminho}')
            self.stdout.write(
                f'  Uso único, vale {dias} dia(s), e deixa de valer assim que a senha '
                'for definida.'
            )

        self.stdout.write('')
        self.stdout.write(
            'Depois da senha, falta a MFA: /accounts/mfa/setup/. Só então /instalacao/ '
            'e /admin/ respondem. É deliberado — um console que lê a trilha de todas '
            'as clínicas atrás só de senha estaria a uma credencial roubada de '
            'distância do histórico delas.'
        )
        if not user.memberships.exists():
            self.stdout.write(
                'Esta conta não tem vínculo em clínica nenhuma, então a área /app/ '
                'não abre para ela — o que é esperado para quem só opera o servidor. '
                'A tela de "nenhuma organização" leva ao console.'
            )
