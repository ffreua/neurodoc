"""O backup e a restauracao aguentam ser usados de verdade?

Este roteiro existe por causa de um defeito que sobreviveu meses: o
`ops/restore.py` importava uma constante que o `ops/deploy.py` deixara de
exportar, e **nenhum roteiro importava o modulo**, de modo que o
`ImportError` so apareceria no dia de restaurar -- o unico dia em que nao
ha segunda chance. Tudo o que este arquivo confere e barato; o que ele
impede nao tem conserto.

Tenta quebrar. As perguntas sao:

- o restaurador **carrega**, e as funcoes que ele chama existem mesmo?
- a trava do backup e uma so dos dois lados, ou sao duas que nao se falam?
- a coleta de lixo e a compactacao recusam rodar com a trava tomada?
- a trava e devolvida depois, inclusive quando o bloco levanta excecao?
- as unidades do systemd apontam para caminho e usuario coerentes, e
  conseguem executar um script versionado em modo 644?
- os scripts do timer usam o Python que tem as dependencias?
- o backup **espera** a trava do deploy em vez de desistir do dia -- e
  diz por que, quando a espera estoura?
"""
import importlib
import inspect
import re
from pathlib import Path

from django.conf import settings as dj_settings
from django.db import connection, connections

failures = []
# `settings.BASE_DIR`, e nao `Path(__file__)`: rodado por
# `manage.py shell < checks/...`, este arquivo e lido do stdin e `__file__`
# aponta para o modulo do Django que fez o `exec`, nao para o roteiro.
ROOT = Path(dj_settings.BASE_DIR)


def confere(condicao, descricao, detalhe=''):
    marca = 'ok  ' if condicao else 'FALHA'
    sufixo = f' ({detalhe})' if detalhe else ''
    print(f'  {marca} {descricao}{sufixo}')
    if not condicao:
        failures.append(descricao)


print('=== 1. o restaurador carrega e as funcoes que ele usa existem ===')
# `import_module`, e nao `from ops import restore`: o erro que isto caca e
# justamente um ImportError no topo do modulo.
restore = None
try:
    restore = importlib.import_module('ops.restore')
    confere(True, 'ops.restore importa')
except Exception as exc:
    confere(False, 'ops.restore importa', f'{type(exc).__name__}: {exc}')

if restore is not None:
    deploy = importlib.import_module('ops.deploy')
    importados = set()
    for nome in dir(restore):
        objeto = getattr(restore, nome, None)
        if getattr(objeto, '__module__', None) == 'ops.deploy':
            importados.add(nome)
    confere(bool(importados), 'restore importa funcoes de ops.deploy', str(len(importados)))
    ausentes = sorted(nome for nome in importados if not hasattr(deploy, nome))
    confere(not ausentes, 'tudo que restore importa de deploy existe la', str(ausentes))
    # O nome que quebrou, conferido explicitamente para a regressao ter dono.
    confere(not hasattr(restore, 'REGISTRY'),
            'restore nao depende mais da constante REGISTRY (virou a funcao registry())')
    parametros = inspect.signature(restore.read_manifest).parameters
    confere('registry_esperado' in parametros,
            'read_manifest recebe o registry por argumento', str(tuple(parametros)))

print('=== 2. a trava do backup e uma so ===')
from documents import archive, retention
from ops.locks import BACKUP_LOCK

confere(retention.BACKUP_LOCK == BACKUP_LOCK, 'a aplicacao usa o numero de ops/locks.py')
backup_py = (ROOT / 'ops/backup.py').read_text(encoding='utf-8')
confere('from ops.locks import BACKUP_LOCK' in backup_py,
        'ops/backup.py usa o mesmo numero, importado do mesmo lugar')
confere('.backup_lock' not in backup_py + inspect.getsource(retention),
        'ninguem mais consulta o arquivo-fantasma /data/media/.backup_lock')
confere('backup_exclusive' in inspect.getsource(archive.compact),
        'a compactacao roda dentro do bloco da trava')
confere('backup_exclusive' in inspect.getsource(retention.garbage_collect),
        'a coleta de lixo roda dentro do bloco da trava')

print('=== 3. com a trava tomada, ninguem mexe em arquivo ===')
# Uma segunda conexao segura a trava, como faria o processo de backup no
# host: advisory lock e reentrante na mesma sessao, entao a disputa so e
# real entre conexoes diferentes.
outra = connections.create_connection('default')
try:
    with outra.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [BACKUP_LOCK])
        tomada = cursor.fetchone()[0]
    confere(tomada, 'a sessao que simula o backup tomou a trava', '' if tomada else 'ja ocupada')

    if tomada:
        for nome, funcao in [
            ('a coleta de lixo', lambda: retention.garbage_collect(dry_run=True)),
            ('a compactacao', lambda: archive.compact(dry_run=True)),
        ]:
            try:
                funcao()
                confere(False, f'{nome} recusa rodar durante o backup', 'rodou assim mesmo')
            except retention.BackupInProgress:
                confere(True, f'{nome} recusa rodar durante o backup')

        with outra.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [BACKUP_LOCK])
finally:
    outra.close()

print('=== 4. a trava e devolvida, inclusive depois de erro ===')
try:
    with retention.backup_exclusive('o teste'):
        raise RuntimeError('falha proposital dentro do bloco')
except RuntimeError:
    pass
with connection.cursor() as cursor:
    cursor.execute('SELECT pg_try_advisory_lock(%s)', [BACKUP_LOCK])
    devolvida = cursor.fetchone()[0]
    if devolvida:
        cursor.execute('SELECT pg_advisory_unlock(%s)', [BACKUP_LOCK])
confere(devolvida, 'o bloco devolve a trava mesmo levantando excecao')

print('=== 5. as unidades do systemd conseguem rodar ===')
for unidade, script in [('neurodoc-backup', 'backup.sh'),
                        ('neurodoc-signing-cleanup', 'cleanup_signing_keys.sh'),
                        ('neurodoc-backup-falhou', 'avisar_falha_backup.sh')]:
    linhas = (ROOT / f'ops/{unidade}.service').read_text(encoding='utf-8').splitlines()
    exec_start = next(l for l in linhas if l.startswith('ExecStart='))
    caminho = next(l for l in linhas if l.startswith('WorkingDirectory=')).split('=', 1)[1]
    # O script e versionado em 644 de proposito: um `chmod +x` faria o
    # preflight recusar o deploy por arvore suja. Executa-lo direto daria
    # "Permission denied" sem dizer o porque.
    confere(exec_start.startswith('ExecStart=/bin/sh '),
            f'{unidade}: chama o /bin/sh em vez de executar o script direto', exec_start)
    confere(exec_start.endswith(f'{caminho}/scripts/{script}'),
            f'{unidade}: ExecStart e WorkingDirectory concordam', exec_start)
    confere((ROOT / 'scripts' / script).is_file(), f'{unidade}: o script existe')

setup = (ROOT / 'scripts/setup_deploy.sh').read_text(encoding='utf-8')
destino = re.search(r"DESTINO_PADRAO='([^']+)'", setup).group(1)
unidade_padrao = (ROOT / 'ops/neurodoc-backup.service').read_text(encoding='utf-8')
confere(f'WorkingDirectory={destino}' in unidade_padrao,
        'o caminho padrao do instalador e o das unidades sao o mesmo', destino)
confere('systemctl enable --now' in setup and 'neurodoc-backup.timer' in setup,
        'o instalador liga os timers (nao deixa o backup para depois)')

print('=== 5-A. o backup que falha avisa alguem ===')
# Ate a 1.24.1 a falha so deixava `status=1/FAILURE` no journal. O aviso
# sai pelo worker (so ele tem a credencial de e-mail) para os
# superadministradores, e o instalador tem de instalar a unidade junto --
# unidade no repositorio e fora do /etc/systemd nao avisa ninguem.
confere('OnFailure=neurodoc-backup-falhou.service' in unidade_padrao,
        'a unidade do backup dispara o aviso quando falha')
confere('ops/neurodoc-backup-falhou.service' in setup,
        'o instalador instala a unidade do aviso')
aviso_sh = (ROOT / 'scripts' / 'avisar_falha_backup.sh').read_text(encoding='utf-8')
confere('neurodoc_v1_celery_worker' in aviso_sh and 'avisar_falha_backup' in aviso_sh,
        'o aviso roda no contêiner do worker, que tem a credencial de e-mail')

from django.core import mail as _mail
from django.core.management import call_command as _call
from django.test.utils import override_settings as _override

from accounts.models import User as _User

_super = _User.objects.filter(is_superuser=True, is_active=True).exclude(email='').count()
_criado = None
if not _super:
    # A base de demonstracao nao tem superadministrador; um descartavel
    # para o aviso ter para quem ir.
    _criado = _User.objects.create_user(
        email='aviso-backup@roteiro.invalid', password=None, is_superuser=True, is_staff=True,
    )
try:
    with _override(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
        _mail.outbox = []
        _call('avisar_falha_backup')
        enviados = list(_mail.outbox)
finally:
    if _criado is not None:
        _criado.delete()
confere(len(enviados) == 1 and 'backup' in enviados[0].subject.lower(),
        'o comando manda um e-mail sobre o backup', [m.subject for m in enviados])
if enviados:
    destinatarios = set(enviados[0].to)
    esperados = set(_User.objects.filter(is_superuser=True, is_active=True)
                    .exclude(email='').values_list('email', flat=True))
    if _criado is not None:
        esperados = {'aviso-backup@roteiro.invalid'}
    confere(destinatarios == esperados, 'para os superadministradores ativos, e so para eles')
    confere('journalctl -u neurodoc-backup.service' in enviados[0].body,
            'e diz onde ver o motivo')

print('=== 6. os scripts do timer usam o Python com as dependencias ===')
for script in ['backup.sh', 'cleanup_signing_keys.sh', 'deploy.sh']:
    texto = (ROOT / 'scripts' / script).read_text(encoding='utf-8')
    # `ops.deploy` le YAML e o Python do sistema na VPS nao tem PyYAML:
    # chamar `python3` direto quebra com ModuleNotFoundError na primeira
    # execucao do timer, de madrugada, sem ninguem olhando.
    confere('.venv-ops/bin/python' in texto, f'{script}: prefere o .venv-ops quando ele existe')

print('=== 6-A. o backup ESPERA a trava do deploy, e nao desiste do dia ===')
# Em 2026-10-02 o timer disparou as 03:10:29, no meio de um deploy que
# correu das 03:01 as 03:12. A linha era `flock -n`, e `-n` quer dizer "se
# estiver ocupado, saia": o dia ficou sem backup, com `status=1/FAILURE` no
# journal e **nenhuma linha dizendo por que**.
#
# Tres asercoes, e a terceira importa tanto quanto as outras: esperar, e
# falar quando a espera estourar. Backup que falha calado so se descobre na
# noite de restaurar.
#
# **So as linhas de codigo.** Os comentarios do proprio `backup.sh` citam
# `flock -n` para explicar o defeito que o derrubou; varrer o arquivo
# inteiro reprovaria a explicacao junto com o erro, e o jeito de passar
# seria apagar a explicacao -- exatamente o contrario do que se quer.
backup_sh = (ROOT / 'scripts' / 'backup.sh').read_text(encoding='utf-8')
linhas_sh = [
    linha for linha in backup_sh.splitlines() if not linha.lstrip().startswith('#')
]
confere(not any(re.search(r'flock\s+-n(?![a-zA-Z])', linha) for linha in linhas_sh),
        'backup.sh nao usa `flock -n` (desistir do dia por causa de um deploy)')
confere(any(re.search(r'flock\s+-w\s', linha) for linha in linhas_sh),
        'backup.sh espera pela trava com `flock -w`')
confere('NAO HOUVE BACKUP' in backup_sh,
        'backup.sh diz no journal quando a espera estoura, em vez de sair mudo')

# O deploy desiste quando a trava esta tomada -- e certo, publicar nao
# pode esperar 45 minutos com alguem olhando --, mas desistia **calado**:
# codigo 1, nenhuma linha. Quem o rodava as 03h nao sabia se tinha
# publicado (revisao de 2026-10-22).
deploy_sh = (ROOT / 'scripts' / 'deploy.sh').read_text(encoding='utf-8')
confere('-E 75' in deploy_sh and 'Nada foi publicado' in deploy_sh,
        'deploy.sh diz que nada foi publicado quando a trava esta tomada')

print('=== 7. o que a primeira restauracao de verdade ensinou ===')
#
# Esta secao existe porque o ciclo completo foi exercitado em 20/09/2026
# num Swarm local -- backup cifrado, servidor destruido, restauracao do
# zero -- e tres defeitos so apareceram ali. Nenhum deles se veria lendo
# o codigo.
import inspect as _inspect

fonte_restore = _inspect.getsource(restore) if restore else ''
fonte_deploy = _inspect.getsource(importlib.import_module('ops.deploy'))

# 0. Sem User-Agent, a Cloudflare responde 403 ao pedido das faixas de IP:
#    foi assim que um deploy morreu (commit a7d8132), e o deploy passou a
#    usar `buscar`. A restauracao ficou com o `urlopen` cru ate 2026-10-22
#    -- e pararia ali, no dia do desastre.
confere('urlopen(' not in fonte_restore and 'buscar(' in fonte_restore,
        'a restauracao pede as faixas da Cloudflare com o User-Agent da instalacao')

# 1. `pg_restore --list` le so o indice e fecha o cano; o `age` que ainda
#    escrevia morre de SIGPIPE. Tratar isso como falha fazia a conferencia
#    de integridade do dump -- o primeiro passo da restauracao -- falhar
#    sempre.
confere('_fechou_o_cano' in fonte_restore,
        'a restauracao tolera o produtor morto por cano fechado')
confere('Restore consumer failed' in fonte_restore,
        'e distingue falha do consumidor da falha da decifragem')

# 2. O dump usa `--no-acl`, entao as permissoes nao voltam: a trilha de
#    auditoria renascia gravavel pela aplicacao, com o REVOKE da migration
#    `audit/0003` perdido. O trigger sobrevive (e schema), mas a defesa em
#    profundidade nao.
confere('_reaplicar_permissoes' in fonte_restore,
        'a restauracao reaplica o REVOKE da trilha')
confere('REVOKE UPDATE, DELETE ON audit_auditevent' in fonte_restore,
        'e reaplica exatamente o que a migration faz')

# 3. `resolve_image` comparava a referencia COM tag contra digests SEM
#    tag: nunca casava, e caia no primeiro digest da lista. Com a imagem
#    tagueada em dois repositorios, o primeiro vira sorteio -- e o
#    registro da release guardava a referencia do repositorio errado, que
#    a restauracao recusa com "Unexpected application registry".
deploy_mod = importlib.import_module('ops.deploy')
confere(hasattr(deploy_mod, 'repositorio_de'),
        'o deploy sabe extrair o repositorio de uma referencia')
if hasattr(deploy_mod, 'repositorio_de'):
    casos = [
        ('ghcr.io/dono/app:abc123', 'ghcr.io/dono/app'),
        ('ghcr.io/dono/app@sha256:aa', 'ghcr.io/dono/app'),
        ('localhost:5000/app:tag', 'localhost:5000/app'),
        ('postgres:17.11-bookworm', 'postgres'),
    ]
    errados = [
        (entrada, deploy_mod.repositorio_de(entrada), esperado)
        for entrada, esperado in casos
        if deploy_mod.repositorio_de(entrada) != esperado
    ]
    confere(not errados, 'tag e digest sao removidos, a porta do registry nao', str(errados))

# As conferencias sobre o `.env.example` ficam no preflight do deploy, e
# nao aqui: `.dockerignore` exclui `.env.*` da imagem -- de proposito --,
# entao o molde nao existe de dentro do container. E o preflight e o lugar
# certo mesmo, porque roda no host e imediatamente antes de publicar.

if failures:
    print()
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print()
print('OK: o restaurador carrega, a trava e uma so e os timers conseguem rodar.')
