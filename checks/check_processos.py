"""Processos do `app` e tarefas do worker por instalação (2026-11-03).

`APP_WORKERS` e `WORKER_CONCURRENCY` saem do `.env` e chegam ao contêiner
(`ops/make_runtime.OPTIONAL_KEYS`); o `ops/entrypoint.sh` os confere antes de
subir. Este roteiro tenta quebrar as três pontas:

1. **a conferência no shell**: número fora da faixa, vazio, letra e sinal
   param a subida com a explicação; o padrão sem a variável é 2;
2. **o caminho até o contêiner**: as duas chaves estão entre as opcionais
   do runtime, e só entram quando preenchidas;
3. **os limites do `docker-stack.yml`**: a memória do `app` cabe quatro
   processos e a CPU passa de um núcleo — com um núcleo só, mais processos
   dividiriam o mesmo e não atenderiam mais ninguém.

    docker compose exec -T app python manage.py shell < checks/check_processos.py
"""
import re
import subprocess
from pathlib import Path

from ops.make_runtime import OPTIONAL_KEYS

falhas = []
RAIZ = Path('/app') if Path('/app/ops/entrypoint.sh').exists() else Path('.')


def conferir(nome, ok, detalhe=''):
    print(f'  [{"ok" if ok else "FALHA"}] {nome}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(nome)


print('=== 1. A conferência no entrypoint ===')
fonte = (RAIZ / 'ops/entrypoint.sh').read_text(encoding='utf-8')
conferir('o entrypoint não tem fim de linha do Windows', '\r' not in fonte)
funcao = fonte[fonte.index('numero_entre() {'):fonte.index('}\n', fonte.index('numero_entre() {')) + 2]
for valor, limite, aceita in [('4', '16', True), ('1', '16', True), ('16', '16', True), ('0', '16', False),
                              ('17', '16', False), ('', '16', False), ('quatro', '16', False),
                              ('-2', '16', False), ('4;rm', '16', False), ('6', '32', True), ('33', '32', False)]:
    r = subprocess.run(['sh', '-c', f'{funcao}\nnumero_entre "$1" {limite} TESTE && echo PASSOU', 'sh', valor],
                       capture_output=True, text=True)
    passou = 'PASSOU' in r.stdout
    conferir(f'{valor!r} (até {limite}) {"aceito" if aceita else "recusado"}', passou == aceita,
             r.stdout + r.stderr)
    if not aceita:
        conferir(f'  e a recusa diz o que fazer ({valor!r})', 'precisa ser um numero entre 1 e' in r.stderr)
conferir('sem APP_WORKERS, 2 processos', 'ND_APP_WORKERS="${APP_WORKERS:-2}"' in fonte)
conferir('sem WORKER_CONCURRENCY, 2 tarefas', 'ND_WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-2}"' in fonte)
conferir('o uvicorn usa o número conferido', '--workers "$ND_APP_WORKERS"' in fonte)
conferir('o celery usa o número conferido', '--concurrency="$ND_WORKER_CONCURRENCY"' in fonte)
conferir('nenhum número fixo sobrou', '--workers 2' not in fonte and '--concurrency=2' not in fonte)

print('=== 2. O caminho até o contêiner ===')
conferir('as duas chaves são opcionais do runtime', {'APP_WORKERS', 'WORKER_CONCURRENCY'} <= set(OPTIONAL_KEYS))

print('=== 3. Os limites do docker-stack.yml ===')
stack = (RAIZ / 'docker-stack.yml').read_text(encoding='utf-8')
app = stack[stack.index('\n  app:'):stack.index('\n  celery_worker:')]
worker = stack[stack.index('\n  celery_worker:'):stack.index('\n  celery_beat:')]


def limite(bloco):
    m = re.search(r"limits: \{cpus: '([\d.]+)', memory: (\d+)(M|G)\}", bloco)
    return float(m.group(1)), int(m.group(2)) * (1024 if m.group(3) == 'G' else 1)


cpu_app, mem_app = limite(app)
cpu_worker, mem_worker = limite(worker)
conferir('o app tem mais de um núcleo para os processos', cpu_app >= 2.0, cpu_app)
conferir('a memória do app cabe quatro processos (~150 MB cada, com folga)', mem_app >= 4 * 150 * 2, mem_app)
conferir('o worker tem dois núcleos e memória para seis tarefas', cpu_worker >= 2.0 and mem_worker >= 6 * 200, (cpu_worker, mem_worker))

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Processos e tarefas: tudo confere.')
