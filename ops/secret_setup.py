import argparse
import base64
import getpass
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone

import yaml

from ops.env import ROOT, read_env


GENERATED = {
    'NEURODOC_DJANGO_SECRET_KEY', 'NEURODOC_DB_ADMIN_PASSWORD',
    'NEURODOC_DB_OWNER_PASSWORD', 'NEURODOC_DB_APP_PASSWORD',
    'NEURODOC_RABBITMQ_PASSWORD', 'NEURODOC_REDIS_PASSWORD',
}

#: Chaves-mestras. Formato Fernet (32 bytes em base64 urlsafe), geradas —
#: e **separadas por finalidade**: comprometer a chave que abre os segredos
#: da clínica não deve dar acesso ao certificado de assinatura.
FERNET_KEYS = {
    'NEURODOC_PFX_MASTER_KEY',
    'NEURODOC_SECRETS_MASTER_KEY',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', action='store_true')
    parser.add_argument('--recover')
    parser.add_argument('--identity')
    args = parser.parse_args()
    os.umask(0o077)
    names = list(yaml.safe_load((ROOT / 'docker-stack.yml').read_text())['secrets'])
    existing = []
    if not args.local:
        existing = subprocess.run(['docker', 'secret', 'ls', '--format', '{{.Name}}'],
                                  capture_output=True, text=True, check=True).stdout.splitlines()
        if not args.recover and any(name in existing for name in names):
            raise RuntimeError('Secrets already exist; use the original recovery bundle')
    if args.recover:
        if not args.identity or args.local:
            parser.error('--recover requires --identity and Swarm mode')
        payload = subprocess.run(['age', '-d', '-i', args.identity, args.recover],
                                 capture_output=True, check=True).stdout
        values = json.loads(payload)
        if set(values) != set(names):
            raise RuntimeError('Recovery bundle does not match secret names')
    else:
        values = {}
        for name in names:
            if name in GENERATED:
                values[name] = secrets.token_hex(32)
            elif name in FERNET_KEYS:
                # Chave-mestra é gerada, nunca digitada. Digitada, ela cairia
                # no ramo abaixo e um Enter a deixaria 'DISABLED' — o que,
                # no caso da SECRETS_MASTER_KEY, devolveria silenciosamente o
                # compartilhamento com a chave do certificado que ela existe
                # para desfazer.
                values[name] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
            elif name == 'CLOUDFLARE_DNS_API_TOKEN' and not args.local:
                values[name] = getpass.getpass('Cloudflare DNS API token: ')
                if not values[name]:
                    raise RuntimeError('Cloudflare token is required')
            elif not args.local:
                values[name] = getpass.getpass(f'{name} (empty disables channel): ') or 'DISABLED'
            else:
                values[name] = 'DISABLED'
        if not args.local:
            config = read_env(ROOT / '.env')
            recipient = config.get('BACKUP_AGE_RECIPIENT', '')
            if not recipient.startswith('age1'):
                raise RuntimeError('Configure the offline backup public key')
            runtime = ROOT / '.runtime'
            runtime.mkdir(mode=0o700, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            target = runtime / f'bootstrap-secrets-{stamp}.age'
            subprocess.run(['age', '-r', recipient, '-o', str(target)],
                           input=json.dumps(values).encode(), check=True)
            print(f'Encrypted recovery bundle: {target.name}')
    if args.local:
        folder = ROOT / '.secrets'
        folder.mkdir(mode=0o700, exist_ok=True)
        for name, value in values.items():
            target = folder / name
            if not target.exists():
                target.write_text(value)
                target.chmod(0o600)
        print('Development secrets prepared. External channels remain disabled.')
        return
    for name, value in values.items():
        if name not in existing:
            subprocess.run(['docker', 'secret', 'create', name, '-'],
                           input=value.encode(), stdout=subprocess.DEVNULL, check=True)
    print('Swarm secrets prepared. Copy the encrypted recovery bundle off the VPS.')


if __name__ == '__main__':
    main()
