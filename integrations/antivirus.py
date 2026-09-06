import subprocess
import tempfile
from pathlib import Path

SCAN_TIMEOUT_SECONDS = 60
UPDATE_TIMEOUT_SECONDS = 300
# The only writable, persistent location for signatures (docker-stack.yml
# mounts the `clamav` volume here on celery_worker only — never on `app`,
# since scanning only happens in the Celery task). clamscan's compiled-in
# default database path is not backed by any volume in this stack, so it
# must always be pointed here explicitly.
CLAMAV_DB_DIR = '/data/clamav'


class ScanUnavailable(Exception):
    """Signature database missing/stale or the scanner itself failed to
    run — the caller must keep the file quarantined with a visible error,
    never treat this as a clean result.
    """


class ScanInfected(Exception):
    def __init__(self, signature):
        self.signature = signature
        super().__init__(signature)


class DefinitionUpdateFailed(Exception):
    pass


def scan_file(path):
    """Runs clamscan locally (same container as the worker; no network
    antivirus service). Returns silently when the file is clean.
    """
    try:
        result = subprocess.run(
            ['clamscan', '--no-summary', '--stdout', f'--database={CLAMAV_DB_DIR}', path],
            capture_output=True, text=True, timeout=SCAN_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise ScanUnavailable('clamscan binary not found') from exc
    except subprocess.TimeoutExpired as exc:
        raise ScanUnavailable('scan timed out') from exc

    if result.returncode == 0:
        return
    if result.returncode == 1:
        # clamscan prints "<path>: <Signature> FOUND" -- keep only the
        # signature name, never the absolute on-disk path, since this
        # reaches scan_error and is rendered back to the uploading tenant.
        line = result.stdout.strip()
        signature = line.rsplit(':', 1)[-1].replace('FOUND', '').strip() if ':' in line else line
        raise ScanInfected(signature or 'unknown signature')
    # returncode >= 2: scanner error (e.g. missing/stale signature database).
    raise ScanUnavailable((result.stderr or result.stdout or 'clamscan error').strip()[:255])


def update_definitions():
    """Refreshes CLAMAV_DB_DIR via freshclam, run every 6h from Celery beat.

    The container already runs as the same UID that owns /data/clamav (see
    Dockerfile), unlike the system clamav/freshclam packages' default
    dedicated UID — so no privilege drop is needed. The config file is
    generated fresh into tmpfs each run since the rest of the filesystem is
    read-only.
    """
    with tempfile.TemporaryDirectory() as tmp:
        conf_path = Path(tmp) / 'freshclam.conf'
        conf_path.write_text(
            'DatabaseMirror database.clamav.net\n'
            f'DatabaseDirectory {CLAMAV_DB_DIR}\n'
            f'UpdateLogFile {tmp}/freshclam.log\n'
            'MaxAttempts 2\nConnectTimeout 15\nReceiveTimeout 60\n',
        )
        try:
            result = subprocess.run(
                ['freshclam', f'--config-file={conf_path}'],
                capture_output=True, text=True, timeout=UPDATE_TIMEOUT_SECONDS,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise DefinitionUpdateFailed(str(exc)) from exc
        if result.returncode != 0:
            raise DefinitionUpdateFailed((result.stderr or result.stdout or 'freshclam error').strip()[:500])
