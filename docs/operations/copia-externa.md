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

### 1. Dar leitura ao usuário que faz SSH

`/srv/neurodoc-backups` é `0700` do usuário `neurodocops`, e o SSH entra
como `deploy`. Sem isto o `scp` devolve "Permission denied" e nada mais.

Na VPS, uma vez:

```bash
sudo usermod -aG neurodocops deploy
sudo chmod 0750 /srv/neurodoc-backups
sudo find /srv/neurodoc-backups -mindepth 1 -maxdepth 1 -type d -exec chmod 0750 {} +
sudo find /srv/neurodoc-backups -type f -exec chmod 0640 {} +
```

E para que os backups **futuros** nasçam legíveis pelo grupo, o
`UMask=0077` de `ops/neurodoc-backup.service` precisa virar `0027`:

```bash
sudo sed -i 's/^UMask=0077$/UMask=0027/' /etc/systemd/system/neurodoc-backup.service
sudo systemctl daemon-reload
```

**O que isto afrouxa, e o que não.** Passa de "só `neurodocops` lê" para
"`neurodocops` e o grupo leem". Continua fechado para qualquer outro
usuário, e o conteúdo segue cifrado com `age` — quem lê o arquivo sem a
chave privada lê ruído. A alternativa, entrar como `neurodocops` por SSH,
daria ao PC um acesso mais poderoso que o necessário.

Conferir que funcionou, do PC:

```powershell
ssh deploy@23.106.44.46 "ls /srv/neurodoc-backups | head"
```

### 2. Chave SSH sem senha para a tarefa agendada

A tarefa roda sem ninguém olhando; uma chave com passphrase a trava para
sempre, em silêncio. Se a chave atual tem passphrase, gere uma dedicada a
este uso (`ssh-keygen -t ed25519 -f ~/.ssh/neurodoc_backup`) e registre-a
em `~/.ssh/authorized_keys` do `deploy`.

## A execução

```powershell
.\scripts\puxar_backups.ps1 -Destino E:\neurodoc-backups
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
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\ferna\projects\neurodoc\scripts\puxar_backups.ps1" -Destino E:\neurodoc-backups'
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

## Conferir que está funcionando

Um backup que ninguém olha não é backup. Uma vez por mês:

```powershell
Get-Content E:\neurodoc-backups\puxar_backups.log -Tail 20
(Get-ChildItem E:\neurodoc-backups -Directory | Where-Object { Test-Path "$($_.FullName)\VERIFICADO" }).Count
```

## O que isto ainda não cobre

O SSD, o PC e a chave privada ficam **na mesma sala**. Incêndio, roubo ou
enchente levam os três. Fechar isso é uma terceira perna em storage
externo (~4,6 MB/dia é centavos), com chave **só de escrita** e *object
lock*, preservando a propriedade de não poder ser apagada de dentro da
VPS. Fica registrado aqui como o próximo passo, não como feito.

E a regra que não muda: **refazer a prova de restauração depois de
qualquer mudança no `BACKUP_AGE_RECIPIENT`** (`docs/operations/restore.md`).
