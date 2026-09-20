"""Roda os roteiros de verificação de `checks/`, todos ou os que você pedir.

Até aqui, "rodar a verificação" era um laço de shell escrito na hora, uma
vez por pessoa e uma vez por sessão:

    for f in checks/check_*.py; do
      docker compose exec -T app python manage.py shell < "$f"
    done

Isso funciona e tem dois defeitos. O primeiro é que ninguém escreve o
laço quando está com pressa — e a hora de rodar a verificação é
justamente quando se está com pressa. O segundo é que o laço não diz
nada: ele despeja a saída dos quarenta e cinco roteiros seguidos, e
descobrir qual falhou exige rolar a tela para trás.

Cada roteiro roda em **processo próprio**, como o laço fazia. É mais
lento que carregar todos no mesmo interpretador, e é deliberado: os
roteiros mexem em `settings`, criam e apagam registros e alguns terminam
com `SystemExit`. Compartilhar o interpretador faria o resultado de um
depender de quem rodou antes — e um roteiro que passa por causa do
vizinho não serve para nada.

**Os roteiros vêm da imagem, não do disco de quem chama.** O laço de
shell empurra o arquivo do host pela entrada padrão, então uma edição
vale na hora; este comando lê `checks/` de dentro do contêiner, que é o
código publicado. É o que se quer para verificar uma versão antes de
publicá-la, e é o contrário do que se quer enquanto se **escreve** um
roteiro novo — aí continue usando `manage.py shell < checks/o_seu.py`,
ou reconstrua a imagem.
"""

import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Roda os roteiros de verificação de checks/ em processos separados. '
        'Sem argumentos, roda todos. Sai com código 1 se algum falhar.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'roteiros', nargs='*',
            help='Nomes ou pedaços de nome a rodar (ex.: planos landing). Sem isto, roda todos.',
        )
        parser.add_argument(
            '--listar', action='store_true',
            help='Mostra os roteiros que seriam rodados e sai.',
        )
        parser.add_argument(
            '--parar-no-primeiro', action='store_true',
            help='Para na primeira falha, em vez de rodar a bateria inteira.',
        )
        parser.add_argument(
            '--detalhado', action='store_true',
            help='Mostra a saída de todos, e não só a dos que falharam.',
        )

    def handle(self, *args, **options):
        pasta = Path(settings.BASE_DIR) / 'checks'
        if not pasta.is_dir():
            self.stderr.write(f'Pasta não encontrada: {pasta}')
            return

        # `check_*.py`: um arquivo auxiliar futuro (`_algo.py`) não é
        # roteiro e não deve entrar na bateria só por estar na pasta.
        todos = sorted(pasta.glob('check_*.py'))
        filtros = [f.replace('.py', '') for f in options['roteiros']]
        if filtros:
            escolhidos = [p for p in todos if any(f in p.stem for f in filtros)]
            nao_achados = [f for f in filtros if not any(f in p.stem for p in todos)]
            for f in nao_achados:
                self.stderr.write(self.style.WARNING(f'Nenhum roteiro casa com {f!r}'))
            if not escolhidos:
                self.stderr.write('Nada a rodar.')
                raise SystemExit(1)
        else:
            escolhidos = todos

        if options['listar']:
            for p in escolhidos:
                self.stdout.write(p.stem)
            self.stdout.write(f'\n{len(escolhidos)} roteiro(s).')
            return

        largura = max(len(p.stem) for p in escolhidos)
        falhas = []
        saidas = {}
        comeco = time.monotonic()

        self.stdout.write(f'Rodando {len(escolhidos)} roteiro(s) de {pasta}\n')
        for caminho in escolhidos:
            inicio = time.monotonic()
            resultado = self._rodar(caminho)
            duracao = time.monotonic() - inicio
            saidas[caminho.stem] = resultado.stdout + resultado.stderr
            passou = resultado.returncode == 0
            marca = self.style.SUCCESS('ok   ') if passou else self.style.ERROR('FALHA')
            self.stdout.write(f'  {marca} {caminho.stem:<{largura}}  {duracao:5.1f}s')
            if not passou:
                falhas.append(caminho.stem)
                if options['parar_no_primeiro']:
                    break

        total = time.monotonic() - comeco

        if options['detalhado']:
            for nome, saida in saidas.items():
                self.stdout.write(f'\n{"=" * 70}\n{nome}\n{"=" * 70}\n{saida}')
        elif falhas:
            # A saída de quem falhou vem sempre: sem ela, descobrir o
            # motivo exigiria rodar tudo de novo -- que é exatamente o
            # atrito que este comando existe para tirar do caminho.
            for nome in falhas:
                self.stdout.write(f'\n{"=" * 70}\n{nome}\n{"=" * 70}\n{saidas[nome]}')

        self.stdout.write('')
        if falhas:
            self.stdout.write(self.style.ERROR(
                f'{len(falhas)} de {len(escolhidos)} falharam em {total:.0f}s: {", ".join(falhas)}'
            ))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(
            f'{len(escolhidos)} roteiro(s), nenhuma falha, {total:.0f}s.'
        ))

    def _rodar(self, caminho):
        """Executa um roteiro como `manage.py shell < arquivo`.

        Pelo `shell`, e não importando o arquivo como módulo, porque é
        assim que os roteiros são escritos: código solto no nível do
        arquivo, contando com o ambiente que o `shell` monta. Rodá-los de
        outro jeito aqui faria este comando verificar algo diferente do
        que o `docs/` manda rodar à mão.
        """
        with caminho.open('rb') as entrada:
            return subprocess.run(
                # `-v 0` tira o banner de importacao automatica do shell,
                # que sao seis linhas de ruido antes de cada roteiro e
                # nao muda o que ele executa.
                [sys.executable, str(Path(settings.BASE_DIR) / 'manage.py'), 'shell', '-v', '0'],
                stdin=entrada, capture_output=True, text=True,
                cwd=str(settings.BASE_DIR),
            )
