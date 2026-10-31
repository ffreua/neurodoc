#!/bin/sh
# Refaz as capturas do manual publico, todas de uma vez.
#
# O navegador roda **dentro do Docker**, na rede da pilha local, e nao na
# maquina de quem chama. Nao e preferencia: uma sequencia de vinte e duas
# capturas com Chrome no host, ao lado do navegador de quem esta
# trabalhando, matou o navegador tres vezes por falta de memoria. Aqui o
# processo e descartavel e a memoria e do contentor.
#
# A imagem oficial do Playwright ja traz os navegadores; o pacote Python
# nao vem, e por isso a instalacao na linha do `sh -c`. Versao fixada: um
# navegador diferente muda a renderizacao, e o manual inteiro sairia com
# outra aparencia sem ninguem ter pedido.
#
# Exige a pilha local de pe (`docker compose up -d`) e o banco de
# demonstracao semeado (`manage.py seed_demo`) -- as capturas saem todas
# da Clinica Demo A, com pacientes sinteticos. Nenhum dado real entra no
# manual, que e publico.
set -eu
cd "$(dirname "$0")/.."
RAIZ=$(pwd)
IMAGEM=mcr.microsoft.com/playwright/python:v1.47.0-jammy

# O nome da rede vem do proprio contentor do `app`, e nao escrito a mao:
# `docker compose` prefixa a rede com o nome do projeto, que muda com o
# nome do diretorio.
REDE=$(docker compose ps -q app | xargs docker inspect \
    -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')

# O banco de demonstracao no estado que o manual descreve (TISS, agenda de
# exames, bloco SNCR ficticio, documento com entregas, chat) -- e os ids das
# telas de um objeto so, que o roteiro de captura recebe pela variavel.
IDS=$(docker compose exec -T app python manage.py shell < ops/preparar_ajuda.py 2>/dev/null \
    | sed -n 's/^IDS //p')
[ -n "$IDS" ] || { echo "preparar_ajuda.py nao terminou; nada foi capturado" >&2; exit 1; }

# No Git Bash do Windows, sem isto o "/ops" do volume vira um caminho do
# Windows e o contentor nao acha o roteiro. Inofensivo no Linux.
export MSYS_NO_PATHCONV=1

exec docker run --rm --network "$REDE" \
    -v "$RAIZ/ops:/ops:ro" \
    -v "$RAIZ/static/help:/saida" \
    -e NEURODOC_URL=http://app:8000 \
    -e NEURODOC_IDS="$IDS" \
    "$IMAGEM" \
    sh -c 'pip3 install -q playwright==1.47.0 >/dev/null 2>&1; python3 /ops/capturar_ajuda.py'
