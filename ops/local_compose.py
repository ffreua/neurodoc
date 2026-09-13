import yaml
from ops.env import ROOT, read_env
from ops.make_runtime import prepare_runtime


config = read_env(ROOT / '.env.example')
config.update(read_env(ROOT / '.env'))
config.update(DEBUG='True', ALLOWED_HOSTS='localhost,127.0.0.1',
              CSRF_TRUSTED_ORIGINS='http://localhost:8000,http://127.0.0.1:8000,http://localhost:8080,http://127.0.0.1:8080',
              PUBLIC_BASE_URL='http://localhost:8000',
              SMS_ENABLED='False', AI_ENABLED='False', NEURODOC_DEMO_ALLOWED='True')

# ------------------------------------------------------------------- e-mail
#
# `EMAIL_ENABLED` deixou de ser fixado aqui: vem do `.env`, e o padrao do
# `.env.example` continua sendo `False`. Quem quiser exercitar o envio de
# verdade liga no `.env` e regenera -- e o destino passa a ser o Mailpit,
# nunca a internet.
#
# O Mailpit aceita qualquer coisa e nao entrega a ninguem: e a diferenca
# entre testar a recuperacao de senha e mandar e-mail sem querer para o
# endereco de um paciente que estava no banco de demonstracao.
config.update(EMAIL_HOST='mailpit', EMAIL_PORT='1025',
              EMAIL_USE_TLS='False', EMAIL_HOST_USER='')

if config['EMAIL_ENABLED'] == 'True':
    # O worker exige a senha do SMTP quando o envio esta ligado
    # (`core/settings.py`), e o Mailpit nao pede senha nenhuma. Sem um
    # valor aqui, o worker nem sobe -- falha de configuracao disfarcada de
    # falha de codigo, e a mais chata de diagnosticar.
    segredo = ROOT / '.secrets' / 'NEURODOC_SMTP_PASSWORD'
    atual = segredo.read_text().strip() if segredo.exists() else ''
    if not atual or atual == 'DISABLED':
        segredo.parent.mkdir(mode=0o700, exist_ok=True)
        segredo.write_text('mailpit-nao-pede-senha' + chr(10))
        print('NEURODOC_SMTP_PASSWORD: marcador local gravado (Mailpit dispensa '
              'autenticacao). Substitua pelo valor real ao apontar para um SMTP '
              'de verdade.')
prepare_runtime(config)
stack = yaml.safe_load((ROOT / 'docker-stack.yml').read_text())
stack.pop('version', None)
for key in list(stack):
    if key.startswith('x-'):
        stack.pop(key)
images = {'db': config['POSTGRES_IMAGE'], 'rabbitmq': config['RABBITMQ_IMAGE'],
          'redis': config['REDIS_IMAGE'], 'traefik': config['TRAEFIK_IMAGE']}
for name, service in stack['services'].items():
    service.pop('deploy', None)
    service['restart'] = 'on-failure:10'
    service['image'] = images.get(name, 'neurodoc:dev')
    service['networks'] = ['local']
    if name in ['app', 'celery_worker', 'celery_beat']:
        service['environment'] = {'RELEASE_ID': 'dev', 'ROLLOUT_ID': 'dev'}
    if name == 'app':
        service['build'] = {'context': '.', 'args': {
            'PYTHON_IMAGE': config['PYTHON_IMAGE'], 'RELEASE_ID': 'dev',
        }}
        service['ports'] = ['127.0.0.1:8000:8000']
        service['volumes'] = [item for item in service['volumes'] if isinstance(item, str)]
        service['tmpfs'].append('/run/neurodoc-signing:size=16m,uid=10001,gid=10001,mode=0700')
    if name == 'traefik':
        service['command'] = [
            '--entrypoints.web.address=:80', '--entrypoints.ping.address=:8082',
            '--ping=true', '--ping.entrypoint=ping',
            '--providers.file.filename=/etc/traefik/local.yml',
        ]
        service['environment'] = {}
        service['secrets'] = []
        service['volumes'] = []
        service['configs'] = [{'source': 'traefik_local', 'target': '/etc/traefik/local.yml'}]
        service['ports'] = ['127.0.0.1:8080:80']
        service['healthcheck']['test'] = ['CMD', 'traefik', 'healthcheck', '--ping',
                                         '--entrypoints.ping.address=:8082',
                                         '--ping.entrypoint=ping']
# O capturador de SMTP. Porta 1025 para receber, 8025 para a caixa de
# entrada no navegador. Sem volume: o que ele guarda e descartavel por
# definicao, e uma caixa que sobrevive ao `down` so acumula confusao.
stack['services']['mailpit'] = {
    'image': config['MAILPIT_IMAGE'],
    'restart': 'on-failure:10',
    'networks': ['local'],
    'ports': ['127.0.0.1:8025:8025'],
    'environment': {'MP_SMTP_AUTH_ACCEPT_ANY': '1', 'MP_SMTP_AUTH_ALLOW_INSECURE': '1'},
    'healthcheck': {
        'test': ['CMD', '/mailpit', 'readyz'],
        'interval': '15s', 'timeout': '5s', 'retries': 5,
    },
}

stack['networks'] = {'local': {'driver': 'bridge'}}
stack['volumes'] = {name: {} for name in stack['volumes'] if name != 'letsencrypt'}
stack['configs'] = {
    'postgres_init': {'file': './ops/postgres_init.sh'},
    'infra_entrypoint': {'file': './ops/infra_entrypoint.sh'},
    'traefik_local': {'file': './ops/traefik-local.yml'},
}
stack['secrets'] = {name: {'file': f'./.secrets/{name}'}
                    for name in stack['secrets'] if name != 'CLOUDFLARE_DNS_API_TOKEN'}
(ROOT / 'compose.yml').write_text(yaml.safe_dump(stack, sort_keys=False))
print('compose.yml and development env_files generated; only local HTTP is published.')
