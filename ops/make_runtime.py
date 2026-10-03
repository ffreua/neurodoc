import ipaddress
from pathlib import Path

import yaml

from ops.env import ROOT, write_env


SECRET_MAP = {
    'DJANGO_SECRET_KEY': 'NEURODOC_DJANGO_SECRET_KEY',
    'DB_APP_PASSWORD': 'NEURODOC_DB_APP_PASSWORD',
    'DB_OWNER_PASSWORD': 'NEURODOC_DB_OWNER_PASSWORD',
    'RABBITMQ_PASSWORD': 'NEURODOC_RABBITMQ_PASSWORD',
    'REDIS_PASSWORD': 'NEURODOC_REDIS_PASSWORD',
    'SMTP_PASSWORD': 'NEURODOC_SMTP_PASSWORD',
    'SMSDEV_API_KEY': 'NEURODOC_SMSDEV_API_KEY',
    'OPENROUTER_API_KEY': 'NEURODOC_OPENROUTER_API_KEY',
    'OPENAI_API_KEY': 'NEURODOC_OPENAI_API_KEY',
    'ANTHROPIC_API_KEY': 'NEURODOC_ANTHROPIC_API_KEY',
    'NVIDIA_API_KEY': 'NEURODOC_NVIDIA_API_KEY',
    'PFX_MASTER_KEY': 'NEURODOC_PFX_MASTER_KEY',
    'SECRETS_MASTER_KEY': 'NEURODOC_SECRETS_MASTER_KEY',
}
COMMON_KEYS = [
    'DEBUG', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', 'TIME_ZONE',
    'PUBLIC_BASE_URL', 'DEFAULT_FROM_EMAIL', 'AI_ENABLED', 'AI_PROVIDER',
    'AI_MODEL', 'EMAIL_ENABLED', 'EMAIL_HOST', 'EMAIL_PORT',
    'EMAIL_HOST_USER', 'EMAIL_USE_TLS', 'EMAIL_USE_SSL',
    'LEADS_EMAIL', 'ALERT_ADMIN_EMAILS', 'SMS_ENABLED', 'NEURODOC_DEMO_ALLOWED',
    'NEURODOC_DOCS_ENABLED',
    'NEURODOC_RECOVERY_MODE',
    'SECURE_HSTS_SECONDS', 'SECURE_HSTS_INCLUDE_SUBDOMAINS',
]

#: Chaves que podem faltar no `.env` sem derrubar o deploy, porque o
#: `core/settings.py` tem um padrao para elas.
#:
#: `COMMON_KEYS` e deliberadamente estrita -- uma chave obrigatoria que
#: some do `.env` tem de parar o deploy, nao virar string vazia dentro do
#: container. Mas acrescentar uma chave **nova** aquela lista quebraria
#: toda instalacao existente na primeira publicacao depois da
#: atualizacao, por uma configuracao que tem padrao e que quase ninguem
#: precisa mudar. Estas entram so quando existem.
OPTIONAL_KEYS = ['TRUSTED_PROXIES', 'AI_BASE_URL_ALLOWLIST',
                 'DOCUMENTS_GC_DRY_RUN',
                 # As duas da politica de conteudo. Faltavam, e a falta era
                 # silenciosa do pior jeito: `core/settings.py` le as duas,
                 # o `.env.example` as declara e a documentacao manda ligar
                 # `CSP_ENFORCE=True` e republicar -- mas a chave nunca
                 # chegava ao container, entao o valor do `.env` nao fazia
                 # efeito nenhum. Quem tentasse ligar o bloqueio veria a
                 # politica continuar em modo relatorio e iria procurar o
                 # defeito no lugar errado.
                 'CSP_ENFORCE', 'CSP_REPORT_URI',
                 # O token do Google Search Console. Opcional pelo motivo
                 # desta lista e por mais um: e **por instalacao**. Quem
                 # subir o NeuroDoc no proprio dominio tem outro token, e
                 # a maioria nao tem nenhum.
                 'GOOGLE_SITE_VERIFICATION']
BASE_SECRETS = ['DJANGO_SECRET_KEY', 'DB_APP_PASSWORD',
                'RABBITMQ_PASSWORD', 'REDIS_PASSWORD']


def prepare_runtime(config):
    runtime = ROOT / '.runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    for role in ['app', 'worker', 'beat']:
        values = {key: config[key] for key in COMMON_KEYS}
        values.update({
            key: config[key] for key in OPTIONAL_KEYS
            if (config.get(key) or '').strip()
        })
        values['SERVICE_ROLE'] = role
        values['RUN_MIGRATIONS'] = 'True' if role == 'app' else 'False'
        names = list(BASE_SECRETS)
        # `SECRETS_MASTER_KEY` vai ao app **e** ao worker. O app a usa para
        # gravar o que o gestor digita; o worker, para decifrar na hora de
        # enviar. Sem ela no worker, o botao de teste funcionava (sincrono,
        # no processo web) e o envio de verdade falhava com SecretUnavailable.
        if role == 'app':
            names += ['DB_OWNER_PASSWORD', 'PFX_MASTER_KEY', 'SECRETS_MASTER_KEY']
        elif role == 'worker':
            names += ['SMTP_PASSWORD', 'SMSDEV_API_KEY',
                      'OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY',
                      'NVIDIA_API_KEY',
                      'SECRETS_MASTER_KEY']
        for name in names:
            values[f'{name}_FILE'] = f'/run/secrets/{SECRET_MAP[name]}'
        write_env(runtime / f'{role}.env', values)
    return runtime


def make_traefik(config, cidrs):
    networks = [str(ipaddress.ip_network(line.strip(), strict=True))
                for line in cidrs if line.strip()]
    if len(networks) < 10:
        raise ValueError('Cloudflare trusted IP list is incomplete')
    data = {
        'api': {'dashboard': False},
        'log': {'level': 'WARN'},
        'ping': {'entryPoint': 'ping'},
        'entryPoints': {
            'web': {
                'address': ':80',
                'forwardedHeaders': {'trustedIPs': networks},
                'http': {'redirections': {'entryPoint': {
                    'to': 'websecure', 'scheme': 'https', 'permanent': True,
                }}},
            },
            'websecure': {
                'address': ':443',
                'forwardedHeaders': {'trustedIPs': networks},
                'transport': {'respondingTimeouts': {
                    'readTimeout': '60s', 'writeTimeout': '0s', 'idleTimeout': '180s',
                }},
            },
            'ping': {'address': ':8082'},
        },
        'providers': {'swarm': {
            'endpoint': 'unix:///var/run/docker.sock',
            'exposedByDefault': False,
            'network': 'traefik_public',
            'constraints': 'Label(`com.neurodoc.platform`, `neurodoc_v1`)',
        }},
        'certificatesResolvers': {'cloudflare': {'acme': {
            'email': config['ACME_EMAIL'],
            'caServer': config['ACME_DIRECTORY'],
            'storage': '/letsencrypt/acme-staging.json' if 'staging' in
                       config['ACME_DIRECTORY'] else '/letsencrypt/acme.json',
            'dnsChallenge': {'provider': 'cloudflare',
                             'resolvers': ['1.1.1.1:53', '8.8.8.8:53']},
        }}},
    }
    path = ROOT / '.runtime/traefik.yml'
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path
