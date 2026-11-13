"""Cria ou atualiza, na Asaas, o webhook que avisa esta instalação.

    docker exec <worker> python manage.py asaas_webhook            # mostra o que há
    docker exec <worker> python manage.py asaas_webhook --gravar   # cria ou atualiza

Roda no **worker**: é ele que tem a chave da API (CLAUDE.md §2). O token que a
Asaas devolve no cabeçalho `asaas-access-token` é o segredo
`NEURODOC_ASAAS_WEBHOOK_TOKEN`, o mesmo que o `app` confere — por isso o
webhook é gravado por aqui, e não digitado no painel: um token copiado à mão
é um token que um dia não bate.

`--gravar` também tira a fila do estado interrompido (`interrupted: false`):
é o que se faz depois de corrigir a causa de quinze falhas seguidas.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from contratacao import asaas

NOME = 'NeuroDoc (contratação)'


class Command(BaseCommand):
    help = 'Mostra, cria ou atualiza o webhook da Asaas desta instalação.'

    def add_arguments(self, parser):
        parser.add_argument('--gravar', action='store_true')
        parser.add_argument('--email', default='',
                            help='Quem a Asaas avisa quando a fila falha (padrão: LEADS_EMAIL).')

    def handle(self, *args, **opts):
        token = getattr(settings, 'ASAAS_WEBHOOK_TOKEN', '') or ''
        if not token or token == 'DISABLED' or len(token) < 32:
            raise CommandError('NEURODOC_ASAAS_WEBHOOK_TOKEN ausente ou curto (mínimo 32 caracteres).')
        url = settings.PUBLIC_BASE_URL.rstrip('/') + '/asaas/webhook/'
        if not url.startswith('https://'):
            raise CommandError(f'A Asaas só entrega em HTTPS público; PUBLIC_BASE_URL dá {url}.')
        try:
            existentes = asaas.chamar('GET', 'webhooks?limit=50').get('data') or []
        except (asaas.AsaasErro, asaas.AsaasIndisponivel) as exc:
            raise CommandError(str(exc)) from exc
        nosso = next((w for w in existentes if w.get('url') == url), None)
        for w in existentes:
            self.stdout.write(
                f"- {w.get('id')} {w.get('name')!r} {w.get('url')} enabled={w.get('enabled')} "
                f"interrupted={w.get('interrupted')} penalizados={w.get('penalizedRequestsCount')} "
                f"token={'sim' if w.get('hasAuthToken') else 'não'} eventos={len(w.get('events') or [])}"
            )
        if not opts['gravar']:
            self.stdout.write('Nada gravado (use --gravar).')
            return
        corpo = {
            'name': NOME, 'url': url,
            'email': opts['email'] or settings.LEADS_EMAIL,
            'enabled': True, 'interrupted': False, 'apiVersion': 3,
            'authToken': token, 'sendType': 'SEQUENTIALLY',
            'events': asaas.EVENTOS_DO_WEBHOOK,
        }
        try:
            if nosso:
                resposta = asaas.chamar('PUT', f"webhooks/{nosso['id']}", corpo)
                self.stdout.write(self.style.SUCCESS(f"Webhook {resposta.get('id')} atualizado."))
            else:
                resposta = asaas.chamar('POST', 'webhooks', corpo)
                self.stdout.write(self.style.SUCCESS(f"Webhook {resposta.get('id')} criado."))
        except (asaas.AsaasErro, asaas.AsaasIndisponivel) as exc:
            raise CommandError(str(exc)) from exc
