# Primeiro deploy, do zero, passo a passo

Este documento assume que você **nunca administrou um servidor**. Cada
comando vem com o que ele faz e como saber se deu certo. Siga na ordem;
nenhum passo depende de um posterior.

Onde aparecer `SEU-USUARIO-GITHUB`, `SEU-IP` ou algo em MAIÚSCULAS entre
sinais de menor/maior, troque pelo seu valor.

> **Regra de ouro:** se a saída de um comando não for a descrita, **pare**
> e resolva antes de seguir. Um passo pulado aqui aparece três passos
> adiante como um erro que não tem relação aparente com a causa.

## Dois caminhos

Há duas formas de fazer este primeiro deploy, e as duas chegam ao mesmo
lugar:

| | O que é | Quando usar |
| --- | --- | --- |
| **Automatizado** | `scripts/setup_deploy.sh` faz as seções 3 a 15 sozinho | É o normal. Use este. |
| **Manual** | as seções 3 a 16 deste documento, comando por comando | Quando algo falhar no automatizado, ou quando você quiser entender o porquê de cada passo |

O script **não** substitui este documento: ele executa o que está aqui. É
aqui que está escrito *por que* cada passo existe, e é aqui que você volta
quando o automatizado parar no meio.

---

## 1. O caminho automatizado, passo a passo

### 1.1 Antes de começar, tenha em mãos

O script vai parar e pedir cada uma destas coisas. Separe antes — sair no
meio para criar um token é o que faz o primeiro deploy virar uma tarde:

- **Token de API da Cloudflare** — template *Edit zone DNS*, permissões
  `Zone > DNS > Edit` e `Zone > Zone > Read`, restrito à zona
  `neurodoc.app.br` (seção 5.4 explica).
- **Token classic do GitHub** — escopo `write:packages` (seção 9).
- **Senha da caixa `contato@neurodoc.app.br`** na Hostinger — a mesma do
  webmail.
- **Chave da NVIDIA** e **do SMSDEV**, se for usar IA e SMS. Se não for, o
  script cria os segredos como `DISABLED` e desliga as duas no `.env`.
- A VPS criada, com Ubuntu 24.04 e acesso `root` por SSH (seções 1 e 2).

### 1.2 Leve o script para a VPS

O repositório é **privado**, então o `curl https://raw.githubusercontent.com/...`
que se vê nos tutoriais devolve **404** — aquele endereço não lê
repositório privado. Da sua máquina, no PowerShell:

```powershell
scp -i $env:USERPROFILE\.ssh\neurodoc `
    $env:USERPROFILE\projects\neurodoc\scripts\setup_deploy.sh `
    root@SEU-IP:/root/
```

É o caminho mais simples, e a vantagem não é só comodidade: **nenhum token
precisa existir na VPS antes de o script rodar**. Quem cria a chave do
GitHub e faz o login no registry é ele, na ordem certa.

Se preferir baixar de dentro da VPS, use a **API** do GitHub, que lê
repositório privado (o host `raw.` não lê):

```bash
curl -fsSL \
  -H "Authorization: Bearer SEU-TOKEN" \
  -H "Accept: application/vnd.github.raw" \
  https://api.github.com/repos/ffreua/neurodoc/contents/scripts/setup_deploy.sh \
  -o setup_deploy.sh
```

Ou clone o repositório antes, por HTTPS com token — o script percebe o
clone existente e pula a etapa de trazer o código:

```bash
git clone https://SEU-TOKEN@github.com/ffreua/neurodoc.git /opt/neurodoc
bash /opt/neurodoc/scripts/setup_deploy.sh
```

### 1.3 Rode, como `root`

```bash
bash setup_deploy.sh
```

Ele se apresenta, lista o que você precisa ter em mãos e pergunta se pode
começar. A partir daí trabalha sozinho, parando só onde você é
indispensável.

### 1.4 O que ele faz, na ordem

**Fase 1, como `root`** (seções 3, 4 e 6 deste documento): atualiza o
sistema, instala utilitários, ajusta o fuso, sobe o fail2ban, cria o swap,
liga o firewall liberando 22/80/443, aplica o *tuning* de produção,
instala o Docker e o configura para produção, inicializa o Swarm, aplica o
rótulo `neurodoc_data=true`, monta o tmpfs das chaves de assinatura, cria
o usuário de operação e lhe passa o bastão.

**Fase 2, como o usuário de operação** (seções 5 e 7 a 15): gera a chave
SSH do GitHub, clona o repositório, cria o `.venv-ops`, cria as três redes
overlay com o isolamento certo, cria os quinze segredos, entra no
registry, monta o `.env`, prepara o registro de homologação, confere o
DNS, roda o preflight, **publica**, troca o certificado de teste pelo de
verdade, cria seu superadministrador, sincroniza a TUSS e emite o convite
da clínica-sede.

### 1.5 Onde ele para e espera por você

| Ele pede | Você faz |
| --- | --- |
| Chave pública SSH na tela | Cola em **GitHub ▸ Settings ▸ SSH and GPG keys ▸ New SSH key** |
| Token classic do GitHub | Cria em **Settings ▸ Developer settings ▸ Tokens (classic)**, escopo `write:packages` |
| Token da Cloudflare | Cria em **dash.cloudflare.com ▸ API Tokens**, template *Edit zone DNS* |
| Senha do e-mail, chaves de IA/SMS | Cola (não aparecem na tela) |
| As chaves geradas, numa caixa amarela | **Anota num gerenciador de senhas** — o Docker não deixa lê-las de novo |
| Registro de homologação | Preenche `docs/releases/<sha>.md` e autoriza a publicação |
| Registros DNS | Aponta `neurodoc.app.br` e `*.neurodoc.app.br` para o IP da VPS |

> **A caixa amarela é a única chance.** O Docker não devolve o conteúdo de
> um segredo, nem para conferir. As duas chaves-mestras cifram os
> certificados de assinatura e as credenciais que as clínicas digitam:
> perdê-las é perder o que elas cifram, sem recuperação. Anote ali, na
> hora.

### 1.6 Se parar no meio

Rode de novo: `bash setup_deploy.sh`. Ele **retoma de onde parou** — cada
passo pergunta ao mundo real (o segredo existe? a rede existe? o rótulo
está no nó?) antes de agir, e pula o que já está feito. Suas respostas
ficam guardadas, então ele não repergunta o que você já disse.

Se o preflight recusar, a mensagem dele diz exatamente o que falta, e o
script imprime a tradução das recusas mais comuns para a seção
correspondente deste documento.

### 1.7 O que o script deliberadamente NÃO faz

Ele não constrói imagem, não dá `docker push` e não roda `docker stack
deploy`. Quem faz isso é `ops/deploy.py`, que fixa as imagens por digest,
espera cada serviço ficar saudável e volta atrás sozinho se algum não
ficar.

Um script de setup que refizesse esses passos viraria uma **segunda
verdade** sobre como se publica o NeuroDoc — e as duas divergiriam no
primeiro ajuste, com a diferença aparecendo em produção. Ele deixa a
máquina exatamente no estado que `ops.deploy --check` exige, e chama o
deploy de verdade.

### 1.8 Depois que terminar

Três coisas ficam para você, e o script as lista no fim:

1. Definir sua senha pelo link do convite e **ligar a MFA** — o console
   `/instalacao/` não abre sem ela.
2. **Backup**: gerar a chave `age` na **sua** máquina (não na VPS), pôr a
   pública em `BACKUP_AGE_RECIPIENT` e publicar de novo (seção 15.4).
3. **HSTS**: só depois de o cadeado aparecer sem aviso (seção 15.3).

---

## O caminho manual

As seções a seguir são o passo a passo completo, comando por comando. Leia
mesmo que vá usar o script: é aqui que está o *porquê* de cada escolha, e é
a única saída quando algo falhar no meio.

---

## 0. O que você vai precisar

| Item | Onde | Custo aproximado |
| --- | --- | --- |
| Domínio `neurodoc.app.br` | já é seu (Registro.br) | — |
| Conta Cloudflare | cloudflare.com | grátis |
| VPS | Hostinger | ~R$ 60–120/mês |
| Conta GitHub | github.com | grátis |

**Tamanho da VPS.** Os limites de memória declarados no `docker-stack.yml`
somam cerca de **9 GiB** e 5,5 vCPU com duas réplicas da aplicação.
Limites são teto, não reserva — o uso real é menor —, mas escolher abaixo
disso significa que um pico derruba um serviço. Recomendado:

- **Mínimo real:** 4 vCPU / 8 GB RAM / 100 GB disco
- **Confortável:** 4 vCPU / 16 GB RAM / 200 GB disco (Hostinger KVM 4)

Sistema operacional: **Ubuntu 24.04 LTS**. Não escolha painel de controle
(nem Plesk, nem hPanel com aplicativos): eles instalam um servidor web que
vai disputar as portas 80 e 443 com o nosso.

---

## 1. Criar a chave SSH no seu computador

A chave SSH substitui a senha para entrar no servidor. São dois arquivos:
um **privado** (fica só com você, nunca sai da sua máquina) e um
**público** (você entrega ao servidor).

Abra o **PowerShell** no Windows e rode:

```powershell
ssh-keygen -t ed25519 -C "fernando@neurodoc" -f $env:USERPROFILE\.ssh\neurodoc
```

Ele pergunta uma *passphrase*. **Digite uma** e guarde — é a senha que
protege a chave caso alguém copie o arquivo do seu computador. (Você a
digitará ao conectar; o Windows pode memorizá-la, veja abaixo.)

Resultado: dois arquivos em `C:\Users\<você>\.ssh\`:

- `neurodoc` — a chave **privada**. Nunca envie a ninguém, nunca coloque
  no Git, nunca cole num chat.
- `neurodoc.pub` — a chave **pública**. Esta sim vai para o servidor.

Veja o conteúdo da pública (você vai colar isso na Hostinger):

```powershell
Get-Content $env:USERPROFILE\.ssh\neurodoc.pub
```

Sai uma linha só, começando com `ssh-ed25519 AAAA...`. Copie inteira.

**Para não digitar a passphrase toda vez**, ligue o agente do Windows:

```powershell
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
ssh-add $env:USERPROFILE\.ssh\neurodoc
```

---

## 2. Criar a VPS na Hostinger

1. Entre no painel da Hostinger → **VPS** → **Comprar/Gerenciar**.
2. Escolha o plano (veja o passo 0) e a localização **mais próxima do
   Brasil** disponível (São Paulo, se houver).
3. Em sistema operacional, escolha **Ubuntu 24.04 LTS** puro — sem painel.
4. Na etapa de **chave SSH**, cole a linha `ssh-ed25519 AAAA...` que você
   copiou. Se a Hostinger só oferecer senha de root nessa tela, aceite a
   senha e adicione a chave no passo 3.
5. Anote o **endereço IP** que a Hostinger mostrar. Ele será o `SEU-IP`
   daqui em diante.

Teste a entrada, no PowerShell:

```powershell
ssh -i $env:USERPROFILE\.ssh\neurodoc root@SEU-IP
```

Na primeira vez ele pergunta se confia no servidor: responda `yes`. Se
aparecer um prompt como `root@srv123:~#`, você está dentro.

---

## 3. Primeiro acesso: deixar o servidor seguro

Todos os comandos desta seção rodam **dentro do servidor** (depois do
`ssh`).

### 3.1 Atualizar o sistema

```bash
apt update && apt upgrade -y
```

### 3.2 Criar um usuário que não é root

Trabalhar como `root` o tempo todo é como usar uma serra sem proteção:
funciona até o dia em que não funciona.

```bash
adduser --disabled-password --gecos "" neurodocops
usermod -aG sudo neurodocops
mkdir -p /home/neurodocops/.ssh
cp /root/.ssh/authorized_keys /home/neurodocops/.ssh/authorized_keys
chown -R neurodocops:neurodocops /home/neurodocops/.ssh
chmod 700 /home/neurodocops/.ssh
chmod 600 /home/neurodocops/.ssh/authorized_keys
```

> Se a Hostinger não colocou sua chave (você entrou com senha), crie o
> arquivo à mão: `nano /home/neurodocops/.ssh/authorized_keys`, cole a
> linha `ssh-ed25519 ...`, salve com `Ctrl+O`, `Enter`, `Ctrl+X`.

Permita que ele use `sudo` sem digitar senha (ele não tem senha):

```bash
echo 'neurodocops ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/neurodocops
chmod 440 /etc/sudoers.d/neurodocops
```

**Abra outro PowerShell** (não feche o atual) e teste:

```powershell
ssh -i $env:USERPROFILE\.ssh\neurodoc neurodocops@SEU-IP
```

Só siga quando isso funcionar. Se você desligar o acesso de root no passo
seguinte sem ter testado este, fica sem como entrar.

### 3.3 Desligar senha e acesso direto de root

```bash
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

### 3.4 Firewall

Só três portas abertas: SSH, HTTP e HTTPS.

```bash
sudo apt install -y ufw
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status
```

Deve listar as três portas como `ALLOW`.

### 3.5 Fuso horário

```bash
sudo timedatectl set-timezone America/Sao_Paulo
```

---

## 4. Instalar o Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker neurodocops
```

**Saia e entre de novo** (`exit`, depois o `ssh` outra vez) para o grupo
valer. Confirme:

```bash
docker version
```

Deve mostrar `Client` e `Server` sem erro de permissão.

---

## 5. Cloudflare: DNS e o token do certificado

O certificado HTTPS é emitido por **desafio de DNS**: o Traefik cria um
registro temporário no seu domínio para provar à Let's Encrypt que o
domínio é seu. Por isso ele precisa de um token da Cloudflare — e por isso
funciona mesmo antes de o site estar no ar.

### 5.1 Apontar o domínio para a Cloudflare

1. Em cloudflare.com, **Add a site** → digite `neurodoc.app.br`.
2. Escolha o plano **Free**.
3. A Cloudflare mostra **dois servidores de nomes** (algo como
   `ana.ns.cloudflare.com` e `bob.ns.cloudflare.com`). Copie os dois.
4. Entre no **Registro.br**, abra o domínio `neurodoc.app.br` → **Alterar
   servidores DNS** → substitua pelos dois da Cloudflare → salve.
5. A propagação leva de minutos a algumas horas. A Cloudflare avisa por
   e-mail quando o domínio estiver ativo.

### 5.2 Criar os registros

No painel da Cloudflare, em **DNS → Records**, crie dois:

| Tipo | Nome | Conteúdo | Proxy |
| --- | --- | --- | --- |
| A | `@` | `SEU-IP` | **Proxied** (nuvem laranja) |
| A | `*` | `SEU-IP` | **Proxied** (nuvem laranja) |

O `*` (curinga) atende os subdomínios por clínica. Deixe os dois
**Proxied**: é assim que a Cloudflare esconde o IP do servidor e filtra
tráfego hostil antes de ele chegar em você.

### 5.3 Modo de SSL

Em **SSL/TLS → Overview**, escolha **Full (strict)**.

Qualquer outro modo ou quebra (Off, Flexible) ou aceita certificado
inválido (Full). *Strict* é o que exige que o certificado do seu servidor
seja de verdade — que é justamente o que vamos emitir.

### 5.4 O token de API

1. Cloudflare → canto superior direito → **My Profile** → **API Tokens**.
2. **Create Token** → modelo **Edit zone DNS** → **Use template**.
3. Em *Zone Resources*, escolha **Include → Specific zone →
   neurodoc.app.br**.
4. **Continue to summary** → **Create Token**.
5. **Copie o token agora.** A Cloudflare não o mostra de novo.

Guarde-o num lugar seguro: ele vira um segredo do Docker no passo 7.

---

## 6. Preparar o Swarm

De volta ao servidor, como `neurodocops`.

### 6.1 Ligar o modo Swarm

```bash
docker swarm init --advertise-addr SEU-IP
```

### 6.2 Marcar o nó como o que guarda os dados

O sistema exige esse rótulo para saber onde os volumes de dados vivem.
Num servidor só, é este mesmo — mas o rótulo tem de estar lá.

```bash
docker node update --label-add neurodoc_data=true $(docker node ls -q)
docker node inspect self --format '{{ .Spec.Labels }}'
```

Deve imprimir `map[neurodoc_data:true]`.

### 6.3 Criar as três redes

A separação é o coração da segurança da instalação: **só o worker alcança
a internet**. O processo web não alcança — e é por isso que um e-mail sai
pela fila, e não de dentro da requisição.

```bash
docker network create --driver overlay --attachable traefik_public
docker network create --driver overlay --internal neurodoc_v1_internal
docker network create --driver overlay --attachable neurodoc_v1_egress
```

Confira o isolamento (o do meio **tem** de dizer `true`):

```bash
for n in traefik_public neurodoc_v1_internal neurodoc_v1_egress; do
  echo -n "$n interna="; docker network inspect $n --format '{{.Internal}}'
done
```

Esperado: `false`, `true`, `false`.

### 6.4 A pasta das chaves de assinatura, em memória

As chaves de sessão de assinatura digital **não podem tocar o disco**.

```bash
sudo mkdir -p /run/neurodoc-signing
sudo mount -t tmpfs -o size=16m,mode=0700 tmpfs /run/neurodoc-signing
echo 'tmpfs /run/neurodoc-signing tmpfs size=16m,mode=0700 0 0' | sudo tee -a /etc/fstab
findmnt -n -o FSTYPE -T /run/neurodoc-signing
```

A última linha deve imprimir `tmpfs`. A linha no `/etc/fstab` faz isso
sobreviver a um reinício do servidor.

---

## 7. Os segredos

Segredo do Docker é um arquivo que só os serviços autorizados enxergam.
São quinze. **Nenhum deles aparece em arquivo de configuração nem no Git.**

### 7.1 Os que são gerados aleatoriamente

São **dois** blocos, e eles não são intercambiáveis. Os seis primeiros
podem ser qualquer texto aleatório; as duas chaves-mestras têm um formato
obrigatório, e o texto aleatório comum **não serve**.

Primeiro bloco — senhas e a chave do Django. Cole inteiro:

```bash
for s in NEURODOC_DJANGO_SECRET_KEY NEURODOC_DB_ADMIN_PASSWORD \
         NEURODOC_DB_OWNER_PASSWORD NEURODOC_DB_APP_PASSWORD \
         NEURODOC_RABBITMQ_PASSWORD NEURODOC_REDIS_PASSWORD; do
  openssl rand -base64 48 | tr -d '\r\n' | docker secret create "$s" -
done
```

Segundo bloco — as duas chaves-mestras de cifragem. Cole inteiro:

```bash
for s in NEURODOC_PFX_MASTER_KEY NEURODOC_SECRETS_MASTER_KEY; do
  k=$(openssl rand -base64 32 | tr -d '\r\n' | tr '+/' '-_')
  echo "$s: ${#k} caracteres (tem de ser 44)"
  printf '%s' "$k" | docker secret create "$s" -
done
unset k
```

Ele imprime o tamanho **antes** de criar cada segredo. As duas linhas têm
de dizer `44 caracteres`. Se disserem outra coisa, pare: o comando foi
digitado errado.

**Por que o segundo comando é diferente.** Essas duas chaves alimentam o
Fernet, que exige exatamente 32 bytes em base64 *url-safe* — 44 caracteres.
O comando do primeiro bloco produz 48 bytes em base64 comum, 64 caracteres,
e o Fernet recusa com `Fernet key must be 32 url-safe base64-encoded bytes`.

E essa recusa **não aparece no deploy**: o sistema sobe normalmente, fica
saudável e serve o site. Ela aparece semanas depois, na primeira vez que
alguém salvar a senha do e-mail de uma clínica ou enviar um certificado de
assinatura — com o sistema já em uso, e sem nada indicando que a causa foi
um comando digitado no primeiro dia. O `tr '+/' '-_'` é o que converte o
base64 comum em url-safe; o `-base64 32` é o que acerta o tamanho.

O `tr -d '\r\n'` apaga os **dois** terminadores, e não só o `\n`. Há builds
do OpenSSL — os do Windows entre eles — que terminam a linha com CRLF: o
`\r` sobrevive a um `tr -d '\n'`, entra no segredo e não aparece em tela
nenhuma. A chave sai com 45 caracteres em vez de 44, e é exatamente por
isso que o comando imprime o tamanho antes de criar cada segredo.

> O Docker **não deixa ler um segredo de volta**, nem para conferir. Por
> isso o passo 15.4 pede que você os anote num gerenciador de senhas no
> momento em que os cria. Se errar uma das duas chaves-mestras e só
> descobrir depois, a correção é apagar e recriar o segredo — o que é
> indolor **antes** de haver dado cifrado, e impossível depois.

> `NEURODOC_PFX_MASTER_KEY` e `NEURODOC_SECRETS_MASTER_KEY` cifram os
> certificados de assinatura e as credenciais que as clínicas digitam.
> **Perder essas duas significa perder o acesso ao que elas cifram** — e
> não há como recuperar. Elas entram no seu backup de segredos (passo 15).

### 7.2 Os que você fornece

```bash
# Token da Cloudflare (passo 5.4)
printf '%s' 'COLE-O-TOKEN-AQUI' | docker secret create CLOUDFLARE_DNS_API_TOKEN -

# Senha da caixa contato@neurodoc.app.br, na Hostinger.
# É a MESMA senha com que você entra no webmail dessa conta.
printf '%s' 'SUA-SENHA-DO-EMAIL' | docker secret create NEURODOC_SMTP_PASSWORD -

# Chave do SMSDEV
printf '%s' 'SUA-CHAVE-SMSDEV' | docker secret create NEURODOC_SMSDEV_API_KEY -

# Chave da NVIDIA (IA padrão do sistema)
printf '%s' 'SUA-CHAVE-NVIDIA' | docker secret create NEURODOC_NVIDIA_API_KEY -
```

### 7.3 Os que você não usa (mas o stack exige)

O sistema aceita outros provedores de IA. Você não precisa deles, mas os
segredos têm de existir — a palavra `DISABLED` é lida como "desligado":

```bash
for s in NEURODOC_OPENROUTER_API_KEY NEURODOC_OPENAI_API_KEY NEURODOC_ANTHROPIC_API_KEY; do
  printf 'DISABLED' | docker secret create "$s" -
done
```

### 7.4 Conferir

```bash
docker secret ls --format '{{.Name}}' | sort
```

Devem aparecer **quinze** nomes. Se faltar um, o deploy recusa e diz qual.

---

## 8. Trazer o código

### 8.1 Chave SSH do servidor para o GitHub

```bash
ssh-keygen -t ed25519 -C "neurodoc-vps" -f ~/.ssh/github -N ""
cat ~/.ssh/github.pub
```

Copie a linha e, no GitHub: **Settings → SSH and GPG keys → New SSH key**,
cole e salve. Configure o SSH para usá-la:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -T git@github.com
```

A última linha responde `Hi <seu-usuario>! You've successfully
authenticated...` — é o esperado (ela diz que o GitHub não dá shell).

### 8.2 Clonar

```bash
sudo apt install -y git python3-venv python3-pip
cd /opt
sudo git clone git@github.com:SEU-USUARIO-GITHUB/neurodoc.git
sudo chown -R neurodocops:neurodocops /opt/neurodoc
cd /opt/neurodoc
python3 -m venv .venv-ops
.venv-ops/bin/pip install pyyaml
```

> O `.venv-ops` existe só para o script de deploy poder ler YAML. A
> aplicação roda dentro do contêiner, com as dependências próprias.

---

## 9. Entrar no registry de imagens

A imagem construída é publicada no **GitHub Container Registry** (grátis
para repositórios privados). Isso dá reprodutibilidade e volta atrás: cada
versão publicada fica identificada pelo commit.

1. No GitHub: **Settings → Developer settings → Personal access tokens →
   Tokens (classic) → Generate new token**.
2. Marque **`write:packages`** (ele marca `read:packages` junto).
3. Gere e copie o token.

No servidor:

```bash
printf '%s' 'COLE-O-TOKEN-DO-GITHUB' | docker login ghcr.io -u SEU-USUARIO-GITHUB --password-stdin
```

Deve responder `Login Succeeded`.

---

## 10. O arquivo `.env` de produção

```bash
cd /opt/neurodoc
cp .env.example .env
nano .env
```

O `.env.example` é a **base**, versionada, com todas as chaves. O `.env`
fica só nesta máquina e **sobrescreve** o que você mudar. O deploy recusa
qualquer chave que exista só no `.env` — chave nova entra primeiro no
exemplo, onde aparece num diff.

**O e-mail já vem configurado** no `.env.example`, com a conta desta
instalação na Hostinger — você não precisa mexer em nada disso:

```
EMAIL_ENABLED=True
EMAIL_HOST=smtp.hostinger.com
EMAIL_PORT=465
EMAIL_HOST_USER=contato@neurodoc.app.br
EMAIL_USE_TLS=False
EMAIL_USE_SSL=True
DEFAULT_FROM_EMAIL=contato@neurodoc.app.br
LEADS_EMAIL=contato@neurodoc.app.br
ALERT_ADMIN_EMAILS=contato@neurodoc.app.br
```

A **senha** dessa caixa não fica aqui: ela é o segredo
`NEURODOC_SMTP_PASSWORD`, criado no passo 7.2. Arquivo de configuração
entra no Git; segredo do Docker, não.

`imap.hostinger.com` e `pop.hostinger.com` não aparecem em lugar nenhum
porque o sistema **só envia** e-mail — ele nunca lê caixa de entrada.
Esses dois servidores servem para você ler `contato@neurodoc.app.br` no
celular ou no webmail, e não têm nada a ver com o servidor.

Altere estas linhas:

```
REGISTRY=ghcr.io/ffreua/neurodoc
SMS_ENABLED=True
AI_ENABLED=True
BACKUP_AGE_RECIPIENT=<ver passo 15; deixe CHANGE_ME por ora>
```

`REGISTRY` já aponta para `ghcr.io/ffreua/neurodoc`. Confira que é o seu
usuário do GitHub: é para lá que a imagem é enviada, e você precisa ter
permissão de escrita.

**Deixe como está**, por enquanto:

```
ACME_DIRECTORY=https://acme-staging-v02.api.letsencrypt.org/directory
NEURODOC_RELEASE_APPROVED=False
SECURE_HSTS_SECONDS=0
```

Os três mudam adiante, em momentos específicos. O de certificado aponta
para o **ambiente de teste** da Let's Encrypt de propósito: o ambiente de
verdade bloqueia o domínio por uma semana depois de cinco falhas seguidas,
e a primeira tentativa de alguém raramente acerta de primeira.

Salve: `Ctrl+O`, `Enter`, `Ctrl+X`.

---

## 11. Registrar a homologação

O deploy recusa publicar sem um registro dizendo que aquela versão foi
conferida. É uma trava deliberada contra publicar de madrugada sem ter
olhado nada.

```bash
cd /opt/neurodoc
git rev-parse HEAD          # anote o SHA
cp docs/releases/TEMPLATE.md docs/releases/$(git rev-parse HEAD).md
nano docs/releases/$(git rev-parse HEAD).md
```

Preencha o que o modelo pede e salve. Depois, no `.env`:

```
NEURODOC_RELEASE_APPROVED=True
```

---

## 12. Conferir antes de publicar

```bash
cd /opt/neurodoc
.venv-ops/bin/python -m ops.deploy --check
```

Ele roda **toda** a verificação e para antes de construir ou publicar
qualquer coisa. Resposta esperada:

```
Preflight aprovado: configuracao, Swarm, redes, secrets, tmpfs e
repositorio estao como o deploy exige.
```

Se der erro, a mensagem diz exatamente o que falta. Os mais comuns:

| Mensagem | O que fazer |
| --- | --- |
| `Configure the ACME account email` | Passo 10: `ACME_EMAIL` ainda é `CHANGE_ME` |
| `Release homologation has not been recorded` | Passo 11 |
| `The persistent-data node label is missing` | Passo 6.2 |
| `Invalid network isolation` | Passo 6.3, rede criada sem `--internal` |
| `Signing session keys must reside on tmpfs` | Passo 6.4 |
| `docker secret inspect` falhou | Passo 7, falta um segredo |
| `Commit or resolve tracked changes` | `git status` e resolva |

---

## 13. Publicar

```bash
cd /opt/neurodoc
.venv-ops/bin/python -m ops.deploy
```

Ele vai, nesta ordem: puxar o código, construir a imagem, publicá-la no
registry, criar os volumes, escrever a configuração do Traefik, subir o
stack e **esperar cada serviço ficar saudável**. Leva de 10 a 25 minutos
na primeira vez (a construção da imagem é o mais demorado).

Acompanhe, se quiser, de outro terminal:

```bash
watch docker service ls
```

Quando terminar sem erro, teste:

```bash
curl -k -I https://neurodoc.app.br
```

Deve responder `HTTP/2 200`. O `-k` está aí porque o certificado ainda é
o de teste — o navegador vai reclamar dele, e está certo.

### Se algo falhar

```bash
docker service ps neurodoc_v1_app --no-trunc     # o que aconteceu
docker service logs neurodoc_v1_app --tail 100   # por quê
```

O deploy tem volta automática: se uma versão nova não ficar saudável, o
Swarm volta para a anterior sozinho.

---

## 14. Trocar para o certificado de verdade

Só depois de o passo 13 ter funcionado e o site responder.

```bash
cd /opt/neurodoc
nano .env
```

Troque:

```
ACME_DIRECTORY=https://acme-v02.api.letsencrypt.org/directory
```

Publique de novo:

```bash
.venv-ops/bin/python -m ops.deploy
```

Aguarde uns dois minutos e abra `https://neurodoc.app.br` no navegador.
Agora tem de aparecer o **cadeado**, sem aviso nenhum.

> O sistema guarda os dois certificados em arquivos separados
> (`acme-staging.json` e `acme.json`), então trocar não apaga o de teste
> nem confunde um com o outro.

---

## 15. Depois de no ar

### 15.1 Sua conta de superadministrador

```bash
cd /opt/neurodoc
docker exec $(docker ps -q -f name=neurodoc_v1_app | head -1) \
  python manage.py create_superadmin seu@email.com \
  --first-name Fernando --last-name Freua --invite
```

Ele imprime um link de definição de senha, de uso único. Abra, defina a
senha, e **em seguida configure a MFA** em `/accounts/mfa/setup/` — o
console `/instalacao/` não abre sem ela. É deliberado: um console que lê a
trilha de todas as clínicas não pode estar a uma senha roubada de
distância.

### 15.2 Encher a tabela TUSS

O CID-10 é importado sozinho na primeira subida (14.233 códigos). A TUSS
vem de uma API externa, e **só o worker alcança a internet**:

```bash
docker exec $(docker ps -q -f name=neurodoc_v1_celery_worker | head -1) \
  python manage.py sync_tuss
```

Leva alguns minutos. Depois disso ela se atualiza sozinha, aos domingos às
4h.

### 15.3 Ligar o HSTS

HSTS diz ao navegador "deste domínio, nunca mais aceite HTTP". O navegador
**guarda** isso — por isso só se liga depois que o HTTPS provou funcionar.

Confirme que `https://neurodoc.app.br` abre com cadeado, e então:

```bash
nano .env      # SECURE_HSTS_SECONDS=31536000
.venv-ops/bin/python -m ops.deploy
```

### 15.4 Backups

O repositório traz as unidades do systemd:

```bash
sudo cp ops/neurodoc-backup.service ops/neurodoc-backup.timer /etc/systemd/system/
sudo cp ops/neurodoc-signing-cleanup.service ops/neurodoc-signing-cleanup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now neurodoc-backup.timer neurodoc-signing-cleanup.timer
systemctl list-timers | grep neurodoc
```

**Além disso, guarde os segredos fora do servidor.** Um backup do banco
sem as chaves-mestras é um backup que não abre:

```bash
docker secret ls --format '{{.Name}}'
```

Os valores não podem ser lidos de volta do Docker — anote-os no momento em
que os criou (passo 7), num gerenciador de senhas. Se não anotou, apague e
recrie os segredos **antes** de ter dados de verdade no sistema.

### 15.5 Conferir o e-mail

```bash
docker exec $(docker ps -q -f name=neurodoc_v1_app | head -1) \
  python manage.py testar_email seu@email.com
```

Ele imprime a configuração antes de tentar. Confira estas linhas:

```
  servidor ............ smtp.hostinger.com:465
  TLS (STARTTLS) ...... False
  SSL implicito ....... True
  cifragem em uso ..... SSL implicito
  usuário ............. contato@neurodoc.app.br
  remetente ........... contato@neurodoc.app.br
```

E depois `1 mensagem(ns) enfileirada(s) para o worker`. A entrega é do
worker, então a mensagem chega alguns segundos depois. Se não chegar:

```bash
docker service logs neurodoc_v1_celery_worker --tail 50
```

Os três erros que aparecem aí, e o que cada um quer dizer:

| No log | Causa | O que fazer |
| --- | --- | --- |
| `authentication failed` | senha errada no segredo | Troque a senha (receita abaixo) |
| `sender ... not allowed` / `not owned` | o `From` não é a caixa autenticada | `DEFAULT_FROM_EMAIL` tem de ser `contato@neurodoc.app.br` |
| a tarefa fica repetindo, sem erro claro | cifragem trocada para a porta | `EMAIL_PORT=465` exige `EMAIL_USE_SSL=True` e `EMAIL_USE_TLS=False` |

### 15.6 Trocar a senha do e-mail

Um segredo do Docker é **imutável**: não existe "editar". Trocar é apagar
e criar de novo — e o Docker **recusa apagar um segredo que algum serviço
está usando**. Por isso a ordem abaixo tem quatro passos, e pular o
primeiro devolve `secret is in use by the following service`.

```bash
cd /opt/neurodoc

# 1. Solta o segredo do worker (ele reinicia sem a senha; o e-mail para
#    de sair por alguns segundos, e nada se perde — a fila segura).
docker service update --secret-rm NEURODOC_SMTP_PASSWORD neurodoc_v1_celery_worker

# 2. Agora o Docker deixa apagar.
docker secret rm NEURODOC_SMTP_PASSWORD

# 3. Cria de novo, com a senha nova.
printf '%s' 'NOVA-SENHA-DO-EMAIL' | docker secret create NEURODOC_SMTP_PASSWORD -

# 4. Republica: o stack reata o segredo ao worker, como está no
#    docker-stack.yml. --skip-build reaproveita a imagem já publicada.
.venv-ops/bin/python -m ops.deploy --skip-build
```

Confira com `manage.py testar_email` (passo 15.5).

> **Por que o passo 4 e não `docker service update --force`.** Segredo do
> Docker é entregue ao contêiner quando ele nasce, então forçar a troca
> faria o worker renascer — mas sem o segredo, que o passo 1 desatou. Só o
> `stack deploy` reata o que está declarado no `docker-stack.yml`.

---

## 16. Publicar uma atualização

Depois que tudo estiver no ar, atualizar é isto:

```bash
cd /opt/neurodoc
git rev-parse HEAD                                    # anote o SHA novo
cp docs/releases/TEMPLATE.md docs/releases/<SHA>.md   # registre a homologação
nano docs/releases/<SHA>.md
git add docs/releases/ && git commit -m "Registro da release <SHA>"
.venv-ops/bin/python -m ops.deploy --check            # confira
.venv-ops/bin/python -m ops.deploy                    # publique
```

O que acontece por baixo:

- as duas réplicas da aplicação são trocadas **uma de cada vez**, a nova
  subindo antes de a antiga sair — ninguém vê o site fora do ar;
- as migrações de banco rodam sob trava, uma vez só, mesmo com duas
  réplicas subindo juntas;
- se a versão nova não ficar saudável, o Swarm **volta sozinho** para a
  anterior.

Mudança de banco que apaga coluna exige procedimento de manutenção: o
preflight recusa enquanto `NEURODOC_SCHEMA_CHANGE` não for `expand`. É
proposital — apagar coluna com a versão antiga ainda rodando derruba o
site.

### Voltar atrás de propósito

```bash
docker service rollback neurodoc_v1_app
```

Ver também `docs/operations/rollback.md`.

---

## Resumo dos comandos do dia a dia

| Para quê | Comando |
| --- | --- |
| Ver se está tudo de pé | `docker service ls` |
| Ver o que houve com um serviço | `docker service ps neurodoc_v1_app --no-trunc` |
| Ler o log | `docker service logs neurodoc_v1_app --tail 100 -f` |
| Publicar atualização | `.venv-ops/bin/python -m ops.deploy` |
| Conferir sem publicar | `.venv-ops/bin/python -m ops.deploy --check` |
| Voltar atrás | `docker service rollback neurodoc_v1_app` |
| Testar e-mail | `manage.py testar_email <endereço>` |
| Atualizar a TUSS | `manage.py sync_tuss` (no worker) |
