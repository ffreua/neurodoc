# Cópia externa do backup (P-10)

O backup diário funciona e já foi provado: em 02/10/2026 o conjunto de
01/10 foi decifrado e conferido — dump Postgres válido, 86 tabelas. O que
faltava, e que esta página resolve, é que **as nove cópias moram na mesma
máquina que elas protegem**. Disco que falha, ou VPS comprometida, leva o
backup junto.

A última linha que `ops/backup.py` imprime é, literalmente,
`copy off-host and verify restore`.

## A decisão: puxar, nunca empurrar

| | Empurrar (VPS → destino) | **Puxar (PC → VPS)** |
| --- | --- | --- |
| Credencial do destino | fica **na VPS** | fica só no PC |
| VPS invadida | o invasor apaga a cópia externa | não alcança o disco |
| Precisa de máquina ligada | não | sim |

Quem invade a VPS encontra a credencial que ela usa para empurrar e apaga
as cópias de fora — é assim que ransomware destrói backup. Puxando, a VPS
não tem credencial nenhuma do disco: **ela não sabe que o disco existe.**

O custo é que o PC precisa estar ligado e o SSD plugado na hora. Isso é
barato aqui: a VPS guarda os conjuntos por `BACKUP_RETENTION_DAYS` (30 no
`.env.example`; `ops/backup.py` recusa menos de 7), então qualquer execução
dentro desse prazo pega tudo. Perder um dia não perde nada. (Esta linha
dizia "9 dias": era quantos backups existiam em 2026-10-02, uma semana
depois do primeiro, e não o prazo de guarda.)

**A chave privada não é usada neste caminho**, de propósito. O PC guarda
cópia cifrada, e só. Decifrar é `docs/operations/restore.md`.

## Antes da primeira execução

### 1. Permissão: nada a fazer

Conferido na VPS em 2026-10-02: `/srv/neurodoc-backups` é `0700` **do
próprio usuário de operação** (`<usuario>` daqui em diante), que é quem
roda a unidade de backup e quem entra por SSH. O acesso de leitura já
existe.

Vale registrar porque a versão anterior desta página mandava pôr
`<usuario>` no grupo `neurodocops` e afrouxar o diretório para `0750` —
lido do molde `ops/neurodoc-backup.service` (que diz `User=neurodocops`) em
vez do servidor real, onde `setup_deploy.sh` substituiu o usuário pelo de
operação. Seria afrouxar permissão à toa.

Conferir, do PC:

```powershell
ssh neurodoc-vps "ls /srv/neurodoc-backups | head"
```

### 2. Chave SSH sem senha para a tarefa agendada

A tarefa roda sem ninguém olhando; uma chave com passphrase a trava para
sempre, em silêncio. Se a chave atual tem passphrase, gere uma dedicada a
este uso (`ssh-keygen -t ed25519 -f ~/.ssh/neurodoc_backup`) e registre-a
em `~/.ssh/authorized_keys` do `<usuario>`.

## A execução

```powershell
.\scripts\puxar_backups.ps1 -Destino D:\neurodoc-backups
```

O que ele faz, em ordem: **recusa rodar se o disco não estiver montado**
(senão encheria o `C:` em silêncio, com o operador achando que a cópia foi
para o SSD) → lista na VPS só as pastas que têm `COMPLETE` → baixa para um
nome `.parcial` → **confere o SHA-256 e o tamanho de cada arquivo contra o
`manifest.json`** → só então renomeia e escreve `VERIFICADO`.

É o `VERIFICADO`, e não a existência da pasta, que diz que aquela cópia
presta. Cópia que não confere é descartada e contada como falha; o script
sai com código 1 se houve qualquer uma.

**Códigos de saída:** 0 tudo certo; 1 alguma cópia falhou ou não conferiu
com o manifesto; 2 o disco não está montado e nada foi copiado. Até
2026-11-18 o disco ausente também saía com 1 — o `Write-Error` sob
`ErrorActionPreference = Stop` encerrava o script antes do `exit 2` —, e no
agendador "SSD fora da tomada" ficava igual a backup que não confere. Em
2026-11-17 a tarefa saiu com 1 e o `D:` não estava montado.

**O buraco que isso escondeu (visto em 2026-11-18).** A última cópia no SSD
era de 08/10: quarenta dias sem cópia externa, com a tarefa falhando todo
dia e ninguém olhando. Como a VPS guarda 30 dias, os backups de 09/10 a
~17/10 já não existem em lugar nenhum. Com o SSD plugado, a tarefa trouxe
os 32 que faltavam (49 no disco). A conferência mensal da seção abaixo é
o que pega isso — e o código 2 agora separa "plugue o SSD" de defeito.

Retenção local: 60 pastas por padrão (`-Manter`), e **só apaga pasta
verificada** — "abrir espaço" jogando fora uma cópia suspeita esconderia
exatamente o problema que interessa ver.

Registro em `<Destino>\puxar_backups.log`.

## Agendar

```powershell
$acao = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\ferna\projects\neurodoc\scripts\puxar_backups.ps1" -Destino D:\neurodoc-backups'
$gatilho = New-ScheduledTaskTrigger -Daily -At 09:00
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'NeuroDoc - puxar backups' `
  -Action $acao -Trigger $gatilho -Settings $config -Description 'Copia os backups da VPS para o SSD externo'
```

`-StartWhenAvailable` é o que importa: PC desligado às 09:00 roda assim
que liga, em vez de pular o dia.

Às 09:00 porque o backup da VPS é às 03:00 (hora de Brasília): quando a
tarefa roda, o do dia já existe.

## Executado em 2026-10-02

Não é mais um plano. Os **11 conjuntos** da VPS estão em
`D:\neurodoc-backups` (SSD `SSD_Freua`, 57,8 MB), de 26/09 a 02/10, todos
com `VERIFICADO`. A tarefa diária está registrada e **foi disparada à mão
para confirmar que roda sob o agendador** — resultado 0. Esse teste
importa mais que o manual: é no contexto do agendador que uma chave SSH
com passphrase, ou um caminho relativo, falharia calado.

**O que a primeira execução ensinou.** Duas das onze pastas falharam com
`scp: Connection closed` (código 255), sem padrão, e vieram inteiras na
execução seguinte — cada pasta é uma conexão SSH nova, e onze em três
minutos às vezes esbarram em limite do servidor. O script passou a tentar
**três vezes** com espera crescente. Vermelho semanal por soluço de rede é
vermelho que ninguém olha, e é assim que uma falha de verdade passa
despercebida.

## Conferir que está funcionando

Um backup que ninguém olha não é backup. Uma vez por mês:

```powershell
Get-Content D:\neurodoc-backups\puxar_backups.log -Tail 20
(Get-ChildItem D:\neurodoc-backups -Directory | Where-Object { Test-Path "$($_.FullName)\VERIFICADO" }).Count
```

## Cópia no Cloudflare R2 (2026-11-18): pronta, desligada até o contrato

O SSD, o PC e a chave privada ficam **na mesma sala**: incêndio, roubo ou
enchente levam os três. E o SSD só copia quando está plugado (em
2026-11-18 o NeuroDoc descobriu 40 dias sem cópia, com o disco
desconectado). Além disso, o servidor e os backups que ele guarda dependem
de **um fornecedor só**: perder a conta leva produção e backups juntos. A terceira perna é o **Cloudflare R2**, outra empresa, com cópia
automática todo dia.

**Estado:** o código está pronto (`ops/nuvem.py`, chamado pelo
`scripts/backup.sh` logo depois do backup; roteiro
`checks/check_copia_nuvem.py`), e **desligado**: `BACKUP_R2_*` vazios no
`.env`. Ligar depende do contrato de adesão descrever a cópia, porque o
contrato vigente diz "até 30 dias no servidor e até 60 dias em SSD" e
descreve a Cloudflare "sem armazenamento como serviço" — ver a minuta em
`docs/governance/` (NeuroDoc 2.4, ProntDoc 1.3).

**Como funciona.**

- Envia cada pasta de backup **completa** que ainda não tem a marca
  `NUVEM`, em ordem: os quatro arquivos cifrados, o `manifest.json` e o
  `COMPLETE` por último. Os arquivos já saem cifrados pelo `age`; nem a
  VPS nem o R2 têm a chave privada.
- Cada envio é assinado com o SHA-256 real do arquivo (o R2 recusa corpo
  diferente) e conferido depois pelo `ETag` (MD5 do que o R2 guardou).
  Só então a pasta ganha a marca `NUVEM`, sem mudar a data que a
  retenção do backup lê.
- O que falhou é reenviado na execução seguinte; o que já está lá não é
  reenviado. Objeto diferente já no R2, ou arquivo local que não confere
  com o manifesto, é **erro**, nunca "copiado".
- Falha sai com erro do `backup.service`, e o `OnFailure=` manda o mesmo
  e-mail do backup que falhou. O vigia (`vigiar_backup.py`) cobra a marca
  com menos de 26 horas quando a cópia está ligada.
- Biblioteca padrão do Python, sem `boto3` nem `rclone`.

**A trava é o que faz a cópia valer.** O balde tem *bucket lock*: objeto
gravado não pode ser apagado nem sobrescrito por 30 dias, nem com a chave
que a VPS guarda. Quem invadir a VPS consegue gravar, não destruir. Uma
regra de ciclo de vida apaga com 60 dias, o prazo que o contrato fixa para
as cópias externas.

### Ligar (depois do contrato publicado)

Na Cloudflare (uma vez, pelo titular):

1. **R2 Object Storage** → criar o balde `neurodoc-backups` (e, no
   ProntDoc, `prontdoc-backups` — **um balde e uma chave por sistema**, para
   uma VPS invadida não alcançar os backups da outra). Localização:
   América do Norte.
2. No balde, **Settings → Bucket lock rules**: regra para todos os objetos,
   **30 dias**.
3. **Settings → Object lifecycle rules**: apagar objetos com **60 dias**.
4. **Manage API tokens → Create API token**: permissão **Object Read &
   Write**, só para aquele balde. Guardar o *Access Key ID* e o *Secret
   Access Key* no gerenciador de senhas.

Na VPS:

```sh
install -d -m 700 ~/.config/neurodoc
install -m 600 /dev/null ~/.config/neurodoc/r2-backup.env
# editar o arquivo com as duas linhas:
#   R2_ACCESS_KEY_ID=...
#   R2_SECRET_ACCESS_KEY=...
# e no /srv/neurodoc/.env:
#   BACKUP_R2_ENDPOINT=https://<id da conta>.r2.cloudflarestorage.com
#   BACKUP_R2_BUCKET=neurodoc-backups
#   BACKUP_R2_CREDENTIALS=/home/deploy/.config/neurodoc/r2-backup.env
.venv-ops/bin/python -m ops.nuvem enviar   # primeira cópia (todo o acervo local)
.venv-ops/bin/python -m ops.nuvem listar
```

(No ProntDoc, troque `neurodoc` por `prontdoc` nos caminhos e no balde; o
ProntDoc recusa balde que mencione o NeuroDoc, e vice-versa.)

### Restaurar a partir do R2

Numa VPS (a de produção ou uma nova, com o repositório, o `.env` e o
arquivo de credenciais):

```sh
.venv-ops/bin/python -m ops.nuvem listar
.venv-ops/bin/python -m ops.nuvem baixar 20261118T060155Z-31b5a4b2 /tmp/restaurar
```

O `baixar` confere cada arquivo com o manifesto e só entrega a pasta
inteira. Daí em diante é o `docs/operations/restore.md`, com a chave
privada do `age`, que nunca vai para a VPS. Sem VPS nenhuma, o painel da
Cloudflare baixa os arquivos um a um.

E a regra que não muda: **refazer a prova de restauração depois de
qualquer mudança no `BACKUP_AGE_RECIPIENT`** (`docs/operations/restore.md`).
