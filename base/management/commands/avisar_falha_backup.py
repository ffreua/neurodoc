"""Avisa quem opera a instalação que o backup diário falhou.

Chamado pelo systemd (`ops/neurodoc-backup-falhou.service`, disparado por
`OnFailure=` da unidade do backup), **dentro do contêiner do worker**: é ele
quem tem a credencial de e-mail (CLAUDE.md §2), e o host não tem Django.

Existe porque o backup falhava em silêncio. Em 2026-10-02 um dia inteiro
ficou sem cópia, e o único rastro era `status=1/FAILURE` no journal da VPS
— que ninguém lê sem motivo. Backup que falha calado só se descobre na
noite de restaurar, que é a noite em que não há o que fazer.

O e-mail não leva a saída do backup: o diagnóstico está no journal, e a
mensagem só precisa fazer alguém ir olhar. Nada de dado clínico, nada de
caminho de chave.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User

ASSUNTO = '[NeuroDoc] O backup diário falhou'


class Command(BaseCommand):
    help = 'Envia aos superadministradores o aviso de que o backup diário falhou.'

    def handle(self, *args, **options):
        destinos = list(
            User.objects.filter(is_superuser=True, is_active=True)
            .exclude(email='').values_list('email', flat=True)
        )
        if not destinos:
            self.stderr.write('Nenhum superadministrador ativo com e-mail: aviso não enviado.')
            return
        quando = timezone.localtime().strftime('%d/%m/%Y %H:%M')
        corpo = (
            f'O backup diário do NeuroDoc falhou ({quando}, horário de Brasília).\n\n'
            'Enquanto ele não rodar de novo, a cópia mais recente é a do último dia '
            'que deu certo — e a cópia externa puxa só o que existe na VPS.\n\n'
            'Para ver o motivo, na VPS:\n'
            '  journalctl -u neurodoc-backup.service -n 80\n\n'
            'Para tentar de novo agora:\n'
            '  sudo systemctl start neurodoc-backup.service\n\n'
            f'Instalação: {settings.PUBLIC_BASE_URL.rstrip("/")}\n'
            'Este aviso sai a cada falha do backup.'
        )
        send_mail(ASSUNTO, corpo, settings.DEFAULT_FROM_EMAIL, destinos)
        self.stdout.write(f'Aviso enviado a {len(destinos)} superadministrador(es).')
