from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from exams.loader import DATA_DIR, TemplateLoadError, install_template
from exams.models import ExamTemplateStatus
from tenancy.models import Tenant


class Command(BaseCommand):
    help = (
        'Instala um roteiro de exame em um tenant, como roteiro oficial da '
        'organização. Reinstalar não sobrescreve: cria a versão seguinte, e o '
        'atendimento antigo continua lendo a versão com que foi preenchido. '
        'Sem --tenant, instala em todos os tenants ativos.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--file', default=str(DATA_DIR / 'neurologia.yaml'))
        parser.add_argument('--tenant', help='slug do tenant; omitir instala em todos')
        parser.add_argument('--draft', action='store_true', help='instala como rascunho')
        parser.add_argument('--no-default', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_file():
            raise CommandError(f'Arquivo não encontrado: {path}')

        tenants = Tenant.objects.all()
        if options['tenant']:
            tenants = tenants.filter(slug=options['tenant'])
            if not tenants.exists():
                raise CommandError(f'Tenant não encontrado: {options["tenant"]}')

        status = ExamTemplateStatus.DRAFT if options['draft'] else ExamTemplateStatus.PUBLISHED
        for tenant in tenants:
            try:
                template, counters = install_template(
                    tenant.id, path, status=status, make_default=not options['no_default'],
                )
            except TemplateLoadError as exc:
                raise CommandError(f'{tenant.slug}: {exc}') from exc
            total = sum(counters.values())
            detail = ', '.join(f'{count} {kind}' for kind, count in sorted(counters.items()))
            self.stdout.write(
                f'{tenant.slug}: {template.name} v{template.version} ({status}) — '
                f'{total} nós ({detail})'
            )
