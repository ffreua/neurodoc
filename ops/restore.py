import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from ops.deploy import (
    configuration, create_config, initialize_volumes, preflight, registry,
    resolve_image, run, wait_for_stack,
)
from ops.env import ROOT
from ops.make_runtime import make_traefik, prepare_runtime


def decrypt_to(command, archive, identity, capture=False):
    """Decifra o arquivo e entrega o fluxo a quem vai consumi-lo.

    Quem manda e o **consumidor**. Se ele termina bem, a restauracao
    daquele passo deu certo -- e o `age` pode muito bem ter terminado mal
    por causa disso: `pg_restore --list` le so o indice do dump e fecha o
    cano, e o `age` que ainda escrevia morre com "pipe fechado" (EPIPE no
    Windows, SIGPIPE no Linux, onde o codigo vem negativo).

    A versao anterior levantava erro nesse caso. O efeito era a conferencia
    de integridade do dump -- o primeiro passo de `--prepare-data` --
    falhar sempre, com a mensagem generica "Restore decryption or consumer
    failed", justamente no dia de restaurar. Foi assim que este defeito
    apareceu: na primeira restauracao de verdade.

    Dado truncado nao passa escondido por isso: um fluxo que acaba antes
    da hora faz o proprio `pg_restore` ou `tar` falhar, e a falha dele
    continua sendo erro.
    """
    source = subprocess.Popen(['age', '-d', '-i', identity, str(archive)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        target = subprocess.run(command, stdin=source.stdout,
                                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        source.stdout.close()
        code = source.wait(timeout=3600)
        if target.returncode:
            raise RuntimeError(
                f'Restore consumer failed ({target.returncode}); '
                f'decryption exited {code}'
            )
        if code and not _fechou_o_cano(code):
            raise RuntimeError(f'Restore decryption failed ({code})')
        return target.stdout if capture else None
    finally:
        if source.poll() is None:
            source.kill()
            source.wait()


def _fechou_o_cano(code):
    """O produtor morreu porque o consumidor parou de ler?

    POSIX: SIGPIPE chega como `-13`, ou `141` quando um shell no meio
    converte o sinal. Windows: o `age` sai com `1` e escreve no stderr, que
    aqui esta descartado -- entao o `1` e aceito, e quem garante o
    resultado e o codigo de saida do consumidor, ja conferido acima.
    """
    return code in (-13, 141, 1)


def _reaplicar_permissoes(database):
    """Devolve a trilha de auditoria ao estado somente-insercao.

    O dump e feito com `--no-owner --no-acl`, de proposito: ele precisa
    restaurar num servidor onde os papeis podem ter outra senha, e trazer
    dono e permissoes junto faria a restauracao falhar por detalhe de
    ambiente. O preco e que as permissoes **nao** voltam -- as tabelas
    renascem com o que o `ALTER DEFAULT PRIVILEGES` do `postgres_init.sh`
    concede, que e tudo.

    Para toda tabela isso e o certo. Para `audit_auditevent` nao: o
    `REVOKE UPDATE, DELETE` da migration `audit/0003` some, e o servidor
    recuperado fica com a trilha gravavel pela aplicacao. O trigger
    sobrevive (ele e schema, e vem no dump), entao a protecao principal
    continua de pe -- mas a defesa em profundidade se perderia em
    silencio, e justamente no servidor que nasceu de um desastre.

    Descoberto na primeira restauracao de verdade, conferindo
    `information_schema.role_table_grants` depois dela.
    """
    sql = (
        "DO $reaplicar$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neurodoc_app') THEN "
        "REVOKE UPDATE, DELETE ON audit_auditevent FROM neurodoc_app; "
        "END IF; END $reaplicar$;"
    )
    run(['docker', 'exec', database, 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1',
         '-U', 'postgres', '-d', 'neurodoc', '-c', sql])


def read_manifest(folder, registry_esperado):
    """Confere o backup e devolve o registro da release que o gerou.

    O registry chega **por argumento**, e nao e lido daqui de dentro: ele
    e uma configuracao da instalacao (`REGISTRY` no `.env`), nao uma
    constante do codigo. Ate a correcao deste modulo isto era
    `from ops.deploy import REGISTRY` -- uma constante que o deploy deixou
    de exportar quando o registry virou configuravel. O restaurador nao
    importava mais, e ninguem percebia: nenhum roteiro de `checks/` importa
    `ops.restore`, de modo que a falha so apareceria no dia de restaurar.
    """
    if not (folder / 'COMPLETE').is_file():
        raise RuntimeError('Incomplete backup')
    manifest = json.loads((folder / 'manifest.json').read_text())
    expected = {'database.dump.age', 'media.tar.age', 'signing.tar.age', 'letsencrypt.tar.age'}
    if set(manifest['files']) != expected:
        raise RuntimeError('Unexpected archive list')
    for name, info in manifest['files'].items():
        path = folder / name
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1048576), b''):
                digest.update(chunk)
        if digest.hexdigest() != info['sha256'] or path.stat().st_size != info['bytes']:
            raise RuntimeError(f'Archive integrity mismatch: {name}')
    record = manifest['release']
    if not record['APP_IMAGE'].startswith(registry_esperado + '@sha256:'):
        raise RuntimeError('Unexpected application registry')
    return record


def prepare_data(folder, identity, record):
    if not identity:
        raise RuntimeError('--identity is required for data restoration')
    services = run(['docker', 'service', 'ls', '--format', '{{.Name}}']).splitlines()
    if any(name.startswith('neurodoc_v1_') or name == 'neurodoc_restore_db' for name in services):
        raise RuntimeError('Use a separate empty recovery host')
    volumes = run(['docker', 'volume', 'ls', '--format', '{{.Name}}']).splitlines()
    if any(name.startswith('neurodoc_v1_') for name in volumes):
        raise RuntimeError('Recovery refuses existing NeuroDoc volumes')
    for key in ['APP_IMAGE', 'POSTGRES_IMAGE']:
        resolve_image(record[key])
    for name in ['postgres', 'media', 'signing', 'letsencrypt']:
        run(['docker', 'volume', 'create', f'neurodoc_v1_{name}'])
    pgconfig = create_config(ROOT / 'ops/postgres_init.sh', 'pginit')
    command = [
        'docker', 'service', 'create', '--name', 'neurodoc_restore_db',
        '--network', 'neurodoc_v1_internal', '--constraint', 'node.labels.neurodoc_data==true',
        '--mount', 'type=volume,source=neurodoc_v1_postgres,target=/var/lib/postgresql/data',
        '--config', f'source={pgconfig},target=/docker-entrypoint-initdb.d/10-neurodoc.sh,mode=0555',
        '--env', 'POSTGRES_DB=neurodoc', '--env', 'POSTGRES_USER=postgres',
        '--env', 'POSTGRES_PASSWORD_FILE=/run/secrets/NEURODOC_DB_ADMIN_PASSWORD',
        '--env', 'POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=trust',
        '--health-cmd', 'pg_isready -U postgres -d neurodoc', '--health-interval', '5s',
        '--health-retries', '20', '--limit-memory', '2G', '--replicas', '1',
    ]
    for name in ['ADMIN', 'OWNER', 'APP']:
        command += ['--secret', f'NEURODOC_DB_{name}_PASSWORD']
    run(command + [record['POSTGRES_IMAGE']])
    database = None
    for attempt in range(120):
        ids = run(['docker', 'ps', '-q', '--filter',
                   'label=com.docker.swarm.service.name=neurodoc_restore_db']).splitlines()
        if len(ids) == 1:
            state = json.loads(run(['docker', 'inspect', ids[0]]))[0]['State']
            if state.get('Health', {}).get('Status') == 'healthy':
                database = ids[0]
                break
        time.sleep(2)
    if not database:
        raise RuntimeError('Recovery database did not become ready')
    listing = decrypt_to(
        ['docker', 'run', '--rm', '-i', '--network', 'none', '--entrypoint', 'pg_restore',
         record['POSTGRES_IMAGE'], '--list'], folder / 'database.dump.age', identity, True,
    ).decode()
    # The bootstrap already created public and the sole approved extension, btree_gist.
    lines = [line for line in listing.splitlines()
             if not re.search(r'\bEXTENSION\b|\bSCHEMA - public\b', line)]
    runtime = ROOT / '.runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    selection = runtime / 'restore.list'
    selection.write_text('\n'.join(lines) + '\n')
    run(['docker', 'cp', str(selection), f'{database}:/tmp/restore.list'])
    decrypt_to(
        ['docker', 'exec', '-i', database, 'pg_restore', '-U', 'postgres',
         '--role=neurodoc_owner', '--no-owner', '--no-acl', '--no-comments',
         '--exit-on-error', '--use-list=/tmp/restore.list', '-d', 'neurodoc'],
        folder / 'database.dump.age', identity,
    )
    for name in ['media', 'signing', 'letsencrypt']:
        decrypt_to(
            ['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0',
             '--entrypoint', 'tar', '--mount',
             f'type=volume,src=neurodoc_v1_{name},dst=/target',
             record['APP_IMAGE'], '-C', '/target', '-xf', '-'],
            folder / f'{name}.tar.age', identity,
        )
    count = run(['docker', 'exec', database, 'psql', '-X', '-qAt', '-U', 'postgres',
                 '-d', 'neurodoc', '-c', 'SELECT count(*) FROM django_migrations;'])
    if not count.isdigit() or int(count) < 1:
        raise RuntimeError('Restored migration history is empty')
    _reaplicar_permissoes(database)
    run(['docker', 'service', 'rm', 'neurodoc_restore_db'])
    for attempt in range(60):
        if not run(['docker', 'ps', '-q', '--filter',
                    'label=com.docker.swarm.service.name=neurodoc_restore_db']):
            break
        time.sleep(2)
    else:
        raise RuntimeError('Wait for the recovery database to stop before activation')
    (runtime / 'restore-data.json').write_text(json.dumps(record, indent=2))
    print('Data restored on isolated host; activation and clinical checks remain pending.')


def activate(record):
    config = configuration()
    preflight(config)
    if config['NEURODOC_RECOVERY_MODE'] != 'True':
        raise RuntimeError('Activate recovery mode to hold domain task consumption')
    for key in ['AI_ENABLED', 'EMAIL_ENABLED', 'SMS_ENABLED']:
        if config[key] != 'False':
            raise RuntimeError('Keep all external channels disabled during recovery')
    if run(['git', 'rev-parse', 'HEAD']) != record['RELEASE_ID']:
        raise RuntimeError('Checkout the exact backed-up release before activation')
    marker = json.loads((ROOT / '.runtime/restore-data.json').read_text())
    if marker['RELEASE_ID'] != record['RELEASE_ID']:
        raise RuntimeError('Data restore marker mismatch')
    params = dict(record, ROLLOUT_ID=uuid.uuid4().hex,
                  APP_REPLICAS=config['APP_REPLICAS'])
    for key in ['APP_IMAGE', 'POSTGRES_IMAGE', 'RABBITMQ_IMAGE', 'REDIS_IMAGE', 'TRAEFIK_IMAGE']:
        params[key] = resolve_image(params[key])
    prepare_runtime(config)
    initialize_volumes(params['APP_IMAGE'])
    cidrs = []
    for suffix in ['ips-v4', 'ips-v6']:
        with urllib.request.urlopen(f'https://www.cloudflare.com/{suffix}', timeout=10) as response:
            cidrs.extend(response.read().decode().splitlines())
    params['TRAEFIK_CONFIG'] = create_config(make_traefik(config, cidrs), 'traefik')
    params['POSTGRES_INIT_CONFIG'] = create_config(ROOT / 'ops/postgres_init.sh', 'pginit')
    params['INFRA_ENTRYPOINT_CONFIG'] = create_config(ROOT / 'ops/infra_entrypoint.sh', 'infra')
    environment = dict(os.environ, **params)
    rendered = run(['docker', 'stack', 'config', '--compose-file', 'docker-stack.yml'], env=environment)
    if '${' in rendered:
        raise RuntimeError('Unresolved recovery configuration')
    run(['docker', 'stack', 'deploy', '--with-registry-auth', '--resolve-image', 'always',
         '--compose-file', 'docker-stack.yml', 'neurodoc_v1'], env=environment)
    wait_for_stack(int(config['DEPLOY_TIMEOUT_SECONDS']))
    (ROOT / '.runtime/last-successful.json').write_text(json.dumps(params, indent=2))
    print('Recovered services healthy; verify origin, records, permissions and files before DNS cutover.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-data', action='store_true')
    group.add_argument('--activate', action='store_true')
    parser.add_argument('--backup-dir', required=True)
    parser.add_argument('--identity')
    args = parser.parse_args()
    folder = Path(args.backup_dir).resolve()
    record = read_manifest(folder, registry(configuration()))
    if args.prepare_data:
        prepare_data(folder, args.identity, record)
    else:
        activate(record)


if __name__ == '__main__':
    main()
