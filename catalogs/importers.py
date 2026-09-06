import csv
import hashlib
import io

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import CatalogRelease, CatalogReleaseStatus, DiagnosisCode, ProcedureCode

MODEL_BY_SYSTEM = {'CID10': DiagnosisCode, 'TUSS': ProcedureCode}


class DuplicateReleaseVersion(Exception):
    pass


class ImportReport:
    def __init__(self):
        self.total = 0
        self.created = 0
        self.errors = []


def _parse_rows(content_text):
    reader = csv.DictReader(io.StringIO(content_text))
    rows = []
    errors = []
    for line_number, row in enumerate(reader, start=2):
        code = (row.get('code') or '').strip()
        description = (row.get('description') or '').strip()
        parent_code = (row.get('parent_code') or '').strip()
        if not code or not description:
            errors.append(f'Line {line_number}: code and description are required')
            continue
        rows.append({'code': code, 'description': description, 'parent_code': parent_code})
    return rows, errors


def import_catalog(system, version, content_text, source_url='', license_note='', dry_run=True):
    """Parses a code,description[,parent_code] CSV and, unless dry_run, creates
    a new CatalogRelease + its codes. Never touches a previously imported
    release: a new version is always a new release, so historical
    description/code snapshots already referenced by clinical records are
    never rewritten.
    """
    if system not in MODEL_BY_SYSTEM:
        raise ValueError(f'Unknown catalog system: {system}')
    model = MODEL_BY_SYSTEM[system]
    rows, errors = _parse_rows(content_text)
    report = ImportReport()
    report.total = len(rows) + len(errors)
    report.errors = errors
    if dry_run:
        report.created = len(rows)
        return report, None
    content_sha256 = hashlib.sha256(content_text.encode()).hexdigest()
    try:
        with transaction.atomic():
            release = CatalogRelease.objects.create(
                system=system, version=version, source_url=source_url,
                imported_at=timezone.now(), content_sha256=content_sha256,
                license_note=license_note, status=CatalogReleaseStatus.DRAFT,
            )
            objs = [model(release=release, **row) for row in rows]
            model.objects.bulk_create(objs)
            report.created = len(objs)
    except IntegrityError as exc:
        raise DuplicateReleaseVersion(f'{system} {version} already exists') from exc
    return report, release


def activate_release(release):
    """Marks a release active and supersedes any previous active release of
    the same system — never deletes it, so historical references remain
    resolvable.
    """
    with transaction.atomic():
        CatalogRelease.objects.filter(
            system=release.system, status=CatalogReleaseStatus.ACTIVE,
        ).exclude(id=release.id).update(status=CatalogReleaseStatus.SUPERSEDED)
        release.status = CatalogReleaseStatus.ACTIVE
        release.save(update_fields=['status'])
    return release
