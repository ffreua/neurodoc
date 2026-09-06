from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalogs.importers import DuplicateReleaseVersion, activate_release, import_catalog


class Command(BaseCommand):
    help = (
        'Import a CID-10/TUSS release from a code,description[,parent_code] CSV file. '
        'Defaults to --dry-run: pass --commit to actually create the release, '
        'and --activate to mark it active immediately after.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--system', required=True, choices=['CID10', 'TUSS'])
        parser.add_argument('--catalog-version', required=True, dest='catalog_version')
        parser.add_argument('--file', required=True)
        parser.add_argument('--source-url', default='')
        parser.add_argument('--license-note', default='')
        parser.add_argument('--commit', action='store_true')
        parser.add_argument('--activate', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_file():
            raise CommandError(f'File not found: {path}')
        content_text = path.read_text(encoding='utf-8')
        try:
            report, release = import_catalog(
                options['system'], options['catalog_version'], content_text,
                source_url=options['source_url'], license_note=options['license_note'],
                dry_run=not options['commit'],
            )
        except DuplicateReleaseVersion as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f'Rows read: {report.total}; would create/created: {report.created}')
        for error in report.errors:
            self.stderr.write(error)
        if report.errors:
            raise CommandError(f'{len(report.errors)} row(s) rejected; review before --commit')
        if not options['commit']:
            self.stdout.write('Dry run only; pass --commit to persist this release.')
            return
        self.stdout.write(f'Release created: {release.system} {release.version} (id={release.id})')
        if options['activate']:
            activate_release(release)
            self.stdout.write('Release activated.')
        else:
            self.stdout.write('Release left as draft; activate explicitly after review.')
