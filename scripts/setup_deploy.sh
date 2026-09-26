#!/usr/bin/env bash
# =============================================================================
#  setup_deploy.sh — primeiro deploy do NeuroDoc, do zero, numa VPS limpa
# =============================================================================
#  Faz o que `docs/operations/primeiro-deploy.md` descreve em 16 seções, sem
#  você digitar comando nenhum. Roda uma vez como root; ele prepara o
#  servidor, cria o usuário de operação e continua sozinho como ele.
#
#  COMO RODAR (na VPS, logado como root):
#      bash setup_deploy.sh
#
#  ---------------------------------------------------------------------------
#  COMO TRAZER ESTE ARQUIVO PARA A VPS
#  ---------------------------------------------------------------------------
#  O repositorio e PRIVADO, entao `curl raw.githubusercontent.com/...` devolve
#  404 -- aquele one-liner nao serve aqui. Tres caminhos que funcionam:
#
#  1) Da sua maquina, por scp. E o mais simples, e nenhum token precisa ir
#     para a VPS antes do script rodar:
#
#       scp -i ~/.ssh/neurodoc scripts/setup_deploy.sh root@SEU-IP:/root/
#
#  2) Na VPS, pela API do GitHub com um token. A API de `contents` le
#     repositorio privado; o host `raw.` nao:
#
#       curl -fsSL \
#         -H "Authorization: Bearer SEU-TOKEN" \
#         -H "Accept: application/vnd.github.raw" \
#         https://api.github.com/repos/ffreua/neurodoc/contents/scripts/setup_deploy.sh \
#         -o setup_deploy.sh
#
#  3) Clonando o repositorio antes, por HTTPS com token:
#
#       git clone https://SEU-TOKEN@github.com/ffreua/neurodoc.git /srv/neurodoc
#       bash /srv/neurodoc/scripts/setup_deploy.sh
#
#     O script percebe o clone existente e pula a etapa de trazer o codigo.
#
#  Os caminhos 2 e 3 exigem que este arquivo ja esteja COMITADO E ENVIADO ao
#  GitHub -- ate la, so o 1 funciona.
#
#  ---------------------------------------------------------------------------
#  O QUE ESTE SCRIPT **NÃO** FAZ, DE PROPÓSITO
#  ---------------------------------------------------------------------------
#  Ele não constrói imagem, não dá `docker push` e não roda `docker stack
#  deploy`. Quem faz isso é `ops/deploy.py`, que já existe, tem trava de
#  execução, confere vinte e tantas pré-condições no `preflight`, fixa as
#  imagens por digest, espera cada serviço ficar saudável e volta atrás
#  sozinho se não ficar.
#
#  Um script de setup que refizesse esses passos viraria uma **segunda**
#  verdade sobre como se publica o NeuroDoc — e as duas divergiriam no
#  primeiro ajuste, com a diferença aparecendo em produção. Este script é o
#  que falta antes: deixa a máquina exatamente no estado que
#  `ops.deploy --check` exige, e então chama o deploy de verdade.
#
#  ---------------------------------------------------------------------------
#  RETOMADA
#  ---------------------------------------------------------------------------
#  Pode rodar quantas vezes quiser. Cada passo pergunta ao **mundo real**
#  (o segredo existe? a rede existe? o rótulo está no nó?) antes de agir, e
#  pula o que já está feito. O arquivo de estado guarda só as suas
#  respostas, para não perguntar duas vezes — nunca é ele que decide se um
#  passo pode ser pulado, porque um arquivo de estado mente quando alguém
#  desfaz algo à mão.
#
#  Requisitos: Ubuntu 24.04 LTS, acesso root, domínio neurodoc.app.br na
#  Cloudflare, conta no GitHub com acesso ao repositório e ao GHCR.
# =============================================================================

set -Eeuo pipefail

# Rodando por 'curl | bash' a entrada padrão é o cano, e nenhuma pergunta
# funcionaria. Reapontamos para o terminal de verdade.
#
# `-e /dev/tty` não basta como teste: dentro de um contêiner, ou num
# `ssh host 'bash script'` sem `-t`, o nó do dispositivo **existe** e abri-lo
# falha por não haver terminal de controle. E uma redireção que falha num
# `exec` derruba o shell na hora — o script morria na linha 45 com
# "No such device or address", antes de imprimir qualquer coisa.
#
# Abrir de mentira primeiro, dentro de um `{ ... }`, é o que distingue os
# dois casos: ali a falha é só da lista de comandos, e não do shell.
if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then
  exec </dev/tty
fi

# ─────────────────────────────────────────────────────────────── aparência ──
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD="$(tput bold)";   RESET="$(tput sgr0)"
  RED="$(tput setaf 1)"; GREEN="$(tput setaf 2)"; YELLOW="$(tput setaf 3)"
  BLUE="$(tput setaf 4)"; CYAN="$(tput setaf 6)"; GREY="$(tput setaf 8)"
else
  BOLD=""; RESET=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""; GREY=""
fi

LOG_FILE="${HOME:-/root}/neurodoc-setup.log"
ESTADO="${HOME:-/root}/.neurodoc-setup.state"
PASSO=0
FASE=""

_log() { printf '%s %s\n' "[$(date '+%F %H:%M:%S')]" "$1" >>"$LOG_FILE" 2>/dev/null || true; }

faixa() {
  echo ""
  echo "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════╗${RESET}"
  printf "${BOLD}${CYAN}║${RESET} %-60s ${BOLD}${CYAN}║${RESET}\n" "$1"
  echo "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════╝${RESET}"
}
passo() {
  PASSO=$((PASSO + 1))
  echo ""
  echo "${BOLD}${BLUE}▶ ${FASE} — PASSO ${PASSO}:${RESET} ${BOLD}$1${RESET}"
  echo "${GREY}──────────────────────────────────────────────────────────────${RESET}"
  _log "PASSO ${PASSO} (${FASE}): $1"
}
info()    { echo "  ${BLUE}ℹ${RESET}  $1";  _log "INFO  $1"; }
ok()      { echo "  ${GREEN}✔${RESET}  $1"; _log "OK    $1"; }
aviso()   { echo "  ${YELLOW}⚠${RESET}  $1"; _log "AVISO $1"; }
pulado()  { echo "  ${GREEN}✓${RESET}  ${GREY}$1 — já feito, pulando${RESET}"; _log "PULA  $1"; }
fazendo() { echo "  ${CYAN}⏳${RESET} $1..."; _log "FAZ   $1"; }

caixa_acao() {
  echo ""
  echo "${BOLD}${YELLOW}  ┌──────────────────────── AÇÃO NECESSÁRIA ───────────────────────┐${RESET}"
  while [[ $# -gt 0 ]]; do echo "${BOLD}${YELLOW}  │${RESET} $1"; shift; done
  echo "${BOLD}${YELLOW}  └────────────────────────────────────────────────────────────────┘${RESET}"
  echo ""
}
enter() { echo ""; read -r -p "  ${BOLD}${GREEN}➜ Feito? Pressione ENTER para continuar...${RESET} " _ || true; }

# ──────────────────────────────────────────────────────────────── erros ────
ao_falhar() {
  local codigo=$1 linha=$2 comando=$3
  echo ""
  echo "${BOLD}${RED}╔══════════════════════════════════════════════════════════════╗${RESET}"
  echo "${BOLD}${RED}║  ❌ O script parou                                            ║${RESET}"
  echo "${BOLD}${RED}╚══════════════════════════════════════════════════════════════╝${RESET}"
  echo "  ${RED}Fase........:${RESET} ${FASE}"
  echo "  ${RED}Passo.......:${RESET} ${PASSO}"
  echo "  ${RED}Linha.......:${RESET} ${linha}"
  echo "  ${RED}Comando.....:${RESET} ${comando}"
  echo "  ${RED}Código saída:${RESET} ${codigo}"
  echo ""
  echo "  ${YELLOW}O que fazer:${RESET}"
  echo "    1. Leia a mensagem de erro logo acima desta caixa."
  echo "    2. Log completo: ${BOLD}${LOG_FILE}${RESET}"
  echo "    3. Corrija e rode o script de novo — ele retoma de onde parou."
  echo ""
  _log "ERRO saida=$codigo linha=$linha cmd=<$comando> fase=$FASE passo=$PASSO"
  if [[ -e /dev/tty ]]; then read -r -p "  ENTER para fechar..." _ </dev/tty 2>/dev/null || true; fi
  exit "$codigo"
}
trap 'ao_falhar $? ${LINENO} "$BASH_COMMAND"' ERR

# ──────────────────────────────────────────────────────────── utilidades ───
tem() { command -v "$1" >/dev/null 2>&1; }

tentar() {  # repete até 3 vezes com espera crescente — rede de VPS oscila
  local max=3 vez=1 espera=4
  until "$@"; do
    if (( vez >= max )); then aviso "Falhou após ${max} tentativas: $*"; return 1; fi
    aviso "Tentativa ${vez}/${max} falhou. Nova em ${espera}s..."
    sleep "$espera"; vez=$((vez + 1)); espera=$((espera * 2))
  done
}

# Entrada fechada e o fim da linha, nao uma resposta vazia.
#
# Com `|| true` e um `while`, um script rodado com a entrada redirecionada
# (ou por engano sem terminal) ficava girando para sempre, imprimindo o
# aviso milhares de vezes. Perguntar exige quem responda; se nao ha, parar
# e dizer por que e o unico desfecho honesto.
sem_resposta() {
  echo ""
  echo "  ${RED}A entrada foi fechada e ainda ha perguntas a responder.${RESET}"
  echo "  Rode o script num terminal interativo:  ${BOLD}bash setup_deploy.sh${RESET}"
  exit 1
}

sim_nao() {
  local pergunta="$1" resposta
  while true; do
    read -r -p "  ${YELLOW}❓ ${pergunta} [S/N]:${RESET} " resposta || sem_resposta
    case "$resposta" in
      [Ss]|[Ss][Ii][Mm]) return 0 ;;
      [Nn]|[Nn][Aa][Oo]) return 1 ;;
      *) aviso "Responda S (sim) ou N (não)." ;;
    esac
  done
}

perguntar() {  # perguntar "texto" "padrão" -> ecoa a resposta
  local texto="$1" padrao="${2:-}" resposta
  if [[ -n "$padrao" ]]; then
    # Com padrao, entrada fechada vira o padrao: e o mesmo que o usuario
    # teria feito apertando ENTER.
    read -r -p "  ${CYAN}❯ ${texto}${RESET} [${padrao}]: " resposta || resposta=""
    echo "${resposta:-$padrao}"
  else
    read -r -p "  ${CYAN}❯ ${texto}${RESET}: " resposta || sem_resposta
    echo "$resposta"
  fi
}

perguntar_segredo() {
  local texto="$1" resposta
  read -r -s -p "  ${CYAN}❯ ${texto}${RESET}: " resposta || sem_resposta
  echo "" >&2
  echo "$resposta"
}

# Estado: guarda RESPOSTAS, não progresso. Ver o cabeçalho do arquivo.
lembrar() {
  local chave="$1" valor="$2" tmp
  tmp="$(mktemp)"
  [[ -f "$ESTADO" ]] && { grep -v "^${chave}=" "$ESTADO" >"$tmp" 2>/dev/null || true; }
  printf '%s=%s\n' "$chave" "$valor" >>"$tmp"
  mv "$tmp" "$ESTADO"; chmod 600 "$ESTADO"
}
lembrado() {
  local chave="$1"
  [[ -f "$ESTADO" ]] || return 1
  local linha; linha="$(grep -m1 "^${chave}=" "$ESTADO" 2>/dev/null)" || return 1
  printf '%s' "${linha#*=}"
}

ip_publico() {
  local ip=""
  ip="$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  [[ -n "$ip" ]] || ip="$(curl -4 -fsS --max-time 5 https://ifconfig.me 2>/dev/null || true)"
  ip="$(printf '%s' "$ip" | tr -d '[:space:]')"
  [[ -n "$ip" ]] || ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | head -n1)" || true
  printf '%s' "$ip"
}

eh_manager() { [[ "$(docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null)" == "true" ]]; }

# Constantes desta instalação. Não são configuráveis porque `ops/deploy.py`
# as exige literalmente no preflight — deixar o operador escolher outro nome
# de rede só adiantaria a falha para depois, com uma mensagem pior.
STACK='neurodoc_v1'
REDE_PUBLICA='traefik_public'
REDE_INTERNA='neurodoc_v1_internal'
REDE_EGRESSO='neurodoc_v1_egress'
ROTULO_NO='neurodoc_data'
TMPFS_ASSINATURA='/run/neurodoc-signing'
# UID do usuário da aplicação dentro da imagem (Dockerfile) — o mesmo de
# `ops/deploy.py::APP_UID`. Tudo que o contêiner escreve precisa ser dele.
UID_APP='10001'
DESTINO_PADRAO='/srv/neurodoc'
DOMINIO='neurodoc.app.br'
ARQ_ESTADO_NOME='.neurodoc-setup.state'

SCRIPT_URL="${NEURODOC_SETUP_URL:-}"

# =============================================================================
#  FASE 1 — SERVIDOR (root)
#  Seções 3, 4 e 6 de docs/operations/primeiro-deploy.md.
# =============================================================================
fase_servidor() {
  FASE="FASE 1: SERVIDOR (root)"; PASSO=0

  passo "Conferindo o sistema"
  [[ -r /etc/os-release ]] || { echo "Sem /etc/os-release — use Ubuntu 24.04 LTS."; exit 1; }
  # shellcheck disable=SC1091
  . /etc/os-release
  tem apt-get || { echo "Este script é para Ubuntu/Debian. Detectado: ${PRETTY_NAME:-?}"; exit 1; }
  info "Servidor: ${BOLD}${PRETTY_NAME:-Linux}${RESET}"
  case "${VERSION_ID:-}" in
    24.04) ok "Ubuntu 24.04 LTS — a versão documentada" ;;
    *) aviso "A documentação assume Ubuntu 24.04 LTS; aqui é ${VERSION_ID:-?}. Deve funcionar, mas não foi essa a testada." ;;
  esac
  export DEBIAN_FRONTEND=noninteractive

  passo "Dados do servidor"
  local usuario fuso swap_gb
  usuario="$(lembrado USUARIO || true)"
  [[ -n "$usuario" ]] || usuario="$(perguntar "Usuário de operação a criar (dono do deploy)" "neurodocops")"
  lembrar USUARIO "$usuario"
  fuso="$(lembrado FUSO || true)"
  [[ -n "$fuso" ]] || fuso="$(perguntar "Fuso horário" "America/Sao_Paulo")"
  lembrar FUSO "$fuso"
  swap_gb="$(lembrado SWAP_GB || true)"
  [[ -n "$swap_gb" ]] || swap_gb="$(perguntar "Swap em GB (0 = não criar)" "4")"
  lembrar SWAP_GB "$swap_gb"

  passo "Atualizando o sistema"
  fazendo "apt update"
  tentar apt-get update -y >>"$LOG_FILE" 2>&1
  fazendo "apt upgrade (pode demorar)"
  tentar apt-get upgrade -y >>"$LOG_FILE" 2>&1
  ok "Sistema atualizado"

  passo "Instalando utilitários"
  # `age` entra aqui porque a cópia de segurança **depende** dele:
  # `ops/backup.py` chama `subprocess.run(['age', '-r', destinatário])` para
  # cifrar o dump e os volumes. Sem o binário, o timer noturno estoura com
  # `FileNotFoundError` na primeira madrugada, e o alerta que faltaria seria
  # justamente o de que não há backup. Estava fora da lista, e uma VPS
  # preparada por este roteiro subia sem nenhuma chance de backup cifrado.
  fazendo "curl git htop iotop net-tools unzip jq ca-certificates age"
  tentar apt-get install -y curl git htop iotop net-tools unzip jq ca-certificates age >>"$LOG_FILE" 2>&1
  if tem age; then
    ok "Utilitários instalados (age presente)"
  else
    # Debian 11 e derivados antigos não têm `age` nos repositórios. Parar
    # aqui é melhor que descobrir na primeira madrugada: o passo seguinte
    # configura o backup, e configurá-lo sem o cifrador é escrever um timer
    # que nunca vai funcionar.
    aviso "O pacote 'age' não está nos repositórios desta distribuição."
    echo "  Instale-o antes de seguir — https://github.com/FiloSottile/age/releases"
    echo "  Sem ele, \`ops/backup.py\` não cifra nada e a cópia noturna falha."
    exit 1
  fi

  passo "Fuso horário (${fuso})"
  if timedatectl show -p Timezone --value 2>/dev/null | grep -qx "$fuso"; then
    pulado "Fuso já é ${fuso}"
  elif timedatectl set-timezone "$fuso" >>"$LOG_FILE" 2>&1; then
    ok "Fuso ajustado para ${fuso}"
  else
    # Antes o `ok` vinha depois do `aviso`, incondicional: a tela dizia que
    # não conseguiu e, na linha seguinte, que tinha conseguido. Saída que se
    # contradiz é pior que saída nenhuma — ninguém mais acredita nas outras.
    aviso "Não consegui ajustar o fuso (sem systemd?). O horário do servidor fica como está."
  fi

  passo "fail2ban (bloqueio de força bruta no SSH)"
  tentar apt-get install -y fail2ban >>"$LOG_FILE" 2>&1
  if [[ -f /etc/fail2ban/jail.local ]]; then
    pulado "jail.local"
  else
    fazendo "Escrevendo /etc/fail2ban/jail.local"
    tee /etc/fail2ban/jail.local >/dev/null <<'CFG'
[sshd]
enabled  = true
port     = 22
maxretry = 3
bantime  = 3600
findtime = 600
CFG
    ok "jail.local criado (bane 1h após 3 tentativas)"
  fi
  systemctl enable fail2ban >>"$LOG_FILE" 2>&1 || true
  if systemctl restart fail2ban >>"$LOG_FILE" 2>&1; then
    ok "fail2ban ativo"
  else
    aviso "fail2ban não subiu. Confira com 'systemctl status fail2ban' — o SSH fica sem o bloqueio de força bruta até isso ser resolvido."
  fi

  passo "Swap (${swap_gb}G)"
  if [[ "$swap_gb" == "0" ]]; then
    info "Pulado a pedido."
  elif swapon --show 2>/dev/null | grep -q '/swapfile'; then
    pulado "Swapfile ativo"
  else
    fazendo "Criando /swapfile de ${swap_gb}G"
    fallocate -l "${swap_gb}G" /swapfile >>"$LOG_FILE" 2>&1 \
      || dd if=/dev/zero of=/swapfile bs=1M count=$((swap_gb * 1024)) >>"$LOG_FILE" 2>&1
    chmod 600 /swapfile
    mkswap /swapfile >>"$LOG_FILE" 2>&1
    swapon /swapfile >>"$LOG_FILE" 2>&1
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
    ok "Swap ativo e persistente"
  fi

  passo "Firewall (UFW: 22, 80, 443)"
  # SSH liberado ANTES de ativar: ativar primeiro derrubaria esta sessão.
  ufw default deny incoming  >>"$LOG_FILE" 2>&1 || true
  ufw default allow outgoing >>"$LOG_FILE" 2>&1 || true
  ufw allow 22/tcp  comment 'SSH'   >>"$LOG_FILE" 2>&1 || true
  ufw allow 80/tcp  comment 'HTTP'  >>"$LOG_FILE" 2>&1 || true
  ufw allow 443/tcp comment 'HTTPS' >>"$LOG_FILE" 2>&1 || true
  if ufw status 2>/dev/null | grep -q 'Status: active'; then
    pulado "UFW ativo (regras reconfirmadas)"
  else
    fazendo "Ativando o UFW"
    ufw --force enable >>"$LOG_FILE" 2>&1
    ok "Firewall ativo"
  fi

  passo "Ajustes de produção (sysctl)"
  if grep -q 'NeuroDoc production tuning' /etc/sysctl.conf 2>/dev/null; then
    pulado "sysctl"
  else
    tee -a /etc/sysctl.conf >/dev/null <<'CFG'

# === NeuroDoc production tuning ===
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
vm.swappiness = 10
vm.overcommit_memory = 1
CFG
    sysctl -p >>"$LOG_FILE" 2>&1 || aviso "sysctl -p reclamou; veja o log."
    ok "Parâmetros aplicados"
  fi

  passo "Docker Engine"
  if tem docker; then
    pulado "Docker $(docker --version | awk '{print $3}' | tr -d ,)"
  else
    fazendo "Removendo pacotes antigos, se houver"
    apt-get remove -y docker docker-engine docker.io containerd runc >>"$LOG_FILE" 2>&1 || true
    fazendo "Instalando pelo script oficial (get.docker.com)"
    tentar bash -c "curl -fsSL https://get.docker.com | sh" >>"$LOG_FILE" 2>&1
    systemctl enable docker >>"$LOG_FILE" 2>&1 || true
    systemctl start docker  >>"$LOG_FILE" 2>&1 || true
    ok "Docker instalado"
  fi

  passo "Docker para produção (daemon.json)"
  if [[ -f /etc/docker/daemon.json ]] && grep -q 'overlay2' /etc/docker/daemon.json 2>/dev/null; then
    pulado "daemon.json"
  else
    mkdir -p /etc/docker
    # `ipv6: false` e o log rotacionado são o que evita os dois problemas
    # que aparecem tarde: rota IPv6 quebrada no Swarm e disco cheio de log.
    tee /etc/docker/daemon.json >/dev/null <<'CFG'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "storage-driver": "overlay2",
  "default-ulimits": {
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 }
  },
  "metrics-addr": "127.0.0.1:9323",
  "ipv6": false
}
CFG
    systemctl restart docker >>"$LOG_FILE" 2>&1
    ok "Docker reconfigurado"
  fi

  passo "Docker Swarm e o rótulo do nó"
  if eh_manager; then
    pulado "Swarm ativo, este nó é manager"
  else
    local ip
    ip="$(ip_publico)"
    ip="$(perguntar "IP público desta VPS (advertise-addr do Swarm)" "${ip:-127.0.0.1}")"
    lembrar VPS_IP "$ip"
    fazendo "docker swarm init --advertise-addr ${ip}"
    docker swarm init --advertise-addr "$ip" >>"$LOG_FILE" 2>&1
    ok "Swarm inicializado"
  fi
  # `neurodoc_data=true` é o rótulo que o `docker-stack.yml` usa para fixar
  # os volumes de dados num nó. Com um nó só ele parece decorativo — e é
  # justamente por isso que é esquecido, e o preflight recusa o deploy.
  local no_id
  no_id="$(docker node ls -q | head -n1)"
  if docker node inspect self --format '{{ index .Spec.Labels "'"$ROTULO_NO"'" }}' 2>/dev/null | grep -qx 'true'; then
    pulado "Rótulo ${ROTULO_NO}=true"
  else
    docker node update --label-add "${ROTULO_NO}=true" "$no_id" >>"$LOG_FILE" 2>&1
    ok "Rótulo ${ROTULO_NO}=true aplicado"
  fi

  passo "Pasta das chaves de assinatura, em memória (tmpfs)"
  # As chaves de sessão de assinatura digital não podem tocar o disco. O
  # preflight confere o tipo do sistema de arquivos e recusa se for disco.
  #
  # `uid`/`gid` do usuário da aplicação, e não do root: esta pasta é
  # montada aqui pelo root e entra no contêiner por bind
  # (`docker-stack.yml`), onde quem escreve é o processo do app, que roda
  # como ${UID_APP} (Dockerfile). Montada com o dono padrão ela fica 0700
  # de root, e a falha não aparece agora — aparece em produção, na
  # primeira receita que alguém tenta assinar.
  mkdir -p "$TMPFS_ASSINATURA"
  if [[ "$(findmnt -n -o FSTYPE -T "$TMPFS_ASSINATURA" 2>/dev/null || true)" == "tmpfs" ]]; then
    pulado "tmpfs em ${TMPFS_ASSINATURA}"
  else
    fazendo "Montando tmpfs em ${TMPFS_ASSINATURA}"
    mount -t tmpfs -o "size=16m,mode=0700,uid=${UID_APP},gid=${UID_APP}" tmpfs "$TMPFS_ASSINATURA"
    ok "tmpfs montado"
  fi
  # Também para o tmpfs que já estava montado de uma execução anterior,
  # feita antes desta correção: remontar derrubaria as chaves de sessão em
  # uso, e o `chown` resolve sem isso.
  if [[ "$(stat -c '%u' "$TMPFS_ASSINATURA")" != "$UID_APP" ]]; then
    fazendo "Ajustando o dono de ${TMPFS_ASSINATURA} para ${UID_APP}"
    chown "${UID_APP}:${UID_APP}" "$TMPFS_ASSINATURA"
    ok "Dono ajustado"
  else
    pulado "Dono de ${TMPFS_ASSINATURA} (${UID_APP})"
  fi
  if grep -q "$TMPFS_ASSINATURA" /etc/fstab 2>/dev/null; then
    pulado "Linha no /etc/fstab"
  else
    echo "tmpfs ${TMPFS_ASSINATURA} tmpfs size=16m,mode=0700,uid=${UID_APP},gid=${UID_APP} 0 0" >>/etc/fstab
    ok "Persistido no /etc/fstab (sobrevive a reinício)"
  fi

  passo "Usuário de operação '${usuario}'"
  if id "$usuario" >/dev/null 2>&1; then
    pulado "Usuário ${usuario}"
  else
    adduser --disabled-password --gecos "" "$usuario" >>"$LOG_FILE" 2>&1
    ok "Usuário ${usuario} criado"
  fi
  usermod -aG sudo,docker "$usuario"
  echo "${usuario} ALL=(ALL) NOPASSWD:ALL" >"/etc/sudoers.d/90-${usuario}"
  chmod 440 "/etc/sudoers.d/90-${usuario}"
  ok "${usuario} nos grupos sudo e docker"
  if [[ -f /root/.ssh/authorized_keys ]]; then
    mkdir -p "/home/${usuario}/.ssh"
    cp /root/.ssh/authorized_keys "/home/${usuario}/.ssh/"
    chown -R "${usuario}:${usuario}" "/home/${usuario}/.ssh"
    chmod 700 "/home/${usuario}/.ssh"; chmod 600 "/home/${usuario}/.ssh/authorized_keys"
    ok "Chave SSH copiada — você entra como ${usuario} com a mesma chave"
  else
    aviso "root não tem authorized_keys; garanta acesso SSH a ${usuario} antes de fechar esta sessão."
  fi

  passo "Preparando a pasta do projeto em ${DESTINO_PADRAO}"
  mkdir -p "$DESTINO_PADRAO"
  chown "${usuario}:${usuario}" "$DESTINO_PADRAO"
  ok "${DESTINO_PADRAO} pronta e pertencente a ${usuario}"

  passo "Passando o bastão para '${usuario}'"
  local eu destino estado_novo
  eu="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "")"
  destino="/home/${usuario}/setup_deploy.sh"
  if [[ -n "$eu" && -f "$eu" ]]; then
    cp "$eu" "$destino"
  elif [[ -n "$SCRIPT_URL" ]]; then
    fazendo "Baixando o script de ${SCRIPT_URL}"
    curl -fsSL "$SCRIPT_URL" -o "$destino"
  else
    caixa_acao \
      "A FASE 1 terminou. Para a FASE 2 (deploy), rode:" \
      "  su - ${usuario}" \
      "  cd ${DESTINO_PADRAO} && bash scripts/setup_deploy.sh" \
      "(ou exporte NEURODOC_SETUP_URL=... para o handoff automático)"
    exit 0
  fi
  chown "${usuario}:${usuario}" "$destino"; chmod 750 "$destino"
  estado_novo="/home/${usuario}/${ARQ_ESTADO_NOME}"
  # Funde o estado do root com o que o operador já tenha, mantendo a
  # PRIMEIRA ocorrência de cada chave — o do operador vem primeiro, então é
  # ele que vence. Antes isto era um `cat >>`, e cada nova execução
  # empilhava as mesmas chaves de novo; o arquivo crescia a cada tentativa
  # e `lembrado` passava a devolver um valor antigo dependendo da ordem.
  touch "$estado_novo"
  awk -F= '!vista[$1]++' "$estado_novo" "$ESTADO" >"${estado_novo}.novo" 2>/dev/null || true
  mv "${estado_novo}.novo" "$estado_novo"
  chown "${usuario}:${usuario}" "$estado_novo"; chmod 600 "$estado_novo"
  ok "Script e estado copiados"
  info "Continuando automaticamente como '${usuario}'..."
  echo ""
  exec sudo -iu "$usuario" bash "$destino" --como-operador
}

# =============================================================================
#  FASE 2 — DEPLOY (usuário de operação)
#  Seções 5 a 15 de docs/operations/primeiro-deploy.md.
# =============================================================================

# Lê os nomes dos segredos do próprio docker-stack.yml, em vez de manter uma
# lista aqui. Um segredo novo no stack passa a ser exigido pelo preflight; se
# esta lista fosse escrita à mão, o script criaria quatorze e o deploy
# recusaria pelo décimo quinto, sem ninguém entender de onde saiu.
segredos_do_stack() {
  awk '
    /^secrets:/ { dentro = 1; next }
    dentro && /^[^[:space:]]/ { dentro = 0 }
    dentro && /^[[:space:]]+[A-Za-z0-9_]+:/ {
      gsub(/[[:space:]]|:.*$/, "", $0); if ($0 != "") print $0
    }
  ' docker-stack.yml
}

# Classificação dos segredos. Quatro famílias, e a diferença entre a
# primeira e a segunda é a armadilha documentada em `docs/operations`:
# as duas chaves-mestras alimentam o Fernet e exigem 32 bytes em base64
# **url-safe** (44 caracteres). O `-base64 48` das outras seis produz 64
# caracteres, o Fernet recusa, e a recusa não aparece no deploy — aparece
# semanas depois, quando alguém salva uma senha de SMTP de clínica.
SEGREDOS_ALEATORIOS="NEURODOC_DJANGO_SECRET_KEY NEURODOC_DB_ADMIN_PASSWORD NEURODOC_DB_OWNER_PASSWORD NEURODOC_DB_APP_PASSWORD NEURODOC_RABBITMQ_PASSWORD NEURODOC_REDIS_PASSWORD"
SEGREDOS_FERNET="NEURODOC_PFX_MASTER_KEY NEURODOC_SECRETS_MASTER_KEY"
SEGREDOS_FORNECIDOS="CLOUDFLARE_DNS_API_TOKEN NEURODOC_SMTP_PASSWORD NEURODOC_SMSDEV_API_KEY NEURODOC_NVIDIA_API_KEY"
SEGREDOS_DESLIGADOS="NEURODOC_OPENROUTER_API_KEY NEURODOC_OPENAI_API_KEY NEURODOC_ANTHROPIC_API_KEY"

segredo_existe() { docker secret inspect "$1" >/dev/null 2>&1; }

criar_segredo() {  # criar_segredo NOME VALOR
  printf '%s' "$2" | docker secret create "$1" - >>"$LOG_FILE" 2>&1
}

# Define uma chave no .env, recusando chave que não exista no .env.example.
# `ops/deploy.py::configuration()` rejeita chave desconhecida — escrever uma
# aqui faria o deploy parar com "Unknown configuration keys" e ninguém saberia
# que foi o script de setup que a inventou.
set_env() {
  local chave="$1" valor="$2" tmp
  if ! grep -q "^${chave}=" .env.example; then
    echo "Chave '${chave}' não existe em .env.example — o deploy recusaria." >&2
    return 1
  fi
  tmp="$(mktemp)"
  grep -v "^${chave}=" .env >"$tmp" 2>/dev/null || true
  printf '%s=%s\n' "$chave" "$valor" >>"$tmp"
  mv "$tmp" .env; chmod 600 .env
}
get_env() { grep -m1 "^$1=" .env 2>/dev/null | cut -d= -f2- || true; }

fase_deploy() {
  FASE="FASE 2: DEPLOY ($(whoami))"; PASSO=0
  faixa "🚢  FASE 2 — DEPLOY (usuário: $(whoami))"

  passo "Conferindo Docker e Swarm"
  tem docker || { echo "Docker ausente. Rode a FASE 1 como root."; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Sem permissão no Docker. Saia e entre de novo."; exit 1; }
  eh_manager || { echo "Este nó não é manager do Swarm. Rode a FASE 1 como root."; exit 1; }
  ok "Docker e Swarm prontos (nó manager)"

  passo "Onde fica o projeto"
  local destino
  destino="$(lembrado DESTINO || true)"
  [[ -n "$destino" ]] || destino="$(perguntar "Pasta do projeto" "$DESTINO_PADRAO")"
  lembrar DESTINO "$destino"
  # Recusa caminho perigoso antes de qualquer `chown -R`. A pergunta acima
  # aceita o que for digitado, e um `/` ali reescreveria o dono do sistema
  # inteiro — o tipo de acidente que não tem desfazer.
  case "$destino" in
    /|/usr|/etc|/var|/home|/root|/boot|/bin|/sbin|/lib*|"")
      echo "Pasta inválida para o projeto: '${destino}'. Use algo como ${DESTINO_PADRAO}."
      exit 1 ;;
  esac
  sudo mkdir -p "$destino"
  # `-R`, e não só o diretório: se alguém já clonou ali como root — que é o
  # caminho natural de quem trouxe o repositório antes de rodar este script
  # —, os arquivos ficam de root e o operador não consegue escrever o
  # `.env`, o registro de homologação nem criar o `.venv-ops`. O Git ainda
  # recusaria o diretório por "dubious ownership", com uma mensagem que não
  # diz que o problema é dono de arquivo.
  sudo chown -R "$(id -un):$(id -gn)" "$destino"
  info "Projeto em ${BOLD}${destino}${RESET}"

  # ─────────────────────────────────────────────── chave SSH do GitHub ────
  passo "Chave SSH deste servidor para o GitHub"
  local chave="${HOME}/.ssh/github"
  mkdir -p "${HOME}/.ssh"; chmod 700 "${HOME}/.ssh"
  if [[ -f "$chave" ]]; then
    pulado "Chave ${chave}"
  else
    ssh-keygen -t ed25519 -C "neurodoc-vps" -f "$chave" -N "" >>"$LOG_FILE" 2>&1
    ok "Chave gerada"
  fi
  if ! grep -q "Host github.com" "${HOME}/.ssh/config" 2>/dev/null; then
    cat >>"${HOME}/.ssh/config" <<SSHCFG
Host github.com
  HostName github.com
  User git
  IdentityFile ${chave}
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
SSHCFG
    chmod 600 "${HOME}/.ssh/config"
    ok "~/.ssh/config configurado"
  else
    pulado "~/.ssh/config"
  fi
  ssh-keyscan github.com >>"${HOME}/.ssh/known_hosts" 2>/dev/null || true

  if [[ ! -d "${destino}/.git" ]]; then
    echo ""
    echo "  ${BOLD}Chave PÚBLICA deste servidor (copie a linha inteira):${RESET}"
    echo "${GREY}──────────────────────────────────────────────────────────────${RESET}"
    echo "${BOLD}${GREEN}$(cat "${chave}.pub")${RESET}"
    echo "${GREY}──────────────────────────────────────────────────────────────${RESET}"
    caixa_acao \
      "1. Abra: https://github.com/settings/ssh/new" \
      "2. Cole a chave acima e salve." \
      "3. Volte aqui."
    enter
  fi

  # ─────────────────────────────────────────────────────────────── clone ──
  passo "Trazendo o código"
  if [[ -d "${destino}/.git" ]]; then
    pulado "Repositório já clonado"
  else
    local repo
    repo="$(lembrado REPO || true)"
    [[ -n "$repo" ]] || repo="$(perguntar "Repositório (SSH)" "git@github.com:ffreua/neurodoc.git")"
    lembrar REPO "$repo"
    fazendo "git clone"
    if ! tentar git clone "$repo" "$destino" >>"$LOG_FILE" 2>&1; then
      aviso "Clone por SSH falhou. Tentando HTTPS."
      local repo_https
      repo_https="$(perguntar "Repositório (HTTPS)" "https://github.com/ffreua/neurodoc.git")"
      tentar git clone "$repo_https" "$destino" >>"$LOG_FILE" 2>&1
    fi
    ok "Código em ${destino}"
  fi
  cd "$destino"
  [[ -f docker-stack.yml ]] || { echo "docker-stack.yml não encontrado — o clone trouxe o repositório errado."; exit 1; }
  [[ -f .env.example ]] || { echo ".env.example não encontrado."; exit 1; }

  # ──────────────────────────────────────────────────────────── venv ops ──
  passo "Ambiente Python do deploy (.venv-ops)"
  # Existe só para `ops/deploy.py` poder ler YAML. A aplicação roda dentro
  # do contêiner, com as dependências dela.
  if [[ -x .venv-ops/bin/python ]] && .venv-ops/bin/python -c 'import yaml' 2>/dev/null; then
    pulado ".venv-ops com pyyaml"
  else
    fazendo "Instalando python3-venv, se faltar"
    sudo apt-get install -y python3-venv >>"$LOG_FILE" 2>&1 || true
    fazendo "Criando .venv-ops e instalando pyyaml"
    python3 -m venv .venv-ops >>"$LOG_FILE" 2>&1
    tentar .venv-ops/bin/pip install --quiet pyyaml >>"$LOG_FILE" 2>&1
    ok ".venv-ops pronto"
  fi

  # ─────────────────────────────────────────────────────────────── redes ──
  passo "As três redes overlay"
  # A separação é o coração da segurança: só o worker alcança a internet.
  # A rede do meio TEM de ser --internal; o preflight confere e recusa.
  criar_rede() {
    local nome="$1" interna="$2"
    if docker network ls --format '{{.Name}}' | grep -qx "$nome"; then
      pulado "Rede ${nome}"
      return
    fi
    if [[ "$interna" == "sim" ]]; then
      docker network create --driver overlay --internal "$nome" >>"$LOG_FILE" 2>&1
    else
      docker network create --driver overlay --attachable "$nome" >>"$LOG_FILE" 2>&1
    fi
    ok "Rede ${nome} criada"
  }
  criar_rede "$REDE_PUBLICA" nao
  criar_rede "$REDE_INTERNA" sim
  criar_rede "$REDE_EGRESSO" nao
  local n esperado real
  for n in "$REDE_PUBLICA:false" "$REDE_INTERNA:true" "$REDE_EGRESSO:false"; do
    esperado="${n##*:}"; n="${n%%:*}"
    real="$(docker network inspect "$n" --format '{{.Internal}}' 2>/dev/null || echo '?')"
    if [[ "$real" != "$esperado" ]]; then
      echo "Rede ${n}: isolamento interno=${real}, esperado ${esperado}."
      echo "Apague-a (docker network rm ${n}) e rode o script de novo."
      exit 1
    fi
  done
  ok "Isolamento conferido: pública=false, interna=true, egresso=false"

  # ──────────────────────────────────────────────────────────── segredos ──
  passo "Os segredos do Docker"
  local todos faltando
  todos="$(segredos_do_stack)"
  [[ -n "$todos" ]] || { echo "Não consegui ler a lista de segredos do docker-stack.yml."; exit 1; }
  # Qualquer segredo do stack que este script não saiba classificar é erro:
  # criar um valor aleatório para algo que devia ser uma chave de API seria
  # pior do que parar aqui.
  local conhecidos="$SEGREDOS_ALEATORIOS $SEGREDOS_FERNET $SEGREDOS_FORNECIDOS $SEGREDOS_DESLIGADOS"
  for n in $todos; do
    if ! printf '%s\n' $conhecidos | grep -qx "$n"; then
      echo "O docker-stack.yml pede o segredo '${n}', que este script não conhece."
      echo "Classifique-o em scripts/setup_deploy.sh antes de seguir."
      exit 1
    fi
  done
  info "$(printf '%s\n' $todos | wc -l | tr -d ' ') segredos declarados no stack"

  local gerados=""
  for n in $SEGREDOS_ALEATORIOS; do
    if segredo_existe "$n"; then pulado "Segredo ${n}"; continue; fi
    # `tr -d '\r\n'`, e não só `\n`: há builds do OpenSSL — os do Windows
    # entre eles — que terminam a linha com CRLF. O `\r` sobrevive ao
    # `tr -d '\n'`, entra no segredo e não aparece em tela nenhuma. Numa
    # senha de banco isso vira um `psql` que recusa a senha certa.
    local v; v="$(openssl rand -base64 48 | tr -d '\r\n')"
    criar_segredo "$n" "$v"
    gerados+="${n}=${v}"$'\n'
    ok "Segredo ${n} criado"
  done
  for n in $SEGREDOS_FERNET; do
    if segredo_existe "$n"; then
      pulado "Segredo ${n}"
      aviso "O Docker não deixa reler um segredo: não dá para conferir se ${n} tem os 44 caracteres do Fernet."
      continue
    fi
    # Mesmo `\r\n` do bloco acima, e aqui ele é pior: um `\r` a mais faz a
    # chave sair com 45 caracteres, o Fernet recusa, e a recusa NÃO aparece
    # no deploy — o sistema sobe saudável e quebra semanas depois, quando
    # alguém salvar a senha de SMTP de uma clínica. A conferência de
    # tamanho logo abaixo é a rede que pega isso na hora.
    local v; v="$(openssl rand -base64 32 | tr -d '\r\n' | tr '+/' '-_')"
    if [[ "${#v}" -ne 44 ]]; then
      echo "Chave Fernet gerada com ${#v} caracteres, e o Fernet exige 44. Abortando."
      exit 1
    fi
    criar_segredo "$n" "$v"
    gerados+="${n}=${v}"$'\n'
    ok "Segredo ${n} criado (44 caracteres, base64 url-safe)"
  done

  if [[ -n "$gerados" ]]; then
    echo ""
    echo "${BOLD}${YELLOW}  ┌──────────── ANOTE AGORA — NÃO DÁ PARA VER DE NOVO ─────────────┐${RESET}"
    echo "${BOLD}${YELLOW}  │${RESET} O Docker não deixa ler um segredo de volta. As duas chaves"
    echo "${BOLD}${YELLOW}  │${RESET} mestras cifram certificados de assinatura e as credenciais que"
    echo "${BOLD}${YELLOW}  │${RESET} as clínicas digitam: ${BOLD}perdê-las é perder o que elas cifram${RESET}."
    echo "${BOLD}${YELLOW}  └────────────────────────────────────────────────────────────────┘${RESET}"
    echo ""
    # Laço em vez de `sed`: as variáveis de cor são sequências de escape, e
    # passá-las como texto de substituição do sed é pedir para um terminal
    # exótico transformar a única exibição destas chaves em lixo.
    while IFS= read -r _linha; do
      [[ -n "$_linha" ]] && echo "    ${GREEN}${_linha}${RESET}"
    done <<<"$gerados"
    echo ""
    if sim_nao "Quer que eu grave isto num arquivo temporário (chmod 600) para você copiar?"; then
      local cofre="${HOME}/neurodoc-segredos-ANOTAR-E-APAGAR.txt"
      printf '%s' "$gerados" >"$cofre"; chmod 600 "$cofre"
      caixa_acao \
        "Arquivo: ${cofre}" \
        "Copie para o seu gerenciador de senhas e APAGUE o arquivo:" \
        "  shred -u ${cofre}"
    fi
    enter
  fi

  # Os fornecidos por você. `*_definido` marca o que ESTA execução decidiu;
  # o que veio de execução anterior não é redecidido a partir de um padrão.
  local sms_ligado ia_ligada sms_definido=nao ia_definido=nao
  if ! segredo_existe CLOUDFLARE_DNS_API_TOKEN; then
    caixa_acao \
      "Token de API da Cloudflare (para o certificado TLS por DNS-01):" \
      "  https://dash.cloudflare.com/profile/api-tokens ▸ Create Token" \
      "  Template 'Edit zone DNS' — Zone:DNS:Edit e Zone:Zone:Read," \
      "  restrito à zona ${DOMINIO}."
    local tk; tk="$(perguntar_segredo "Cole o token da Cloudflare")"
    while [[ -z "$tk" ]]; do aviso "Vazio."; tk="$(perguntar_segredo "Cole o token da Cloudflare")"; done
    criar_segredo CLOUDFLARE_DNS_API_TOKEN "$tk"
    ok "Segredo CLOUDFLARE_DNS_API_TOKEN criado"
  else
    pulado "Segredo CLOUDFLARE_DNS_API_TOKEN"
  fi

  if ! segredo_existe NEURODOC_SMTP_PASSWORD; then
    caixa_acao \
      "Senha da caixa contato@${DOMINIO}, na Hostinger." \
      "É a MESMA com que você entra no webmail dessa conta." \
      "(o servidor é smtp.hostinger.com:465, SSL implícito — já no .env.example)"
    local sm; sm="$(perguntar_segredo "Cole a senha do e-mail")"
    while [[ -z "$sm" ]]; do aviso "Vazio."; sm="$(perguntar_segredo "Cole a senha do e-mail")"; done
    criar_segredo NEURODOC_SMTP_PASSWORD "$sm"
    ok "Segredo NEURODOC_SMTP_PASSWORD criado"
  else
    pulado "Segredo NEURODOC_SMTP_PASSWORD"
  fi

  # SMS e IA podem ficar desligados. O segredo tem de existir de qualquer
  # forma — `DISABLED` é lido como "desligado" —, e a chave do `.env` tem de
  # concordar com ele: ligar o SMS com o segredo em DISABLED daria uma falha
  # no log do worker, longe de quem ligou.
  sms_ligado=nao
  if segredo_existe NEURODOC_SMSDEV_API_KEY; then
    pulado "Segredo NEURODOC_SMSDEV_API_KEY"
    sms_ligado="$(lembrado SMS_LIGADO || echo nao)"
  elif sim_nao "Você vai usar SMS (SMSDEV) nesta instalação?"; then
    local sd; sd="$(perguntar_segredo "Cole a chave do SMSDEV")"
    while [[ -z "$sd" ]]; do aviso "Vazio."; sd="$(perguntar_segredo "Cole a chave do SMSDEV")"; done
    criar_segredo NEURODOC_SMSDEV_API_KEY "$sd"; sms_ligado=sim; sms_definido=sim
    ok "Segredo NEURODOC_SMSDEV_API_KEY criado"
  else
    criar_segredo NEURODOC_SMSDEV_API_KEY 'DISABLED'; sms_definido=sim
    ok "NEURODOC_SMSDEV_API_KEY criado como DISABLED"
  fi
  lembrar SMS_LIGADO "$sms_ligado"

  ia_ligada=nao
  if segredo_existe NEURODOC_NVIDIA_API_KEY; then
    pulado "Segredo NEURODOC_NVIDIA_API_KEY"
    ia_ligada="$(lembrado IA_LIGADA || echo nao)"
  elif sim_nao "Você vai usar a IA (provedor padrão NVIDIA) nesta instalação?"; then
    local nv; nv="$(perguntar_segredo "Cole a chave da NVIDIA")"
    while [[ -z "$nv" ]]; do aviso "Vazio."; nv="$(perguntar_segredo "Cole a chave da NVIDIA")"; done
    criar_segredo NEURODOC_NVIDIA_API_KEY "$nv"; ia_ligada=sim; ia_definido=sim
    ok "Segredo NEURODOC_NVIDIA_API_KEY criado"
  else
    criar_segredo NEURODOC_NVIDIA_API_KEY 'DISABLED'; ia_definido=sim
    ok "NEURODOC_NVIDIA_API_KEY criado como DISABLED"
  fi
  lembrar IA_LIGADA "$ia_ligada"

  for n in $SEGREDOS_DESLIGADOS; do
    if segredo_existe "$n"; then pulado "Segredo ${n}"; continue; fi
    criar_segredo "$n" 'DISABLED'
    ok "${n} criado como DISABLED (provedor de IA que esta instalação não usa)"
  done

  faltando=""
  for n in $todos; do segredo_existe "$n" || faltando+=" $n"; done
  [[ -z "$faltando" ]] || { echo "Segredos ainda ausentes:${faltando}"; exit 1; }
  ok "Todos os $(printf '%s\n' $todos | wc -l | tr -d ' ') segredos do stack existem"

  # ───────────────────────────────────────────────────────────── registry ─
  passo "Entrando no GitHub Container Registry"
  if [[ -f "${HOME}/.docker/config.json" ]] && grep -q 'ghcr.io' "${HOME}/.docker/config.json" 2>/dev/null; then
    pulado "Login no ghcr.io"
  else
    local gh_user
    gh_user="$(lembrado GH_USER || true)"
    [[ -n "$gh_user" ]] || gh_user="$(perguntar "Seu usuário do GitHub (dono das imagens)" "ffreua")"
    lembrar GH_USER "$gh_user"
    caixa_acao \
      "Crie um token classic do GitHub:" \
      "  https://github.com/settings/tokens/new" \
      "  Marque write:packages (ele marca read:packages junto)."
    local gh_token; gh_token="$(perguntar_segredo "Cole o token do GitHub")"
    printf '%s' "$gh_token" | docker login ghcr.io -u "$gh_user" --password-stdin >>"$LOG_FILE" 2>&1
    ok "Autenticado no ghcr.io como ${gh_user}"
  fi

  # ────────────────────────────────────────────────────────────────── env ─
  passo "O arquivo .env de produção"
  # `.env.example` é a base versionada com TODAS as chaves; `.env` fica só
  # nesta máquina e sobrescreve o que muda por instalação. O deploy recusa
  # chave que exista só no `.env` — por isso `set_env` confere antes.
  local env_novo=nao
  if [[ -s .env ]]; then
    pulado ".env já existe (não vou sobrescrever o que você ajustou)"
  else
    cp .env.example .env; chmod 600 .env; env_novo=sim
    ok ".env criado a partir do .env.example"
  fi

  local registry_atual gh_user_env
  gh_user_env="$(lembrado GH_USER || echo ffreua)"
  registry_atual="$(get_env REGISTRY)"
  registry_atual="$(perguntar "Registry da imagem (host/namespace/repositório, sem tag)" "${registry_atual:-ghcr.io/${gh_user_env}/neurodoc}")"
  set_env REGISTRY "$registry_atual"

  # SMS e IA só são reescritos quando ESTA execução criou o segredo — aí
  # sabemos a resposta porque acabamos de perguntá-la. Numa reexecução em
  # que o segredo já existia, o estado pode ter se perdido e o padrão "não"
  # desligaria a IA de uma instalação que a usa, em silêncio.
  [[ "$sms_definido" == sim ]] && set_env SMS_ENABLED "$([[ "$sms_ligado" == sim ]] && echo True || echo False)"
  [[ "$ia_definido"  == sim ]] && set_env AI_ENABLED  "$([[ "$ia_ligada"  == sim ]] && echo True || echo False)"

  if [[ "$env_novo" == sim ]]; then
    # Certificado de TESTE na primeira publicação, de propósito: o ambiente
    # de verdade da Let's Encrypt bloqueia o domínio por uma semana depois
    # de cinco falhas seguidas, e a primeira tentativa raramente acerta.
    set_env ACME_DIRECTORY 'https://acme-staging-v02.api.letsencrypt.org/directory'
    # HSTS fica em 0 até o HTTPS provar que funciona. O navegador GUARDA a
    # instrução: ligar antes da hora deixa o site inalcançável para quem já
    # visitou, e não há como voltar atrás pelo servidor.
    set_env SECURE_HSTS_SECONDS '0'
  else
    # Numa reexecução estas duas ficam como estão. Forçá-las de volta
    # rebaixaria para o certificado de teste e desligaria o HSTS de uma
    # instalação que já passou por esses dois passos — um "setup" que
    # desfaz o que o operador fez depois dele.
    info "ACME_DIRECTORY e SECURE_HSTS_SECONDS mantidos como estão (${GREY}$(get_env SECURE_HSTS_SECONDS)s de HSTS${RESET})"
  fi
  ok "Chaves desta instalação ajustadas no .env"
  info "REGISTRY=${registry_atual} · SMS_ENABLED=$(get_env SMS_ENABLED) · AI_ENABLED=$(get_env AI_ENABLED)"

  local backup_dest
  backup_dest="$(get_env BACKUP_AGE_RECIPIENT)"
  if [[ "$backup_dest" == "CHANGE_ME" || -z "$backup_dest" ]]; then
    aviso "BACKUP_AGE_RECIPIENT ainda é CHANGE_ME — o backup cifrado não funciona sem ele."
    info "Gere a chave com 'age-keygen' na SUA máquina (não na VPS) e ponha a pública aqui depois."
  fi

  # ──────────────────────────────────────────────────────── homologação ───
  passo "Registrando a homologação desta versão"
  # O deploy recusa publicar sem um registro dizendo que a versão foi
  # conferida. É uma trava deliberada contra publicar de madrugada sem ter
  # olhado nada — e o script não a contorna sozinho: ele prepara o arquivo
  # e pergunta.
  local sha arquivo
  # Atualiza ANTES de calcular o SHA. `ops/deploy.py` faz `git pull --ff-only`
  # por conta própria logo depois do preflight: sem este passo, o registro
  # seria criado com o nome do commit antigo e a versão publicada seria
  # outra — um registro de homologação apontando para o que não foi ao ar.
  git pull --ff-only >>"$LOG_FILE" 2>&1 || aviso "Não consegui atualizar o repositório agora; seguindo com o commit local."
  sha="$(git rev-parse HEAD)"
  arquivo="docs/releases/${sha}.md"
  local registro_novo=nao
  if [[ -f "$arquivo" ]]; then
    pulado "Registro ${arquivo}"
  else
    registro_novo=sim
    cp docs/releases/TEMPLATE.md "$arquivo"
    ok "Registro criado a partir do modelo: ${arquivo}"
    caixa_acao \
      "Abra e preencha o registro de homologação desta versão:" \
      "  nano ${destino}/${arquivo}" \
      "" \
      "Ele é o que responde, daqui a um ano, 'quem conferiu esta versão'."
    if sim_nao "Quer abrir o editor agora?"; then "${EDITOR:-nano}" "$arquivo" || true; fi
  fi
  # Registro novo (o `git pull` trouxe um commit) zera a autorização: sem
  # isto, a aprovação dada a uma versão passaria a valer para outra, e a
  # trava que existe justamente para impedir publicar sem conferir viraria
  # uma caixa marcada uma vez e esquecida.
  if [[ "$registro_novo" == sim && "$(get_env NEURODOC_RELEASE_APPROVED)" == "True" ]]; then
    set_env NEURODOC_RELEASE_APPROVED 'False'
    aviso "Versão nova (${sha:0:12}): a autorização anterior não vale para ela."
  fi
  if [[ "$(get_env NEURODOC_RELEASE_APPROVED)" == "True" ]]; then
    pulado "NEURODOC_RELEASE_APPROVED=True"
  elif sim_nao "Você conferiu esta versão e autoriza publicá-la?"; then
    set_env NEURODOC_RELEASE_APPROVED 'True'
    ok "Homologação registrada no .env"
  else
    aviso "Sem a homologação o deploy recusa. Rode o script de novo quando tiver conferido."
    exit 0
  fi

  # ─────────────────────────────────────────────────────────────────  DNS ─
  passo "DNS do domínio"
  local ip
  ip="$(lembrado VPS_IP || true)"; [[ -n "$ip" ]] || ip="$(ip_publico)"
  lembrar VPS_IP "$ip"
  caixa_acao \
    "Na Cloudflare, aponte estes registros para ${ip:-o IP da VPS}:" \
    "  A   ${DOMINIO}                 ->  ${ip:-IP_DA_VPS}" \
    "  A   *.${DOMINIO}  (curinga)    ->  ${ip:-IP_DA_VPS}" \
    "" \
    "Modo de SSL na Cloudflare: Full (strict)." \
    "O proxy laranja pode ficar ligado — o certificado sai por DNS-01."
  local resolvido
  resolvido="$(getent hosts "$DOMINIO" 2>/dev/null | awk '{print $1}' | head -n1)" || true
  if [[ -n "$resolvido" ]]; then
    info "${DOMINIO} resolve para ${resolvido} (com proxy, será um IP da Cloudflare — é o esperado)"
  else
    aviso "Ainda não resolvi ${DOMINIO}. O DNS pode levar alguns minutos."
  fi
  sim_nao "O DNS está apontado e posso seguir?" || { aviso "Ajuste o DNS e rode de novo."; exit 0; }

  # ──────────────────────────────────────────────────────────── preflight ─
  passo "Conferindo tudo antes de publicar (ops.deploy --check)"
  # Esta é a verificação de verdade: vinte e tantas pré-condições, a mesma
  # que roda no deploy. Se ela passar, o resto é mecânico.
  # Pelo `scripts/deploy.sh`, e nao chamando `ops.deploy` na mao: aquele
  # script ja resolve a trava de execucao e qual Python usar. Duplicar isso
  # aqui criaria duas formas de publicar que divergem no primeiro ajuste.
  #
  # `bash scripts/...` e nao `./scripts/...`: os scripts do repositorio sao
  # rastreados em modo 644, e um `chmod +x` aqui faria o git ver mudanca de
  # modo. O preflight exige arvore limpa e recusaria o deploy com
  # "Commit or resolve tracked changes" -- por causa do setup, nao do codigo.
  if bash scripts/deploy.sh --check 2>&1 | tee -a "$LOG_FILE"; then
    ok "Preflight aprovado"
  else
    echo ""
    aviso "O preflight recusou. A mensagem acima diz o quê. Os mais comuns:"
    echo "    ${GREY}Configure the ACME account email ......... ACME_EMAIL no .env${RESET}"
    echo "    ${GREY}Release homologation has not been ....... NEURODOC_RELEASE_APPROVED${RESET}"
    echo "    ${GREY}persistent-data node label is missing .... rótulo ${ROTULO_NO} (FASE 1)${RESET}"
    echo "    ${GREY}Invalid network isolation ................ rede criada sem --internal${RESET}"
    echo "    ${GREY}Signing session keys must reside on tmpfs  ${TMPFS_ASSINATURA} (FASE 1)${RESET}"
    echo "    ${GREY}Commit or resolve tracked changes ........ git status no servidor${RESET}"
    echo ""
    echo "  Corrija e rode o script de novo — ele retoma daqui."
    exit 1
  fi

  # ───────────────────────────────────────────────────────────── publicar ─
  passo "Publicando (build, push, stack, espera de saúde)"
  echo "  ${GREY}Leva de 10 a 25 minutos na primeira vez — a imagem é construída aqui.${RESET}"
  echo "  ${GREY}Acompanhe de outro terminal com: watch docker service ls${RESET}"
  echo ""
  if bash scripts/deploy.sh 2>&1 | tee -a "$LOG_FILE"; then
    ok "Publicado"
  else
    echo ""
    aviso "O deploy falhou. Para ver o que houve:"
    echo "    ${CYAN}docker service ps ${STACK}_app --no-trunc${RESET}"
    echo "    ${CYAN}docker service logs ${STACK}_app --tail 100${RESET}"
    echo "  O Swarm volta sozinho para a versão anterior se uma nova não ficar saudável."
    exit 1
  fi

  # ────────────────────────────────────────────── certificado de verdade ──
  passo "Trocando o certificado de teste pelo de verdade"
  if [[ "$(get_env ACME_DIRECTORY)" != *staging* ]]; then
    pulado "Já está no certificado de produção"
  else
    echo "  A publicação acima usou o certificado de TESTE (o navegador reclama dele)."
    if curl -k -sS -o /dev/null -w '%{http_code}' "https://${DOMINIO}/health/" --max-time 20 2>/dev/null | grep -qx '200'; then
      ok "https://${DOMINIO}/health/ respondeu 200 com o certificado de teste"
    else
      aviso "Não consegui confirmar o /health/ ainda. Pode ser propagação de DNS ou o certificado saindo."
    fi
    if sim_nao "O site respondeu. Posso trocar para o certificado de verdade e publicar de novo?"; then
      set_env ACME_DIRECTORY 'https://acme-v02.api.letsencrypt.org/directory'
      fazendo "Publicando de novo com o certificado de produção"
      bash scripts/deploy.sh 2>&1 | tee -a "$LOG_FILE"
      ok "Certificado de produção emitido"
    else
      aviso "Tudo bem. Troque ACME_DIRECTORY no .env e rode 'bash scripts/deploy.sh' quando quiser."
    fi
  fi

  # ──────────────────────────────────────────── backup e limpeza no timer ──
  passo "Backup diário e limpeza de chaves (timers do systemd)"
  # Até esta correção o script terminava sem instalar nada disso, e o
  # resumo final mandava "configure o backup depois". Quem seguisse o
  # resumo ficava sem backup nenhum e só descobria no dia de precisar —
  # que é o dia em que não há como corrigir. Instalar aqui, junto do
  # deploy, é a única ordem em que o esquecimento não é possível.
  #
  # As unidades em `ops/` são moldes: trazem o caminho e o usuário padrão,
  # e aqui recebem os desta instalação, que a FASE 1 pode ter mudado.
  local proj_real usuario_ops
  proj_real="$(pwd)"
  usuario_ops="$(id -un)"
  local unidade ajustes
  ajustes="s#/srv/neurodoc#${proj_real}#g"
  ajustes="${ajustes}; s#^User=neurodocops#User=${usuario_ops}#"
  ajustes="${ajustes}; s#^Group=neurodocops#Group=${usuario_ops}#"
  for unidade in neurodoc-backup neurodoc-signing-cleanup; do
    sudo sed "$ajustes" "ops/${unidade}.service" |
      sudo tee "/etc/systemd/system/${unidade}.service" >/dev/null
    sudo cp "ops/${unidade}.timer" "/etc/systemd/system/${unidade}.timer"
  done
  sudo systemctl daemon-reload
  sudo systemctl enable --now neurodoc-backup.timer neurodoc-signing-cleanup.timer >>"$LOG_FILE" 2>&1
  ok "Timers instalados e ligados (backup às 03:00, limpeza a cada 5 min)"

  # A pasta de destino, antes de o primeiro backup tentar cria-la. Ela mora
  # em /srv, que e do root, e o backup roda como o usuario de operacao:
  # `ops/backup.py` chamava `mkdir(parents=True)` e morria com
  # `PermissionError: [Errno 13] ... '/srv/neurodoc-backups'`.
  #
  # Ninguem criava esta pasta -- nem este script, nem a secao 15.4 do
  # roteiro. A falha nao aparecia na instalacao: o timer ficava ligado e
  # verde, e quem seguisse o resumo final ia dormir achando que tinha
  # backup. Ela aparecia as 03:00 da primeira madrugada, no journal, onde
  # ninguem olha -- e de novo em todas as seguintes, ate a noite em que o
  # backup fizesse falta.
  local pasta_backup
  pasta_backup="$(get_env BACKUP_DIR)"
  if [[ -n "$pasta_backup" ]]; then
    sudo mkdir -p "$pasta_backup"
    sudo chown "$(id -un):$(id -gn)" "$pasta_backup"
    sudo chmod 700 "$pasta_backup"
    ok "Pasta de backup ${pasta_backup} pronta (0700, dona: $(id -un))"
  fi

  # A chave do backup é a única coisa deste servidor que não pode morar
  # neste servidor. Sem ela o arquivo cifrado é lixo — inclusive para você.
  if [[ "$(get_env BACKUP_AGE_RECIPIENT)" == "CHANGE_ME" || -z "$(get_env BACKUP_AGE_RECIPIENT)" ]]; then
    aviso "O timer está ligado, mas BACKUP_AGE_RECIPIENT ainda é CHANGE_ME:"
    echo "    ${GREY}o backup vai falhar todas as noites até você pôr a chave pública 'age'.${RESET}"
    echo "    ${CYAN}age-keygen -o neurodoc-backup.key${RESET}  ${GREY}(na SUA máquina, nunca aqui)${RESET}"
  else
    fazendo "Rodando o primeiro backup agora, para provar que funciona"
    if sudo systemctl start neurodoc-backup.service; then
      ok "Primeiro backup concluído — confira em $(get_env BACKUP_DIR)"
      aviso "Um backup só conta como backup depois de restaurado noutra máquina:"
      echo "    ${CYAN}python -m ops.restore --prepare-data --backup-dir <pasta> --identity <chave>${RESET}"
    else
      aviso "O primeiro backup falhou. Veja: ${CYAN}journalctl -u neurodoc-backup.service -n 50${RESET}"
    fi
  fi

  # ───────────────────────────────────────────────────────── pós-deploy ───
  passo "Sua conta de superadministrador"
  local app_id
  app_id="$(docker ps -q -f "name=${STACK}_app" | head -1)" || true
  if [[ -z "$app_id" ]]; then
    aviso "Contêiner do app ainda não está de pé; crie a conta depois (comandos no fim)."
  elif [[ "$(lembrado SUPERADMIN_CRIADO || echo nao)" == "sim" ]]; then
    pulado "Superadministrador já criado nesta instalação"
  else
    local email nome sobrenome
    email="$(perguntar "Seu e-mail de superadministrador" "")"
    if [[ -n "$email" ]]; then
      nome="$(perguntar "Primeiro nome" "Fernando")"
      sobrenome="$(perguntar "Sobrenome" "Freua")"
      if docker exec "$app_id" python manage.py create_superadmin "$email" \
           --first-name "$nome" --last-name "$sobrenome" --invite 2>&1 | tee -a "$LOG_FILE"; then
        lembrar SUPERADMIN_CRIADO sim
        caixa_acao \
          "O link de definição de senha saiu acima. Ele é de uso único." \
          "Depois de definir a senha, configure a MFA em:" \
          "  https://${DOMINIO}/accounts/mfa/setup/" \
          "O console /instalacao/ não abre sem MFA — é deliberado."
      else
        aviso "create_superadmin falhou; rode depois (comando no fim)."
      fi
    fi
  fi

  passo "Tabela TUSS (o CID-10 já veio sozinho)"
  # O CID-10 é importado na primeira subida, dentro do contêiner. A TUSS vem
  # de uma API externa, e nesta topologia SÓ O WORKER alcança a internet —
  # rodar isto no `app` falharia por timeout, não por erro de código.
  local worker_id
  worker_id="$(docker ps -q -f "name=${STACK}_celery_worker" | head -1)" || true
  if [[ -z "$worker_id" ]]; then
    aviso "Worker ainda não está de pé; rode a TUSS depois (comando no fim)."
  elif [[ "$(lembrado TUSS_OK || echo nao)" == "sim" ]]; then
    pulado "TUSS já sincronizada"
  elif sim_nao "Sincronizar a TUSS agora? (leva alguns minutos)"; then
    if docker exec "$worker_id" python manage.py sync_tuss 2>&1 | tee -a "$LOG_FILE"; then
      lembrar TUSS_OK sim; ok "TUSS sincronizada (ela se atualiza sozinha aos domingos às 4h)"
    else
      aviso "sync_tuss falhou; rode depois (comando no fim)."
    fi
  fi

  passo "Convite da clínica-sede"
  # A organização do próprio Dr. Fernando nasce de um convite de plataforma
  # com plano `custom` sem override — que é a forma decidida de dar acesso
  # irrestrito: visível na tela, auditável e reversível, ao contrário de uma
  # exceção codificada.
  if [[ -z "$app_id" ]]; then
    aviso "Contêiner do app indisponível; emita o convite depois (comando no fim)."
  elif [[ "$(lembrado CONVITE_SEDE || echo nao)" == "sim" ]]; then
    pulado "Convite da sede já emitido"
  elif sim_nao "Emitir o convite de plataforma da clínica-sede (plano custom, irrestrito)?"; then
    local admin_email
    admin_email="$(perguntar "E-mail do superadministrador que emite o convite" "${email:-}")"
    if docker exec "$app_id" python manage.py issue_platform_invitation \
         --issued-by-email "$admin_email" --plan custom \
         --plan-note 'Clinica-sede da instalacao' 2>&1 | tee -a "$LOG_FILE"; then
      lembrar CONVITE_SEDE sim
      caixa_acao "Anote o código do convite acima — ele é de uso único e tem prazo."
    else
      aviso "Emissão do convite falhou; rode depois (comando no fim)."
    fi
  fi

  instrucoes_finais "$destino"
}

instrucoes_finais() {
  local destino="$1"
  faixa "✅  NEURODOC NO AR"
  echo "  ${BOLD}Endereços:${RESET}"
  echo "    • Sistema........: ${CYAN}https://${DOMINIO}${RESET}"
  echo "    • Console.........: ${CYAN}https://${DOMINIO}/instalacao/${RESET}  ${GREY}(exige MFA)${RESET}"
  echo "    • Documentação....: ${CYAN}https://${DOMINIO}/technical-docs/${RESET}"
  echo ""
  echo "  ${BOLD}O que ainda falta fazer (nesta ordem):${RESET}"
  echo "    1. ${BOLD}Definir sua senha${RESET} pelo link do convite e ${BOLD}ligar a MFA${RESET}."
  echo "    2. ${BOLD}Backup${RESET}: o timer diário já está ligado. Se ${CYAN}BACKUP_AGE_RECIPIENT${RESET}"
  echo "       ainda for CHANGE_ME, gere a chave na SUA máquina (${CYAN}age-keygen${RESET}, nunca aqui),"
  echo "       ponha a pública no .env e publique de novo — sem ela o backup falha toda noite."
  echo "       ${BOLD}E restaure uma cópia em outra máquina${RESET} antes de confiar nela:"
  echo "       ${CYAN}python -m ops.restore --prepare-data --backup-dir <pasta> --identity <chave>${RESET}"
  echo "    3. ${BOLD}HSTS${RESET}: só depois de o cadeado aparecer sem aviso —"
  echo "       ${CYAN}SECURE_HSTS_SECONDS=31536000${RESET} no .env e ${CYAN}bash scripts/deploy.sh${RESET}."
  echo "       ${GREY}O navegador guarda a instrução; ligar cedo demais não tem volta.${RESET}"
  echo ""
  echo "  ${BOLD}Dia a dia (em ${destino}):${RESET}"
  echo "    • Publicar atualização.: ${CYAN}bash scripts/deploy.sh${RESET}"
  echo "    • Conferir sem publicar: ${CYAN}bash scripts/deploy.sh --check${RESET}"
  echo "    • Status...............: ${CYAN}docker service ls${RESET}"
  echo "    • Log do app...........: ${CYAN}docker service logs ${STACK}_app --tail 100 -f${RESET}"
  echo "    • Voltar atrás.........: ${CYAN}docker service rollback ${STACK}_app${RESET}"
  echo ""
  echo "  ${BOLD}Comandos que talvez tenham ficado para depois:${RESET}"
  echo "    ${GREY}# superadministrador${RESET}"
  echo "    ${CYAN}docker exec \$(docker ps -q -f name=${STACK}_app | head -1) \\"
  echo "      python manage.py create_superadmin SEU@EMAIL --first-name Nome --last-name Sobrenome --invite${RESET}"
  echo "    ${GREY}# TUSS — no WORKER, que é quem alcança a internet${RESET}"
  echo "    ${CYAN}docker exec \$(docker ps -q -f name=${STACK}_celery_worker | head -1) \\"
  echo "      python manage.py sync_tuss${RESET}"
  echo "    ${GREY}# convite da clínica-sede, plano custom (irrestrito)${RESET}"
  echo "    ${CYAN}docker exec \$(docker ps -q -f name=${STACK}_app | head -1) \\"
  echo "      python manage.py issue_platform_invitation --issued-by-email SEU@EMAIL --plan custom${RESET}"
  echo "    ${GREY}# testar o e-mail${RESET}"
  echo "    ${CYAN}docker exec \$(docker ps -q -f name=${STACK}_celery_worker | head -1) \\"
  echo "      python manage.py testar_email SEU@EMAIL${RESET}"
  echo ""
  echo "  ${BOLD}${RED}Nunca rode 'manage.py migrate' à mão.${RESET} A conexão padrão é o usuário"
  echo "  ${GREY}da aplicação, sem permissão de criar tabela. Quem migra é o próprio${RESET}"
  echo "  ${GREY}contêiner na subida, sob trava, com a conexão de dono do esquema.${RESET}"
  echo ""
  echo "  ${GREY}Passo a passo completo: docs/operations/primeiro-deploy.md${RESET}"
  echo "  ${GREY}Log desta execução....: ${LOG_FILE}${RESET}"
  _log "CONCLUIDO"
}

# =============================================================================
#  Roteamento
# =============================================================================
touch "$LOG_FILE" 2>/dev/null || true
chmod 600 "$LOG_FILE" 2>/dev/null || true

if [[ "${1:-}" != "--como-operador" ]]; then
  faixa "🚀  NEURODOC — SETUP DE VPS E PRIMEIRO DEPLOY"
  echo "  Faz o que docs/operations/primeiro-deploy.md descreve, do zero."
  echo "  É seguro rodar de novo: retoma de onde parou."
  echo ""
  echo "  ${BOLD}📋 Tenha em mãos:${RESET}"
  echo "    • ${BOLD}Token da Cloudflare${RESET} (template 'Edit zone DNS', zona ${DOMINIO})"
  echo "    • ${BOLD}Token classic do GitHub${RESET} (escopo write:packages)"
  echo "    • ${BOLD}Senha de contato@${DOMINIO}${RESET} (a mesma do webmail Hostinger)"
  echo "    • ${BOLD}Chave da NVIDIA${RESET} e ${BOLD}do SMSDEV${RESET}, se for usar IA e SMS"
  echo "    • O domínio ${BOLD}${DOMINIO}${RESET} já gerenciado na Cloudflare"
  echo ""
  echo "  ${GREY}Este script não constrói nem publica imagem por conta própria —${RESET}"
  echo "  ${GREY}quem faz isso é ops/deploy.py, com o preflight e a volta atrás dele.${RESET}"
  if [[ "$(id -u)" -eq 0 ]]; then
    echo ""
    sim_nao "Posso começar a preparar o servidor?" || { echo "  Sem problema — rode quando estiver pronto."; exit 0; }
  fi
fi

if [[ "$(id -u)" -eq 0 ]]; then
  fase_servidor   # termina com 'exec' para a FASE 2 como o usuário de operação
else
  fase_deploy
fi
