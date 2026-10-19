#!/usr/bin/env bash
# Só a Cloudflare chega às portas 80 e 443 da VPS.
#
# Desde 2026-10-19 o domínio passa pelo proxy da Cloudflare. Sem esta
# trava, o proxy protegia só quem chegava pelo nome: quem soubesse o IP do
# servidor (e ele esteve no DNS público até aquele dia) falava direto com
# o Traefik, sem a absorção de ataque e sem as regras da borda.
#
# POR QUE NÃO É UMA REGRA DO UFW. O Docker publica as portas por DNAT, e o
# pacote redirecionado atravessa a cadeia FORWARD, não a INPUT: o `ufw`
# nunca o vê. O lugar que o Docker reserva para regra do administrador é a
# cadeia DOCKER-USER, que ele cria vazia e não apaga ao reiniciar. No IPv6
# não há DNAT — o docker-proxy escuta direto em [::]:80/443 —, então ali a
# trava é na INPUT.
#
# AS QUATRO TRAVAS DE SEGURANÇA, porque errar aqui tira o site do ar:
#   1. lista vazia ou estranha nunca é aplicada: vale a última lista boa,
#      guardada em disco; sem nenhuma, o script sai sem tocar em nada;
#   2. a regra só vale para conexão NOVA que ENTRA pela interface externa.
#      O worker falando com SMTP, SMS e IA sai pelas pontes do Docker e
#      não passa por ela;
#   3. depois de aplicar, o script pede /health/ pelo domínio — o pedido
#      sai para a Cloudflare e volta pela borda dela, exatamente o caminho
#      de um paciente. Se não der 200, desfaz tudo e sai com erro;
#   4. a porta 22 não é tocada.
#
# Desfazer à mão: `bash ops/cloudflare_firewall.sh --remover`.
#
# A lista de faixas muda raramente, mas muda; o timer roda uma vez por dia.
# Ela é a mesma que o deploy põe no `traefik.yml` e que o `.env` declara em
# TRUSTED_PROXIES — mudando a lista, as três precisam acompanhar.
set -euo pipefail

DOMINIO="${NEURODOC_DOMINIO:-neurodoc.app.br}"
ESTADO=/var/lib/neurodoc/cloudflare
CADEIA4=NEURODOC-CF
CADEIA6=NEURODOC-CF6
PORTAS=80,443

interface_externa() { ip route get 1.1.1.1 | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}'; }

remover() {
    local ext; ext="$(interface_externa)"
    while iptables -C DOCKER-USER -i "$ext" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA4" 2>/dev/null; do
        iptables -D DOCKER-USER -i "$ext" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA4"
    done
    while ip6tables -C INPUT -i "$ext" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA6" 2>/dev/null; do
        ip6tables -D INPUT -i "$ext" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA6"
    done
    iptables -F "$CADEIA4" 2>/dev/null && iptables -X "$CADEIA4" 2>/dev/null || true
    ip6tables -F "$CADEIA6" 2>/dev/null && ip6tables -X "$CADEIA6" 2>/dev/null || true
}

if [[ "${1:-}" == "--remover" ]]; then
    remover
    echo "Trava removida: as portas 80 e 443 voltam a aceitar qualquer origem."
    exit 0
fi

# ---------------------------------------------------------------- a lista
mkdir -p "$ESTADO"
chmod 700 "$ESTADO"

# Uma lista só é aceita se tiver o tamanho de sempre (hoje 15 faixas IPv4
# e 7 IPv6) e só linhas de faixa. Página de erro, resposta vazia ou HTML de
# um proxy no meio do caminho não passam.
obter() {
    local versao="$1" minimo="$2" padrao="$3" nova
    nova="$(curl -fsS --max-time 20 "https://www.cloudflare.com/ips-v${versao}" 2>/dev/null \
            | tr -d '\r' | grep -E "$padrao" || true)"
    if [[ "$(printf '%s\n' "$nova" | grep -c .)" -ge "$minimo" ]] \
       && ! printf '%s\n' "$nova" | grep -vqE "$padrao"; then
        printf '%s\n' "$nova" > "$ESTADO/ips-v${versao}.tmp"
        mv "$ESTADO/ips-v${versao}.tmp" "$ESTADO/ips-v${versao}"
    elif [[ -s "$ESTADO/ips-v${versao}" ]]; then
        echo "Aviso: lista IPv${versao} da Cloudflare indisponível ou estranha; uso a última boa." >&2
    else
        echo "ERRO: sem lista IPv${versao} da Cloudflare e sem cópia guardada. Nada foi alterado." >&2
        exit 1
    fi
}
obter 4 10 '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$'
obter 6 4 '^[0-9a-f:]+/[0-9]{1,3}$'

# ---------------------------------------------------------------- aplicar
EXT="$(interface_externa)"
[[ -n "$EXT" ]] || { echo "ERRO: não achei a interface externa. Nada foi alterado." >&2; exit 1; }

# A cadeia é montada inteira antes de o salto existir: não há instante em
# que a porta fique fechada para a Cloudflare.
montar() {
    local cmd="$1" cadeia="$2" lista="$3"
    $cmd -N "$cadeia" 2>/dev/null || $cmd -F "$cadeia"
    while read -r faixa; do
        [[ -n "$faixa" ]] && $cmd -A "$cadeia" -s "$faixa" -j RETURN
    done < "$lista"
    $cmd -A "$cadeia" -j DROP
}
montar iptables "$CADEIA4" "$ESTADO/ips-v4"
montar ip6tables "$CADEIA6" "$ESTADO/ips-v6"

iptables -C DOCKER-USER -i "$EXT" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA4" 2>/dev/null \
    || iptables -I DOCKER-USER 1 -i "$EXT" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA4"
ip6tables -C INPUT -i "$EXT" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA6" 2>/dev/null \
    || ip6tables -I INPUT 1 -i "$EXT" -p tcp -m multiport --dports "$PORTAS" -m conntrack --ctstate NEW -j "$CADEIA6"

# ---------------------------------------------------------------- conferir
for tentativa in 1 2 3; do
    codigo="$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://${DOMINIO}/health/" || true)"
    if [[ "$codigo" == "200" ]]; then
        echo "Trava aplicada em ${EXT}: $(grep -c . "$ESTADO/ips-v4") faixas IPv4 e $(grep -c . "$ESTADO/ips-v6") IPv6 da Cloudflare; ${DOMINIO}/health/ respondeu 200 pela borda."
        exit 0
    fi
    sleep 5
done

remover
echo "ERRO: depois da trava, ${DOMINIO}/health/ respondeu '${codigo}'. A trava foi DESFEITA; o site segue aberto como antes." >&2
exit 1
