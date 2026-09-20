import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ops.deploy import configuration, run
from ops.env import ROOT
from ops.locks import BACKUP_LOCK


def container_for(service):
    ids = run(['docker', 'ps', '-q', '--filter',
               f'label=com.docker.swarm.service.name=neurodoc_v1_{service}']).splitlines()
    if len(ids) != 1:
        raise RuntimeError(f'Expected one container for {service}')
    return ids[0]


def encrypt_stream(command, output, recipient):
    with output.open('xb') as destination:
        producer = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        try:
            encryptor = subprocess.run(['age', '-r', recipient], stdin=producer.stdout,
                                       stdout=destination, stderr=subprocess.DEVNULL)
            producer.stdout.close()
            code = producer.wait(timeout=3600)
            if code or encryptor.returncode:
                raise RuntimeError('Backup stream or encryption failed')
        finally:
            if producer.poll() is None:
                producer.kill()
                producer.wait()


def main():
    os.umask(0o077)
    config = configuration()
    root = Path(config['BACKUP_DIR'])
    if not root.is_absolute() or root.name != 'neurodoc-backups' or root.is_symlink():
        raise RuntimeError('Use an absolute, non-symlink directory named neurodoc-backups')
    recipient = config['BACKUP_AGE_RECIPIENT']
    if not recipient.startswith('age1'):
        raise RuntimeError('A valid offline age recipient is required')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    record_path = ROOT / '.runtime/last-successful.json'
    record = json.loads(record_path.read_text())
    database = container_for('db')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = root / f'{stamp}-{uuid.uuid4().hex[:8]}'
    target.mkdir(mode=0o700)
    keeper = subprocess.Popen(
        ['docker', 'exec', '-i', '-e', 'PGCONNECT_TIMEOUT=5', database,
         'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'neurodoc'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True,
    )
    locked = False
    try:
        keeper.stdin.write("SET statement_timeout = '10s';\n")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            keeper.stdin.write(f'SELECT pg_try_advisory_lock({BACKUP_LOCK});\n')
            keeper.stdin.flush()
            response = keeper.stdout.readline().strip()
            if response == 't':
                locked = True
                break
            if response != 'f':
                raise RuntimeError('Backup lock session failed')
            time.sleep(2)
        if not locked:
            raise RuntimeError('Backup lock timeout')
        encrypt_stream(
            ['docker', 'exec', database, 'pg_dump', '-U', 'postgres',
             '-d', 'neurodoc', '--format=custom', '--no-owner', '--no-acl', '--no-comments'],
            target / 'database.dump.age', recipient,
        )
        for volume in ['media', 'signing', 'letsencrypt']:
            encrypt_stream(
                ['docker', 'run', '--rm', '--network', 'none', '--user', '0',
                 '--entrypoint', 'tar', '--mount',
                 f'type=volume,src=neurodoc_v1_{volume},dst=/source,readonly',
                 record['APP_IMAGE'], '-C', '/source', '-cf', '-', '.'],
                target / f'{volume}.tar.age', recipient,
            )
        files = {}
        for path in target.iterdir():
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1048576), b''):
                    digest.update(chunk)
            files[path.name] = {'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}
        # A sessao que segura a trava tem de estar viva **agora**, e nao so
        # ter estado viva no comeco: se o container do banco reiniciou no
        # meio da copia, o PostgreSQL devolveu a trava sem avisar e a
        # aplicacao pode ter comprimido ou apagado arquivo enquanto o tar
        # rodava. Um backup assim parece completo e falha na restauracao --
        # que e exatamente o momento em que ninguem tem uma segunda chance.
        if keeper.poll() is not None:
            raise RuntimeError('Backup lock session died mid-copy; discard this backup')
        manifest = {'completed_at': datetime.now(timezone.utc).isoformat(),
                    'release': record, 'files': files,
                    'consistency': 'database snapshot then immutable files; deletion lock held'}
        (target / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        (target / 'COMPLETE').write_text('ok\n')
    finally:
        if keeper.poll() is None:
            try:
                keeper.stdin.write('\\q\n')
                keeper.stdin.flush()
            except BrokenPipeError:
                pass
            try:
                keeper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                keeper.kill()
                keeper.wait()
    if not (target / 'COMPLETE').exists():
        raise RuntimeError('Backup did not complete')
    retention = int(config['BACKUP_RETENTION_DAYS'])
    if retention < 7:
        raise RuntimeError('Retention must be at least seven days')
    cutoff = time.time() - retention * 86400
    for folder in root.iterdir():
        if folder == target or folder.is_symlink() or not folder.is_dir():
            continue
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', folder.name):
            continue
        if (folder / 'COMPLETE').is_file() and folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder)
    print(f'Encrypted backup complete: {target.name}; copy off-host and verify restore.')


if __name__ == '__main__':
    main()
