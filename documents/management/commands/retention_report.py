"""Situação de guarda dos prontuários.

Só relata. A eliminação de prontuário é ato com consequência jurídica e
não sai de um comando que roda sozinho — nem de um que roda por engano.
"""

from django.core.management.base import BaseCommand

from documents.retention import RETENTION_YEARS, purge_candidates, retention_report


class Command(BaseCommand):
    help = (
        f'Relata a guarda legal de {RETENTION_YEARS} anos (Lei 13.787/2018, art. 6º) '
        'de cada prontuário. Não elimina nada.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default=None, help='Restringe a uma clínica (UUID).')
        parser.add_argument('--vencidos', action='store_true',
                            help='Lista só os prontuários com prazo já vencido.')

    def handle(self, *args, **options):
        if options['vencidos']:
            linhas = purge_candidates(options['tenant'])
            if not linhas:
                self.stdout.write(self.style.SUCCESS(
                    f'Nenhum prontuário com os {RETENTION_YEARS} anos de guarda vencidos. '
                    'Nada pode ser eliminado.'
                ))
                return
        else:
            linhas = retention_report(options['tenant'])

        self.stdout.write(
            f'{"Prontuário":12}{"Paciente":34}{"Último registro":18}'
            f'{"Guarda até":14}{"Faltam":10}'
        )
        self.stdout.write('-' * 88)
        sem_registro = 0
        for linha in sorted(linhas, key=lambda x: x['expires_at'] or x['patient'].created_at):
            patient = linha['patient']
            if linha['expires_at'] is None:
                sem_registro += 1
                continue
            faltam = f'{linha["years_left"]} anos' if not linha['eligible'] else 'VENCIDO'
            self.stdout.write(
                f'{patient.record_number or "—":12}'
                f'{patient.full_name[:32]:34}'
                f'{linha["last_record_at"].strftime("%d/%m/%Y"):18}'
                f'{linha["expires_at"].strftime("%d/%m/%Y"):14}'
                f'{faltam:10}'
            )
        if sem_registro:
            self.stdout.write(
                f'\n{sem_registro} cadastro(s) sem registro clínico — a guarda de '
                'prontuário não se aplica a eles.'
            )
        vencidos = sum(1 for x in linhas if x['eligible'])
        self.stdout.write(f'\nTotal: {len(linhas)} · vencidos: {vencidos}')
        if vencidos:
            self.stdout.write(self.style.WARNING(
                'Prontuário com prazo vencido pode ser eliminado, e não precisa ser. '
                'A CFM 1.821/2007 prevê guarda permanente para o que está arquivado '
                'eletronicamente; a decisão é da clínica, documento a documento.'
            ))
