"""O Traefik lê o Docker pelo proxy, e não pelo socket (auditoria de 2026-11-11).

O Traefik é o único serviço com porta aberta à internet. Com o socket do
Docker montado nele, uma falha no Traefik virava controle do servidor — o
`:ro` não limita a API. O que se tenta quebrar, lendo a pilha e o gerador
da configuração (sem subir nada):

1. **nenhum serviço exposto monta o socket**: só o `docker_proxy` o tem;
2. **o proxy só lê**: `POST` desligado, e nada de contêineres, segredos,
   configurações, imagens, volumes ou execução;
3. **a rede do proxy é fechada**: interna, e só o Traefik e o proxy nela;
4. **o Traefik aponta para o proxy**, na configuração gerada e no exemplo;
5. **a imagem do proxy é fixada** e entra na lista de infraestrutura;
6. **o ambiente local** não leva o proxy (o Traefik local lê um arquivo).
"""
from pathlib import Path

import yaml

from django.conf import settings

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


raiz = Path(settings.BASE_DIR)
pilha = yaml.safe_load((raiz / 'docker-stack.yml').read_text(encoding='utf-8'))
servicos = pilha['services']

print('=== 1. o socket ===')
com_socket = sorted(
    nome for nome, s in servicos.items()
    if any('docker.sock' in (v if isinstance(v, str) else str(v.get('source', '')))
           for v in s.get('volumes', []))
)
conferir('so o docker_proxy monta o socket do Docker', com_socket, ['docker_proxy'])
conferir('o proxy nao publica porta', 'ports' in servicos['docker_proxy'], False)

print('=== 2. o proxy so le ===')
env = {k: str(v) for k, v in (servicos['docker_proxy'].get('environment') or {}).items()}
conferir('POST desligado', env.get('POST'), '0')
abertos = sorted(k for k, v in env.items() if v == '1')
conferir('so as leituras do provedor swarm', abertos, ['INFO', 'NETWORKS', 'NODES', 'SERVICES', 'TASKS'])
perigosos = {'CONTAINERS', 'SECRETS', 'CONFIGS', 'IMAGES', 'VOLUMES', 'EXEC', 'BUILD', 'SWARM',
             'PLUGINS', 'SYSTEM', 'AUTH', 'COMMIT', 'ALLOW_START', 'ALLOW_STOP', 'ALLOW_RESTARTS'}
conferir('nada perigoso ligado', sorted(perigosos & set(abertos)), [])

print('=== 3. a rede do proxy ===')
rede = pilha['networks'].get('docker_api') or {}
conferir('a rede docker_api e interna', rede.get('internal'), True)
na_rede = sorted(n for n, s in servicos.items() if 'docker_api' in (s.get('networks') or []))
conferir('so o Traefik e o proxy nela', na_rede, ['docker_proxy', 'traefik'])

print('=== 4. o Traefik aponta para o proxy ===')
import tempfile

import ops.make_runtime as make_runtime
from ops.make_runtime import make_traefik

# O gerador escreve em `.runtime/`, que no contêiner é só leitura.
temporario = Path(tempfile.mkdtemp())
(temporario / '.runtime').mkdir()
make_runtime.ROOT = temporario
cidrs = [f'173.245.{n}.0/24' for n in range(48, 60)]
caminho = make_traefik({'ACME_EMAIL': 'roteiro@example.com',
                        'ACME_DIRECTORY': 'https://acme-staging-v02.api.letsencrypt.org/directory'},
                       cidrs)
gerado = yaml.safe_load(Path(caminho).read_text(encoding='utf-8'))
conferir('na configuracao gerada', gerado['providers']['swarm']['endpoint'], 'tcp://docker_proxy:2375')
exemplo = yaml.safe_load((raiz / 'ops/traefik.example.yml').read_text(encoding='utf-8'))
conferir('no exemplo', exemplo['providers']['swarm']['endpoint'], 'tcp://docker_proxy:2375')

print('=== 5. a imagem ===')
from ops.deploy import IMAGE_KEYS

conferir('a imagem do proxy esta na lista de infraestrutura', 'DOCKER_PROXY_IMAGE' in IMAGE_KEYS, True)
conferir('e vem da configuracao', servicos['docker_proxy']['image'], '${DOCKER_PROXY_IMAGE}')
if (raiz / '.env.example').exists():
    exemplo_env = (raiz / '.env.example').read_text(encoding='utf-8')
    linha = next((l for l in exemplo_env.splitlines() if l.startswith('DOCKER_PROXY_IMAGE=')), '')
    conferir('com versao fixada (nada de latest)',
             bool(linha) and ':latest' not in linha and ':' in linha.split('=', 1)[1], True)
else:
    # A imagem do app não leva o `.env.example`; o deploy recusa imagem sem
    # versão (`ops/deploy.py::resolve_image`) de qualquer forma.
    print('  --   .env.example fora desta imagem: conferencia da versao pulada')

print('=== 6. o ambiente local ===')
compose = raiz / 'compose.yml'
if compose.exists():
    local = yaml.safe_load(compose.read_text(encoding='utf-8'))
    conferir('o compose local nao tem o proxy', 'docker_proxy' in local['services'], False)
else:
    print('  --   compose.yml nao gerado nesta imagem: conferencia pulada')

print()
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: o Traefik le o Docker so pelo proxy, que so deixa ler.')
