import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from base.version import VERSION, version_display
from ops.env import ROOT, read_env
from ops.make_runtime import make_traefik, prepare_runtime


STACK = 'neurodoc_v1'

#: UID do usuario da aplicacao dentro da imagem (`Dockerfile`). Os volumes
#: e binds que o app escreve precisam pertencer a ele.
APP_UID = 10001

#: Registry de onde o Swarm puxa a imagem da aplicacao.
#:
#: Era uma constante em codigo, apontando para `ghcr.io/pycodebr/scsi_v1`
#: -- o repositorio de **outro** projeto, herdado do esqueleto. Quem
#: publicasse o NeuroDoc num dominio proprio nao teria permissao de escrita
#: la, e o deploy pararia no `docker push` depois de ja ter construido a
#: imagem.
#:
#: Virou configuracao, e nao um `sed` no arquivo: o PRD (P-02) pede que o
#: registry nao seja renomeado unilateralmente, e uma variavel de ambiente
#: deixa a escolha com quem opera a instalacao, registrada no `.env` dela,
#: sem tocar no codigo versionado.
DEFAULT_REGISTRY = 'ghcr.io/pycodebr/scsi_v1'
SERVICES = ['app', 'celery_worker', 'celery_beat', 'db', 'rabbitmq', 'redis', 'traefik']
IMAGE_KEYS = ['PYTHON_IMAGE', 'POSTGRES_IMAGE', 'RABBITMQ_IMAGE', 'REDIS_IMAGE', 'TRAEFIK_IMAGE']


def run(args, env=None, input_text=None):
    result = subprocess.run(args, cwd=ROOT, env=env, input=input_text,
                            text=True, capture_output=True)
    if result.returncode:
        # Detailed output may contain application data; do not print it here.
        raise RuntimeError(f'Command failed: {args[0]} {args[1]} (exit {result.returncode})')
    return result.stdout.strip()


#: Como este deploy se identifica nas requisicoes HTTP que faz.
#:
#: A Cloudflare devolve **403** para o `Python-urllib/3.x` que o urllib
#: manda por padrao. O deploy parava ao buscar as faixas de IP dela --
#: depois de ja ter construido e publicado a imagem, no passo que apenas
#: monta a configuracao do Traefik -- e a mensagem, um `HTTP Error 403`
#: sem URL, nao dizia de onde vinha.
#:
#: Identificar-se pelo nome do produto, e nao imitar um navegador: quem le
#: o log do outro lado precisa saber quem bateu na porta, e um User-Agent
#: de Chrome vindo de um servidor e o tipo de disfarce que volta como
#: bloqueio mais duro no dia em que for percebido.
USER_AGENT = f'NeuroDoc/{VERSION} (+https://neurodoc.app.br)'


def buscar(url, timeout):
    """GET com o `USER_AGENT` desta instalacao."""
    pedido = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    return urllib.request.urlopen(pedido, timeout=timeout)


def configuration():
    defaults = read_env(ROOT / '.env.example')
    custom = read_env(ROOT / '.env')
    unknown = set(custom) - set(defaults)
    if unknown:
        raise ValueError(f'Unknown configuration keys: {sorted(unknown)}')
    defaults.update(custom)
    return defaults


def inspect_network(name, internal):
    data = json.loads(run(['docker', 'network', 'inspect', name]))[0]
    if data['Driver'] != 'overlay' or data['Scope'] != 'swarm':
        raise RuntimeError(f'Invalid network driver/scope: {name}')
    if bool(data['Internal']) != internal:
        raise RuntimeError(f'Invalid network isolation: {name}')


def registry(config):
    """O registry desta instalacao, com o historico como padrao."""
    return (config.get('REGISTRY') or '').strip() or DEFAULT_REGISTRY


def preflight(config):
    alvo = registry(config)
    if '/' not in alvo or ':' in alvo.split('/')[-1]:
        raise RuntimeError(
            f'REGISTRY invalido: {alvo!r}. Use `host/namespace/repositorio`, '
            'sem tag -- a tag e o SHA do commit, posta pelo proprio deploy.'
        )
    if config['DEBUG'] != 'False':
        raise RuntimeError('Production requires DEBUG=False')
    if config['NEURODOC_RELEASE_APPROVED'] != 'True':
        raise RuntimeError('Release homologation has not been recorded')
    if config['NEURODOC_SCHEMA_CHANGE'] != 'expand':
        raise RuntimeError('Destructive schema changes require a maintenance procedure')
    hosts = set(config['ALLOWED_HOSTS'].split(','))
    if not {'neurodoc.app.br', '.neurodoc.app.br', 'localhost', '127.0.0.1'} <= hosts:
        raise RuntimeError('Required ALLOWED_HOSTS entries missing')
    origins = set(config['CSRF_TRUSTED_ORIGINS'].split(','))
    if not {'https://neurodoc.app.br', 'https://*.neurodoc.app.br'} <= origins:
        raise RuntimeError('Required CSRF trusted origins missing')
    if config['PUBLIC_BASE_URL'] != 'https://neurodoc.app.br':
        raise RuntimeError('Unexpected production base URL')
    if int(config['APP_REPLICAS']) < 2:
        raise RuntimeError('Production rollout baseline requires two web replicas')
    if config['ACME_EMAIL'] == 'CHANGE_ME' or '@' not in config['ACME_EMAIL']:
        raise RuntimeError('Configure the ACME account email')
    # `TRUSTED_PROXIES=` vazia nao e "usa o padrao": `env.list` devolve
    # lista vazia, e o valor declarado vence o default do `settings`. O
    # efeito e o produto deixar de confiar em proxy nenhum -- atras do
    # Traefik, `base/net.py` passa a devolver o IP **dele** para todo
    # visitante, e o limite de vinte consultas ao QR da receita vira um
    # balde unico para o planeta inteiro. Para usar o padrao, a linha sai
    # do `.env`; vazia, ela e uma decisao silenciosa.
    if 'TRUSTED_PROXIES' in read_env(ROOT / '.env') and not config['TRUSTED_PROXIES'].strip():
        raise RuntimeError(
            'TRUSTED_PROXIES esta declarada e vazia: remova a linha do .env para '
            'usar o padrao, ou preencha as faixas dos proxies confiaveis'
        )
    info = json.loads(run(['docker', 'info', '--format', '{{json .Swarm}}']))
    if info.get('LocalNodeState') != 'active' or not info.get('ControlAvailable'):
        raise RuntimeError('Run on an active Swarm manager')
    nodes = run(['docker', 'node', 'ls', '-q']).splitlines()
    if len(nodes) != 1 or config['NEURODOC_NODES'] != '1':
        raise RuntimeError('This deployment requires the documented single-node topology')
    node = json.loads(run(['docker', 'node', 'inspect', 'self']))[0]
    if node['Spec'].get('Labels', {}).get('neurodoc_data') != 'true':
        raise RuntimeError('The persistent-data node label is missing')
    for name, internal in [('traefik_public', False),
                           ('neurodoc_v1_internal', True),
                           ('neurodoc_v1_egress', False)]:
        inspect_network(name, internal)
    import yaml
    stack = yaml.safe_load((ROOT / 'docker-stack.yml').read_text())
    for name in stack['secrets']:
        run(['docker', 'secret', 'inspect', name, '--format', '{{.ID}}'])
    if run(['findmnt', '-n', '-o', 'FSTYPE', '-T', '/run/neurodoc-signing']) != 'tmpfs':
        raise RuntimeError('Signing session keys must reside on tmpfs')
    # Ser tmpfs nao basta: o diretorio e montado no host, por root, e entra
    # no container por bind. Quem escreve nele e o processo da aplicacao,
    # que roda como UID 10001 (Dockerfile). Montado com o dono padrao, a
    # pasta fica 0700 de root e a primeira assinatura falha com "permission
    # denied" -- em producao, na hora de assinar uma receita, e nao aqui.
    if os.stat('/run/neurodoc-signing').st_uid != APP_UID:
        raise RuntimeError(
            f'/run/neurodoc-signing must be owned by UID {APP_UID} (the container user); '
            f'remount with uid={APP_UID},gid={APP_UID} or chown it'
        )
    for path in ['requirements.txt', 'manage.py', 'core/asgi.py',
                 'accounts/models.py', 'tenancy/middleware.py', 'docs/index.md']:
        if not (ROOT / path).is_file():
            raise RuntimeError(f'Implementation prerequisite missing: {path}')
    lock = (ROOT / 'requirements.txt').read_text()
    if '--hash=' not in lock:
        raise RuntimeError('Resolve and commit requirements.txt with hashes')
    if run(['git', 'status', '--porcelain', '--untracked-files=no']):
        raise RuntimeError('Commit or resolve tracked changes before deployment')


def repositorio_de(referencia):
    """O repositorio de uma referencia, sem tag e sem digest.

    `ghcr.io/dono/app:abc123`      -> `ghcr.io/dono/app`
    `localhost:5000/app@sha256:..` -> `localhost:5000/app`

    A porta do registry e o separador da tag sao os dois `:`, e distingui-los
    exige olhar a ultima barra: o que vem depois dela pode ter tag, o que vem
    antes e host[:porta].
    """
    sem_digest = referencia.split('@')[0]
    depois_da_barra = sem_digest.rsplit('/', 1)[-1]
    if ':' in depois_da_barra:
        return sem_digest[:len(sem_digest) - len(depois_da_barra.split(':', 1)[1]) - 1]
    return sem_digest


def resolve_image(reference):
    if ':latest' in reference or (':' not in reference and '@sha256:' not in reference):
        raise RuntimeError('Unpinned image reference')
    run(['docker', 'pull', reference])
    data = json.loads(run(['docker', 'image', 'inspect', reference]))[0]
    digests = data.get('RepoDigests') or []
    if not digests:
        raise RuntimeError('Registry digest unavailable')
    # A comparacao tira a TAG dos dois lados. Antes ela punha
    # `ghcr.io/dono/app:abc123` contra `ghcr.io/dono/app@sha256:...`, que
    # nunca sao iguais -- entao caia sempre no primeiro digest da lista.
    #
    # Com um repositorio so, o primeiro e o certo por acaso e ninguem
    # percebe. A mesma imagem tagueada em dois (o que acontece ao publicar
    # num registry novo, ou ao testar a restauracao) faz o Docker listar os
    # dois digests, e o primeiro passa a ser sorteio: o registro da release
    # guardaria uma referencia de outro repositorio, e a restauracao a
    # recusaria como "Unexpected application registry" -- no dia de
    # restaurar.
    procurado = repositorio_de(reference)
    for item in digests:
        if repositorio_de(item) == procurado:
            return item
    raise RuntimeError(
        f'Nenhum digest de {procurado} entre os publicados: {digests}'
    )


def create_config(path, prefix):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    name = f'neurodoc_{prefix}_{digest}'
    exists = subprocess.run(['docker', 'config', 'inspect', name],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if exists.returncode:
        run(['docker', 'config', 'create', name, str(path)])
    return name


def initialize_volumes(image):
    import yaml
    stack = yaml.safe_load((ROOT / 'docker-stack.yml').read_text())
    for value in stack['volumes'].values():
        run(['docker', 'volume', 'create', value['name']])
    mounts = []
    for item in ['media', 'staticfiles', 'signing', 'beat', 'clamav']:
        mounts += ['--mount', f'type=volume,src=neurodoc_v1_{item},dst=/data/{item}']
    program = (
        'import os; from pathlib import Path; '
        '[(os.chown(p,10001,10001),os.chmod(p,0o750)) '
        'for p in Path("/data").iterdir() if p.is_dir()]'
    )
    run(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
         '--entrypoint', 'python', *mounts, image, '-c', program])


def wait_for_stack(timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = True
        for service in SERVICES:
            name = f'{STACK}_{service}'
            data = json.loads(run(['docker', 'service', 'inspect', name]))[0]
            state = data.get('UpdateStatus', {}).get('State')
            if state in {'paused', 'rollback_started', 'rollback_paused', 'rollback_completed'}:
                raise RuntimeError(f'Deployment failed or rolled back: {service}')
            if state and state != 'completed':
                ready = False
            desired = data['Spec']['Mode']['Replicated']['Replicas']
            containers = run(['docker', 'ps', '-q', '--filter',
                              f'label=com.docker.swarm.service.name={name}']).splitlines()
            if len(containers) != desired:
                ready = False
                continue
            for container in containers:
                info = json.loads(run(['docker', 'inspect', container]))[0]
                if info['State'].get('Health', {}).get('Status') != 'healthy':
                    ready = False
        if ready:
            apps = run(['docker', 'ps', '-q', '--filter',
                        f'label=com.docker.swarm.service.name={STACK}_app']).splitlines()
            for container in apps:
                run(['docker', 'exec', container, 'python', '/app/ops/probe_ready.py'])
            return
        print('Waiting for service health and convergence...', flush=True)
        time.sleep(10)
    raise RuntimeError('Stack convergence timeout; inspect services before retrying')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument(
        '--check', action='store_true',
        help='Roda so o preflight e sai, sem git pull, build, push ou stack deploy. '
             'Serve para conferir a VPS antes de publicar: sem isto, a unica forma '
             'de descobrir que falta um secret, um rotulo de no ou uma entrada de '
             'ALLOWED_HOSTS e comecar um deploy de verdade.',
    )
    parser.add_argument('--synced', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    config = configuration()
    preflight(config)
    if args.check:
        # Depois do preflight e antes de tudo o mais. O preflight ja recusou
        # o que houvesse de errado; chegar aqui e a resposta.
        print('Preflight aprovado: configuracao, Swarm, redes, secrets, tmpfs e '
              'repositorio estao como o deploy exige.')
        return
    if not args.synced:
        run(['git', 'pull', '--ff-only'])
        options = ['--skip-build'] if args.skip_build else []
        os.execv(sys.executable, [sys.executable, '-m', 'ops.deploy',
                                 *options, '--synced'])
    runtime = prepare_runtime(config)
    record_path = runtime / 'last-successful.json'
    previous = json.loads(record_path.read_text()) if record_path.exists() else None
    images = {key: resolve_image(config[key]) for key in IMAGE_KEYS}
    if previous:
        for key in IMAGE_KEYS[1:]:
            if previous[key] != images[key]:
                raise RuntimeError('Infrastructure image changed: use a planned maintenance upgrade')
    if args.skip_build:
        if not previous:
            raise RuntimeError('--skip-build requires a previous successful release record')
        app_image = resolve_image(previous['APP_IMAGE'])
        release = previous['RELEASE_ID']
    else:
        release = run(['git', 'rev-parse', 'HEAD'])
        if not re.fullmatch(r'[a-f0-9]{40}', release):
            raise RuntimeError('Invalid Git commit identifier')
        tag = f'{registry(config)}:{release}'
        published = subprocess.run(['docker', 'manifest', 'inspect', tag],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if published.returncode != 0:
            run(['docker', 'build', '--pull', '--build-arg',
                 f'PYTHON_IMAGE={images["PYTHON_IMAGE"]}', '--build-arg',
                 f'RELEASE_ID={release}', '-t', tag, '.'])
            run(['docker', 'push', tag])
        app_image = resolve_image(tag)
    label = json.loads(run(['docker', 'image', 'inspect', app_image]))[0]
    if label['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != release:
        raise RuntimeError('Image revision does not match release record')
    initialize_volumes(app_image)
    cidrs = []
    for suffix in ['ips-v4', 'ips-v6']:
        with buscar(f'https://www.cloudflare.com/{suffix}', timeout=10) as response:
            cidrs.extend(response.read().decode().splitlines())
    traefik_file = make_traefik(config, cidrs)
    params = dict(images, APP_IMAGE=app_image, RELEASE_ID=release,
                  ROLLOUT_ID=uuid.uuid4().hex, APP_REPLICAS=config['APP_REPLICAS'])
    # Fica no registro da publicacao, e nao so na imagem: e por ele que se
    # descobre depois qual versao do produto cada release entregou, sem
    # precisar recuperar o commit para ler `base/version.py`.
    params['PRODUCT_VERSION'] = VERSION
    params['POSTGRES_INIT_CONFIG'] = create_config(ROOT / 'ops/postgres_init.sh', 'pginit')
    params['INFRA_ENTRYPOINT_CONFIG'] = create_config(ROOT / 'ops/infra_entrypoint.sh', 'infra')
    params['TRAEFIK_CONFIG'] = create_config(traefik_file, 'traefik')
    command_env = dict(os.environ, **params)
    rendered = run(['docker', 'stack', 'config', '--compose-file', 'docker-stack.yml'], env=command_env)
    if '${' in rendered:
        raise RuntimeError('Unresolved stack variables')
    candidate = runtime / 'candidate.json'
    candidate.write_text(json.dumps(params, indent=2))
    candidate.chmod(0o600)
    run(['docker', 'stack', 'deploy', '--with-registry-auth',
         '--resolve-image', 'always', '--compose-file', 'docker-stack.yml', STACK], env=command_env)
    wait_for_stack(int(config['DEPLOY_TIMEOUT_SECONDS']))
    if 'staging' not in config['ACME_DIRECTORY']:
        with buscar(config['PUBLIC_BASE_URL'] + '/health/', timeout=15) as response:
            if response.status != 200:
                raise RuntimeError('External HTTPS health check failed')
    if record_path.exists():
        (runtime / 'previous-successful.json').write_bytes(record_path.read_bytes())
    record_path.write_text(json.dumps(params, indent=2))
    record_path.chmod(0o600)
    # Os dois numeros na mesma linha, de proposito. O SHA identifica o
    # build e e o que se usa para voltar atras; a versao identifica o
    # produto e e a que se escreve na nota de versao e no chamado. Quem
    # acabou de publicar precisa dos dois a vista.
    print(f'NeuroDoc {version_display()} publicado.')
    print(f'Release {release} deployed; all services are healthy.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
