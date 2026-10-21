"""Importa a lista oficial das substâncias controladas (Anexo I da Portaria 344/98).

Rode no **worker**, que é quem faz trabalho externo (ver `CLAUDE.md` §2):

    docker exec $(docker ps -q -f name=neurodoc_v1_celery_worker | head -1) \\
      python manage.py import_portaria344

Sem `--url`, baixa o ato vigente que o código conhece
(`catalogs.portaria344.URL_PADRAO`). Quando a Anvisa publicar uma
atualização, a página "Lista de substâncias sujeitas a controle especial
no Brasil" aponta o ato novo no Anvisalegis: passe o endereço dele em
`--url`, e rode primeiro com `--dry-run`, que lê e confere sem gravar.
"""

import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalogs import controlados, portaria344


class Command(BaseCommand):
    help = 'Importa a lista oficial das substâncias controladas (Portaria SVS/MS 344/1998).'

    def add_arguments(self, parser):
        parser.add_argument('--url', default=portaria344.URL_PADRAO, help='Endereço do ato no Anvisalegis.')
        parser.add_argument('--arquivo', default='', help='HTML do ato já baixado.')
        parser.add_argument('--versao', default='', help='Nome da release. Padrão: o número da RDC.')
        parser.add_argument('--dry-run', action='store_true', help='Lê e confere, sem gravar.')
        parser.add_argument('--nao-ativar', action='store_true', help='Importa como rascunho.')

    def handle(self, *args, **opcoes):
        if opcoes['arquivo']:
            conteudo, url = Path(opcoes['arquivo']).read_bytes(), ''
        else:
            url = opcoes['url']
            pedido = urllib.request.Request(url, headers={'User-Agent': 'NeuroDoc (lista 344)'})
            try:
                with urllib.request.urlopen(pedido, timeout=60) as resposta:
                    conteudo = resposta.read()
            except OSError as erro:
                raise CommandError(
                    f'Não consegui baixar o ato: {erro}. Este comando roda no worker, '
                    'que é quem baixa arquivo externo.'
                )
        try:
            texto = portaria344.texto_do_html(conteudo)
            listas = portaria344.ler(texto)
        except portaria344.ListaInvalida as erro:
            raise CommandError(f'O texto não tem a forma esperada, nada foi gravado: {erro}')
        nome, atualizacao = portaria344.versao_do_ato(texto)
        self.stdout.write(f'Ato: {nome or "(sem número)"} · atualização do anexo: {atualizacao or "?"}')
        for lista in listas:
            self.stdout.write(f'  Lista {lista.codigo:<3} {len(lista.substancias):>4} substância(s)')
        if opcoes['dry_run']:
            self.stdout.write(self.style.SUCCESS('Ensaio: nada gravado.'))
            return
        try:
            release, n_listas, n_subst = controlados.importar(
                conteudo, url=url, versao=opcoes['versao'], ativar=not opcoes['nao_ativar'],
            )
        except controlados.VersaoRepetida as erro:
            raise CommandError(f'A versão {erro} já foi importada. Use --versao para outro nome.')
        self.stdout.write(self.style.SUCCESS(
            f'Release {release.version} ({release.status}): {n_listas} listas, {n_subst} substâncias.'
        ))
