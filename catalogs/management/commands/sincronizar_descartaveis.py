"""Atualiza agora a lista de domínios de e-mail descartável.

Roda no worker, que é quem tem saída para a internet (CLAUDE.md §2):

    docker exec <worker> python manage.py sincronizar_descartaveis

`--arquivo` lê de um arquivo local em vez de baixar — para conferir uma
lista antes de ela valer, ou numa máquina sem rede. É o mesmo caminho da
tarefa de domingo: a mesma conferência, a mesma troca numa transação, o
mesmo aviso por e-mail quando falha.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Baixa, confere e grava a lista de domínios de e-mail descartável.'

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', help='Lê a lista deste arquivo em vez de baixar.')

    def handle(self, *args, **opcoes):
        from catalogs import descartaveis

        conteudo = None
        if opcoes.get('arquivo'):
            with open(opcoes['arquivo'], 'rb') as fh:
                conteudo = fh.read()
        resultado = descartaveis.sincronizar(conteudo)
        if not resultado['ok']:
            raise CommandError(resultado['erro'])
        self.stdout.write(
            f"Lista gravada: {resultado['total']} domínios "
            f"({resultado['entraram']} entraram, {resultado['sairam']} saíram)."
        )
