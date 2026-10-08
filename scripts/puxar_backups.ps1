# Puxa os backups da VPS para um disco externo, a partir do PC do controlador.
#
# POR QUE PUXAR, E NAO EMPURRAR. Se a VPS empurrasse a copia para fora, ela
# precisaria de uma credencial do destino -- e quem invadisse a VPS usaria
# essa credencial para apagar tambem a copia de fora. E assim que ransomware
# destroi backup. Puxando, a VPS nao tem credencial nenhuma do disco: ela nao
# sabe que o disco existe. Invasao na VPS nao alcanca a copia.
#
# POR QUE VERIFICAR O SHA-256 AQUI. `scp` interrompido deixa arquivo parcial
# sem dizer nada, e um backup parcial so se descobre defeituoso na noite de
# restaurar -- a pior noite para descobrir. Cada pasta de backup traz um
# `manifest.json` com o hash de cada arquivo (`ops/backup.py`); conferir aqui
# transforma "copiei" em "copiei inteiro".
#
# POR QUE RECUSAR SE O DISCO NAO ESTIVER MONTADO. Sem isso o script criaria
# a pasta no disco do sistema e encheria o C: em silencio, enquanto o
# operador acreditaria que a copia esta no disco externo.
#
# O QUE ELE NAO FAZ: nao decifra nada. A chave privada nao e usada aqui, de
# proposito -- o PC guarda copia cifrada, e so. Para provar que o backup
# abre, veja `docs/operations/restore.md`.

[CmdletBinding()]
param(
    # Pasta no disco externo. O script RECUSA rodar se a raiz dela nao existir.
    [string]$Destino = 'D:\neurodoc-backups',

    # Como se chega na VPS. O usuario precisa conseguir LER
    # /srv/neurodoc-backups (ver docs/operations/copia-externa.md).
    [string]$Servidor = 'deploy@23.106.44.46',

    [string]$Origem = '/srv/neurodoc-backups',

    # Quantas pastas de backup manter no disco externo. Zero = nunca apagar.
    # O padrao guarda mais que a VPS (9 dias): o disco externo e o lugar onde
    # o historico pode ser mais longo, porque ninguem disputa o espaco.
    [int]$Manter = 60
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Registrar($texto) {
    $linha = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $texto
    Write-Host $linha
    if ($script:Log) { Add-Content -Path $script:Log -Value $linha -Encoding utf8 }
}

# --- 1. O disco esta mesmo plugado? ---------------------------------------
$raiz = [System.IO.Path]::GetPathRoot($Destino)
if (-not (Test-Path $raiz)) {
    Write-Error "O disco $raiz nao esta montado. Plugue o SSD e rode de novo. Nada foi copiado."
    exit 2
}
if (-not (Test-Path $Destino)) { New-Item -ItemType Directory -Path $Destino -Force | Out-Null }
$script:Log = Join-Path $Destino 'puxar_backups.log'
Registrar "=== inicio ($Servidor -> $Destino) ==="

# --- 2. Quais pastas a VPS tem, e quais estao COMPLETE? -------------------
# `COMPLETE` so e escrito quando o backup terminou inteiro (ops/backup.py).
# Pasta sem ele e backup em andamento ou abortado: copiar seria copiar lixo.
$remotas = & ssh -o BatchMode=yes -o ConnectTimeout=20 $Servidor `
    "find '$Origem' -mindepth 2 -maxdepth 2 -name COMPLETE -printf '%h\n' | xargs -r -n1 basename | sort"
if ($LASTEXITCODE -ne 0) {
    Registrar "ERRO: nao consegui listar a VPS (ssh saiu com $LASTEXITCODE)."
    exit 1
}
$remotas = @($remotas | Where-Object { $_ -match '^\d{8}T\d{6}Z-[a-f0-9]{8}$' })
if ($remotas.Count -eq 0) {
    Registrar 'ERRO: a VPS nao listou nenhum backup COMPLETE. Nao mexo em nada.'
    exit 1
}
Registrar "a VPS tem $($remotas.Count) backup(s) completo(s)."

# --- 3. Copiar o que ainda nao esta aqui ----------------------------------
$novos = 0; $falhos = 0
foreach ($pasta in $remotas) {
    $local = Join-Path $Destino $pasta
    if (Test-Path (Join-Path $local 'VERIFICADO')) { continue }

    # Baixa para um nome temporario: assim uma copia interrompida nunca
    # ocupa o nome definitivo, e a proxima execucao nao a confunde com
    # backup bom.
    $parcial = "$local.parcial"
    Registrar "copiando $pasta ..."

    # TENTA DE NOVO. Na primeira execucao real (02/10/2026), 2 das 11 pastas
    # falharam com `scp: Connection closed` (codigo 255) -- sem padrao, e as
    # duas vieram inteiras na execucao seguinte. Cada pasta e uma conexao SSH
    # nova, e onze em tres minutos as vezes esbarram em limite do servidor.
    #
    # Sem isto a tarefa agendada ficaria vermelha por soluco de rede, e
    # vermelho que aparece toda semana por nada e vermelho que ninguem olha
    # -- que e como uma falha de verdade passa despercebida.
    $copiou = $false
    for ($tentativa = 1; $tentativa -le 3 -and -not $copiou; $tentativa++) {
        if (Test-Path $parcial) { Remove-Item $parcial -Recurse -Force }
        & scp -q -o BatchMode=yes -o ConnectTimeout=20 -r "${Servidor}:${Origem}/${pasta}" $parcial
        if ($LASTEXITCODE -eq 0) { $copiou = $true; break }
        Registrar "  tentativa $tentativa falhou (scp saiu com $LASTEXITCODE)"
        if ($tentativa -lt 3) { Start-Sleep -Seconds (5 * $tentativa) }
    }
    if (-not $copiou) {
        Registrar "  FALHOU na copia apos 3 tentativas"
        if (Test-Path $parcial) { Remove-Item $parcial -Recurse -Force }
        $falhos++; continue
    }

    # --- 4. Conferir o manifesto ------------------------------------------
    $manifesto = Join-Path $parcial 'manifest.json'
    if (-not (Test-Path $manifesto)) {
        Registrar '  FALHOU: sem manifest.json'
        Remove-Item $parcial -Recurse -Force; $falhos++; continue
    }
    $dados = Get-Content $manifesto -Raw | ConvertFrom-Json
    $ruim = $false
    foreach ($nome in $dados.files.PSObject.Properties.Name) {
        $esperado = $dados.files.$nome
        $arquivo = Join-Path $parcial $nome
        if (-not (Test-Path $arquivo)) { Registrar "  FALTA $nome"; $ruim = $true; continue }
        $tamanho = (Get-Item $arquivo).Length
        if ($tamanho -ne $esperado.bytes) {
            Registrar "  TAMANHO ERRADO em $nome ($tamanho, esperava $($esperado.bytes))"
            $ruim = $true; continue
        }
        $hash = (Get-FileHash $arquivo -Algorithm SHA256).Hash.ToLower()
        if ($hash -ne $esperado.sha256.ToLower()) {
            Registrar "  HASH ERRADO em $nome"; $ruim = $true
        }
    }
    if ($ruim) {
        Registrar "  DESCARTADO $pasta (nao confere com o manifesto)"
        Remove-Item $parcial -Recurse -Force; $falhos++; continue
    }

    # `VERIFICADO` so e escrito depois de todo hash bater. E ele, e nao a
    # existencia da pasta, que diz que esta copia presta.
    Set-Content -Path (Join-Path $parcial 'VERIFICADO') -Value "ok`n" -Encoding utf8
    if (Test-Path $local) { Remove-Item $local -Recurse -Force }
    Rename-Item $parcial $local
    $n = $dados.files.PSObject.Properties.Name.Count
    Registrar "  ok $pasta ($n arquivo(s) conferido(s))"
    $novos++
}

# --- 5. Retencao local ----------------------------------------------------
# So apaga pasta VERIFICADA: uma copia que nunca passou na conferencia nao
# conta como copia, e apaga-la para "abrir espaco" esconderia o problema.
if ($Manter -gt 0) {
    $verificadas = @(Get-ChildItem $Destino -Directory |
        Where-Object { $_.Name -match '^\d{8}T\d{6}Z-[a-f0-9]{8}$' -and (Test-Path (Join-Path $_.FullName 'VERIFICADO')) } |
        Sort-Object Name -Descending)
    if ($verificadas.Count -gt $Manter) {
        foreach ($velha in $verificadas[$Manter..($verificadas.Count - 1)]) {
            Remove-Item $velha.FullName -Recurse -Force
            Registrar "removida (retencao $Manter): $($velha.Name)"
        }
    }
}

$total = @(Get-ChildItem $Destino -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'VERIFICADO') }).Count
Registrar "=== fim: $novos novo(s), $falhos falha(s), $total no disco ==="
if ($falhos -gt 0) { exit 1 }
exit 0
