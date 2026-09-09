"""Compacta o arquivo morto de documentos.

Roda por padrão em simulação: mostra o que faria e não toca em nada. Só
com `--aplicar` é que o disco muda — porque o que está aqui é prontuário,
e um comando que altera arquivo médico por engano de digitação é um
comando mal desenhado.
"""

from django.core.management.base import BaseCommand, CommandError

from documents.archive import COMPACT_AFTER_DAYS, compact
from documents.retention import BackupInProgress


def _mb(valor):
    return f'{valor / (1024 * 1024):.1f} MB'


class Command(BaseCommand):
    help = (
        'Comprime anexos publicados com mais de '
        f'{COMPACT_AFTER_DAYS} dias, conferindo o SHA-256 antes de apagar o original.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true',
                            help='Executa de verdade. Sem isto, apenas simula.')
        parser.add_argument('--tenant', default=None,
                            help='Restringe a uma clínica (UUID).')
        parser.add_argument('--limite', type=int, default=None,
                            help='Processa no máximo N arquivos.')

    def handle(self, *args, **options):
        try:
            resumo = compact(
                tenant_id=options['tenant'], limit=options['limite'],
                dry_run=not options['aplicar'],
            )
        except BackupInProgress as exc:
            raise CommandError(str(exc)) from exc

        modo = 'APLICADO' if options['aplicar'] else 'SIMULAÇÃO (use --aplicar para valer)'
        self.stdout.write(f'Modo: {modo}')
        self.stdout.write(f'Arquivos elegíveis: {resumo["considerados"]}')

        if options['aplicar']:
            economizado = resumo['antes'] - resumo['depois']
            proporcao = (economizado / resumo['antes'] * 100) if resumo['antes'] else 0
            self.stdout.write(f'Compactados: {resumo["compactados"]}')
            self.stdout.write(
                f'Espaço: {_mb(resumo["antes"])} → {_mb(resumo["depois"])} '
                f'(economia de {_mb(economizado)}, {proporcao:.0f}%)'
            )
        else:
            self.stdout.write(f'Ocupam hoje: {_mb(resumo["antes"])}')

        for falha in resumo['falhas']:
            self.stdout.write(self.style.ERROR(f'FALHA: {falha}'))
        if resumo['falhas']:
            raise CommandError(
                f'{len(resumo["falhas"])} arquivo(s) não passaram na conferência. '
                'Os originais não foram alterados.'
            )
        self.stdout.write(self.style.SUCCESS('Concluído.'))
