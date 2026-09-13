"""Manda um e-mail de teste e conta o que aconteceu, passo a passo.

Existe porque "não estamos enviando e-mails" tem cinco causas possíveis, e
a mensagem de erro do Django não distingue nenhuma delas: o envio pode
estar desligado, o processo pode não ter saída para a internet, a senha
pode não ter chegado ao worker, o servidor pode recusar, ou a mensagem
pode estar na fila esperando um worker que não está de pé.

Este comando responde qual das cinco é, e por isso imprime a configuração
antes de tentar.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Envia um e-mail de teste pelo caminho real da instalação e relata '
        'cada etapa. Sem --direto, passa pela fila como em produção.'
    )

    def add_arguments(self, parser):
        parser.add_argument('destino', help='endereço que deve receber a mensagem')
        parser.add_argument(
            '--direto', action='store_true',
            help='fala com o SMTP deste processo, sem passar pela fila. Serve '
                 'para separar "o SMTP está errado" de "o worker não está de pé".',
        )

    def handle(self, *args, **options):
        destino = options['destino'].strip()
        if '@' not in destino:
            raise CommandError(f'Endereço inválido: {destino}')

        papel = __import__('os').environ.get('SERVICE_ROLE', 'app')
        self.stdout.write('--- configuração ---')
        self.stdout.write(f'  processo ............ {papel}')
        self.stdout.write(f'  EMAIL_ENABLED ....... {settings.EMAIL_ENABLED}')
        self.stdout.write(f'  backend ............. {settings.EMAIL_BACKEND}')
        self.stdout.write(f'  servidor ............ {settings.EMAIL_HOST}:{settings.EMAIL_PORT}')
        self.stdout.write(f'  TLS ................. {settings.EMAIL_USE_TLS}')
        self.stdout.write(f'  usuário ............. {settings.EMAIL_HOST_USER or "(sem autenticação)"}')
        # Nunca a senha: só se ela existe. Um comando de diagnóstico que
        # imprime credencial vira credencial em log de terminal.
        self.stdout.write(f'  senha ............... {"presente" if settings.EMAIL_HOST_PASSWORD else "AUSENTE"}')
        self.stdout.write(f'  remetente ........... {settings.DEFAULT_FROM_EMAIL}')

        if not settings.EMAIL_ENABLED:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'EMAIL_ENABLED=False: a mensagem vai para a caixa em memória e '
                'nada sai desta máquina. Ligue no .env e regenere o compose '
                '(python -m ops.local_compose) para exercitar o envio.'
            ))

        from django.core.mail import EmailMultiAlternatives, get_connection

        mensagem = EmailMultiAlternatives(
            subject='NeuroDoc — teste de envio',
            body=(
                'Esta mensagem foi gerada por manage.py testar_email.\n\n'
                'Se ela chegou, o caminho de e-mail da instalação está '
                'funcionando de ponta a ponta.\n'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[destino],
        )

        self.stdout.write('')
        self.stdout.write('--- envio ---')
        if options['direto']:
            # Ignora `EMAIL_BACKEND` de propósito: é o que separa um SMTP mal
            # configurado de um worker ausente. Num processo sem egresso
            # (o `app`, em produção) isto falha — e falhar aqui é o
            # diagnóstico, não o defeito.
            conexao = get_connection(backend='django.core.mail.backends.smtp.EmailBackend')
            enviadas = conexao.send_messages([mensagem])
            self.stdout.write(f'  SMTP direto: {enviadas} mensagem(ns) aceita(s) pelo servidor.')
        else:
            enviadas = mensagem.send(fail_silently=False)
            if settings.EMAIL_ENABLED:
                self.stdout.write(f'  {enviadas} mensagem(ns) enfileirada(s) para o worker.')
                self.stdout.write(
                    '  A entrega acontece em communications.tasks.deliver_installation_email. '
                    'Se não chegar, veja o log do worker: o SMTP é falado lá, não aqui.'
                )
            else:
                from django.core import mail

                self.stdout.write(f'  {enviadas} mensagem(ns) na caixa em memória '
                                  f'(total: {len(mail.outbox)}).')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Concluído para {destino}.'))
