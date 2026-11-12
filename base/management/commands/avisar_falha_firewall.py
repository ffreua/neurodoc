"""Avisa quem opera a instalação que a trava da Cloudflare falhou.

Chamado pelo systemd (`ops/neurodoc-cloudflare-fw-falhou.service`,
disparado por `OnFailure=` da trava), **dentro do contêiner do worker** —
o mesmo caminho de `avisar_falha_backup`, e pelo mesmo motivo: só o worker
tem a credencial de e-mail (CLAUDE.md §2).

Existe porque a falha era calada (auditoria de 2026-11-11). A rodada que
não confirmava o site pela borda desfazia a trava e deixava só
`status=1` no journal: as portas 80 e 443 aceitando qualquer IP, sem
ninguém saber. O e-mail não diz qual dos dois desfechos houve — trava
desfeita ou mantida com o app fora do ar —, porque o journal diz, e a
mensagem só precisa fazer alguém ir olhar.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User

ASSUNTO = '[NeuroDoc] A trava da Cloudflare falhou'


class Command(BaseCommand):
    help = 'Envia aos superadministradores o aviso de que a trava da Cloudflare falhou.'

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
            f'A rodada da trava da Cloudflare falhou ({quando}, horário de Brasília).\n\n'
            'Ou a trava foi desfeita — o site respondia pelo app e não pela borda, e as '
            'portas 80 e 443 aceitam qualquer IP até a próxima rodada —, ou ela ficou '
            'aplicada porque o próprio app estava fora do ar. A rodada se repete de hora '
            'em hora.\n\n'
            'Para ver qual dos dois, na VPS:\n'
            '  sudo journalctl -u neurodoc-cloudflare-fw.service -n 20\n\n'
            'Para tentar de novo agora:\n'
            '  sudo systemctl start neurodoc-cloudflare-fw.service\n\n'
            f'Instalação: {settings.PUBLIC_BASE_URL.rstrip("/")}\n'
            'Este aviso sai a cada rodada que falha.'
        )
        send_mail(ASSUNTO, corpo, settings.DEFAULT_FROM_EMAIL, destinos)
        self.stdout.write(f'Aviso enviado a {len(destinos)} superadministrador(es).')
