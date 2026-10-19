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
barato aqui: a VPS guarda 9 dias, então qualquer execução dentro de 9 dias
pega tudo. Perder um dia não perde nada.

**A chave privada não é usada neste caminho**, de propósito. O PC guarda
cópia cifrada, e só. Decifrar é `docs/operations/restore.md`.

## Antes da primeira execução

### 1. Permissão: nada a fazer

Conferido na VPS em 2026-10-02: `/srv/neurodoc-backups` é `0700` **do
próprio `deploy`**, que é quem roda a unidade de backup e quem entra por
SSH. O acesso de leitura já existe.

Vale registrar porque a versão anterior desta página mandava rodar
`usermod -aG neurodocops deploy` e afrouxar o diretório para `0750` — lido
do molde `ops/neurodoc-backup.service` (que diz `User=neurodocops`) em vez
do servidor real, onde `setup_deploy.sh` substituiu o usuário por
`deploy`. Seria afrouxar permissão à toa.

Conferir, do PC:

```powershell
ssh neurodoc-vps "ls /srv/neurodoc-backups | head"
```

### 2. Chave SSH sem senha para a tarefa agendada

A tarefa roda sem ninguém olhando; uma chave com passphrase a trava para
sempre, em silêncio. Se a chave atual tem passphrase, gere uma dedicada a
este uso (`ssh-keygen -t ed25519 -f ~/.ssh/neurodoc_backup`) e registre-a
em `~/.ssh/authorized_keys` do `deploy`.

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
`D:
eurodoc-backups` (SSD `SSD_Freua`, 57,8 MB), de 26/09 a 02/10, todos
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

## O que isto ainda não cobre

O SSD, o PC e a chave privada ficam **na mesma sala**. Incêndio, roubo ou
enchente levam os três. Fechar isso é uma terceira perna em storage
externo (~4,6 MB/dia é centavos), com chave **só de escrita** e *object
lock*, preservando a propriedade de não poder ser apagada de dentro da
VPS. Fica registrado aqui como o próximo passo, não como feito.

E a regra que não muda: **refazer a prova de restauração depois de
qualquer mudança no `BACKUP_AGE_RECIPIENT`** (`docs/operations/restore.md`).
