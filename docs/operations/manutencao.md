# Manutenção do dia a dia — o que fazer em cada situação

Escrito para ser seguido sem saber administrar servidor. Cada situação tem
**o que fazer**, **como saber se deu certo** e **o que fazer se não der**.

> **Regra de ouro:** comando que apaga (`rm`, `shred`, `docker volume rm`)
> **nunca** vai colado no que copia. Copie, confira que chegou, e só então
> apague. Foi assim que a primeira chave de backup se perdeu.

**Como entrar no servidor.** Abra o PowerShell e digite:

```
ssh neurodoc-vps
```

`neurodoc-vps` é um **apelido** definido no `~/.ssh/config` desta máquina
(`C:\Users\<você>\.ssh\config` no Windows) — o endereço do servidor mora
lá, e não no repositório, que é público. Numa máquina nova, crie o arquivo:

```
Host neurodoc-vps
    HostName <IP-da-VPS>
    User deploy
    IdentityFile ~/.ssh/id_ed25519
```

A cópia diária do backup (`scripts/puxar_backups.ps1`) usa o mesmo
apelido: sem ele, ela para de puxar.

Você fica lá dentro até digitar `exit`. Onde aparecer `cd /srv/neurodoc`,
é porque o comando só funciona nessa pasta.

---

## 1. Toda semana: o sistema está de pé?

```
ssh neurodoc-vps "docker service ls"
```

**Certo:** sete linhas, e a coluna `REPLICAS` com `2/2` no `app` e `1/1`
nos outros seis. Os dois números de cada par iguais.

**Errado:** algum `0/1`. Veja o que houve:

```
ssh neurodoc-vps "docker service ps neurodoc_v1_app --no-trunc"
ssh neurodoc-vps "docker service logs neurodoc_v1_app --tail 100"
```

Troque `app` pelo serviço com problema. Copie a saída e peça ajuda — ela
diz a causa.

---

## 2. Toda semana: o backup rodou?

```
ssh neurodoc-vps "ls -1 /srv/neurodoc-backups/ | tail -3"
```

**Certo:** a pasta mais recente é de hoje ou de ontem. O nome é a data em
UTC (`20260926T060116Z` = 26/09 às 03:01 no horário do Brasil).

**Errado:** a mais recente tem vários dias. Veja o porquê:

```
ssh neurodoc-vps "journalctl -u neurodoc-backup.service -n 30 --no-pager"
```

Para rodar um backup agora, sem esperar a madrugada:

```
ssh neurodoc-vps "sudo systemctl start neurodoc-backup.service"
```

### 2.1 Levar uma cópia para fora do servidor

Backup que só existe no servidor não protege contra perder o servidor.
Uma vez por mês, no PowerShell:

```
cd $env:USERPROFILE\Documents
mkdir -Force backups-neurodoc
cd backups-neurodoc
scp -r neurodoc-vps:/srv/neurodoc-backups/* .
```

Depois copie essa pasta para um HD externo ou nuvem.

**Nunca guarde a `CHAVE-BACKUP.key` no mesmo lugar dos backups.** Quem
pegar os dois juntos tem o prontuário inteiro. A chave num gerenciador de
senhas, os backups noutro lugar.

---

## 3. Restaurar um backup (o procedimento completo)

Faça isto **de verdade a cada seis meses**, mesmo sem precisar. Backup que
nunca foi restaurado não é backup: é um arquivo que você espera que
funcione.

Precisa: seu PC com Docker, a pasta do backup e a `CHAVE-BACKUP.key`.

### Passo 1 — Preparar o Docker (uma vez por teste)

```
docker swarm init
docker node update --label-add neurodoc_data=true $(docker node ls -q)
docker network create --driver overlay --internal neurodoc_v1_internal
```

### Passo 2 — Criar as três senhas de banco

**Não precisam ser as de produção.** O banco da recuperação nasce do zero
com elas, e o backup não carrega senha de usuário de banco. Cole as três
linhas:

```
openssl rand -base64 48 | tr -d "\r\n" | docker secret create NEURODOC_DB_ADMIN_PASSWORD -
openssl rand -base64 48 | tr -d "\r\n" | docker secret create NEURODOC_DB_OWNER_PASSWORD -
openssl rand -base64 48 | tr -d "\r\n" | docker secret create NEURODOC_DB_APP_PASSWORD -
```

### Passo 3 — Entrar no registry de imagens

```
docker login ghcr.io -u ffreua
```

Ele pede a senha: cole o **token do GitHub**, não a senha da conta.

### Passo 4 — Restaurar

```
cd $env:USERPROFILE\projects\neurodoc
python -m ops.restore --prepare-data --backup-dir "CAMINHO\DA\PASTA\DO\BACKUP" --identity "$env:USERPROFILE\Documents\CHAVE-BACKUP.key"
```

**Certo:** `Data restored on isolated host; activation and clinical checks
remain pending.`

**Errado — `Command failed: docker service (exit 1)`:** faltou algo dos
passos 1 a 3. É a mensagem que aparece para qualquer pré-condição ausente,
porque o restaurador esconde a saída dos comandos de propósito (ela pode
conter dado de paciente).

### Passo 5 — Conferir o que voltou

```
docker run -d --name leitura -e POSTGRES_PASSWORD=x -v neurodoc_v1_postgres:/var/lib/postgresql/data postgres:17.11-bookworm
```

Espere uns 20 segundos e rode:

```
docker exec leitura psql -U postgres -d neurodoc -tAc "select 'pacientes: ' || count(*) from patients_patient union all select 'atendimentos: ' || count(*) from clinical_encounter"
```

Os números têm que bater com o que havia no dia do backup. **Este passo é
o teste.** Sem ele você provou que o arquivo abre, não que os dados estão
lá.

### Passo 6 — Limpar (importante)

Os dados restaurados são prontuário de verdade. **Não deixe no seu PC.**

```
docker rm -f leitura
docker volume rm neurodoc_v1_postgres neurodoc_v1_media neurodoc_v1_signing neurodoc_v1_letsencrypt
docker secret rm NEURODOC_DB_ADMIN_PASSWORD NEURODOC_DB_OWNER_PASSWORD NEURODOC_DB_APP_PASSWORD
docker network rm neurodoc_v1_internal
docker swarm leave --force
```

---

## 4. Publicar uma atualização

**Antes, no seu computador**, com a versão fechada e commitada:

```
git push origin main
```

**Depois, no servidor:**

```
ssh neurodoc-vps
cd /srv/neurodoc
git pull
bash scripts/deploy.sh --check
bash scripts/deploy.sh
```

**O build roda no servidor, não no seu computador.** Não é preciso subir a
pilha local para publicar — ela serve para rodar os roteiros de
verificação, e nada mais.

A nota de versão em `docs/releases/` entra junto com o código, **antes** do
push, e é nomeada pela versão (`1.1-SEGUIMENTO.md`) e não pelo SHA. Nomear
pelo SHA tem um problema circular: o commit que cria o arquivo muda o SHA
que o arquivo nomeia. O `deploy.sh` não exige o arquivo — ele é registro,
não requisito.

O `--check` confere sem publicar nada. **Só rode o de baixo se o de cima
aprovar.** A publicação leva de 10 a 25 minutos e não derruba o site: as
duas réplicas trocam uma de cada vez, a nova subindo antes de a antiga
sair.

**Se der errado:** o Swarm volta sozinho para a versão anterior. Para
forçar a volta:

```
docker service rollback neurodoc_v1_app
```

**Nunca rode `manage.py migrate` à mão.** A conexão padrão é o usuário da
aplicação, sem permissão de criar tabela — dá `permission denied for
schema public`. Quem migra é o próprio contêiner na subida, sob trava.

---

## 5. Trocar senhas e chaves

Segredo do Docker é **imutável**: não existe editar. Trocar é soltar do
serviço, apagar, criar de novo e republicar — nessa ordem. Pular o
primeiro passo devolve `secret is in use by the following service`.

### Senha do e-mail

```
ssh neurodoc-vps
cd /srv/neurodoc
docker service update --secret-rm NEURODOC_SMTP_PASSWORD neurodoc_v1_celery_worker
docker secret rm NEURODOC_SMTP_PASSWORD
printf '%s' 'SENHA-NOVA' | docker secret create NEURODOC_SMTP_PASSWORD -
bash scripts/deploy.sh --skip-build
```

Confira com:

```
docker exec $(docker ps -q -f name=neurodoc_v1_celery_worker | head -1) python manage.py testar_email SEU@EMAIL
```

### Token do GitHub

São **dois lugares**, e esquecer o segundo quebra o próximo deploy:

```
ssh neurodoc-vps
printf 'https://ffreua:TOKEN-NOVO@github.com\n' > ~/.git-credentials
printf '%s' 'TOKEN-NOVO' | docker login ghcr.io -u ffreua --password-stdin
```

### Token da Cloudflare

**Este eu não trocaria sem motivo.** Ele renova o certificado HTTPS a cada
60 dias. Se você trocar e esquecer de atualizar aqui, o site fica sem
certificado daqui a dois meses — e a falha não avisa na hora de trocar,
avisa quando o certificado vence.

```
ssh neurodoc-vps
cd /srv/neurodoc
docker service update --secret-rm CLOUDFLARE_DNS_API_TOKEN neurodoc_v1_traefik
docker secret rm CLOUDFLARE_DNS_API_TOKEN
printf '%s' 'TOKEN-NOVO' | docker secret create CLOUDFLARE_DNS_API_TOKEN -
bash scripts/deploy.sh --skip-build
```

### As duas chaves-mestras

**Não troque.** `NEURODOC_PFX_MASTER_KEY` e `NEURODOC_SECRETS_MASTER_KEY`
cifram os certificados de assinatura digital e as credenciais que as
clínicas digitam no sistema. Trocá-las torna ilegível tudo o que elas já
cifraram, sem recuperação. Se um dia for mesmo necessário, é procedimento
de migração — decifrar com a antiga e recifrar com a nova —, não uma troca
de segredo.

---

## 6. Situações específicas

### O navegador reclama do certificado HTTPS

```
ssh neurodoc-vps "docker service logs neurodoc_v1_traefik --tail 50 | grep -i acme"
```

Quase sempre é o token da Cloudflare vencido ou revogado. Recrie-o (§5) e
republique.

### A TUSS está vazia

```
ssh neurodoc-vps "docker exec \$(docker ps -q -f name=neurodoc_v1_celery_worker | head -1) python manage.py sync_tuss"
```

Se der `ReadTimeout`, é o servidor da ANS fora do ar — não é problema
nosso. Tente noutro dia; o timer refaz sozinho aos domingos às 4h.

### Atualizar a lista de medicamentos (CMED)

A Anvisa publica listas novas periodicamente. Confira antes, sem gravar:

```
ssh neurodoc-vps "docker exec \$(docker ps -q -f name=neurodoc_v1_celery_worker | head -1) python manage.py import_cmed --dry-run"
```

Se o número de apresentações fizer sentido, rode de novo sem `--dry-run`.

### O disco está enchendo

```
ssh neurodoc-vps "df -h /; docker system df"
```

Para limpar imagens antigas (não toca em dado nenhum):

```
ssh neurodoc-vps "docker image prune -af --filter until=720h"
```

### Ligar o HSTS (uma vez só, e sem volta)

Só depois de semanas com o cadeado funcionando sem aviso. O navegador
guarda a instrução por um ano e **não há como desfazer pelo servidor**.

```
ssh neurodoc-vps
cd /srv/neurodoc
sed -i 's/^SECURE_HSTS_SECONDS=.*/SECURE_HSTS_SECONDS=31536000/' .env
bash scripts/deploy.sh --skip-build
```

---

## 7. Calendário

| Quando | O quê |
| --- | --- |
| **Toda semana** | §1 serviços de pé · §2 backup rodou |
| **Todo mês** | §2.1 cópia do backup para fora do servidor |
| **A cada 6 meses** | §3 restaurar de verdade e conferir os números |
| **A cada 90 dias** | Trocar o token do GitHub (§5) — ele vence sozinho |
| **Quando lembrar** | §6 conferir o disco e atualizar a CMED |

---

## 8. Quando pedir ajuda

Copie **a saída inteira** do comando que falhou. A mensagem de erro é o
diagnóstico; descrevê-la com as próprias palavras perde exatamente a
informação que resolve.

Se o site estiver fora do ar e você precisar de uma ação só, é esta — ela
volta para a versão anterior, que funcionava:

```
ssh neurodoc-vps "docker service rollback neurodoc_v1_app"
```
