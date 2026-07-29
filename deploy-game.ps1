param(
    # Nome do jogo (arquivo games/<nome>.env), ex: dragonwilds
    [string]$Game = "",
    # OU: App ID do servidor dedicado na Steam (deploy generico)
    [string]$AppId = "",
    # Modo interativo: pergunta cada valor (o .env vira apenas default dos prompts)
    [switch]$Interactive,
    [string]$ProxmoxHost = "",
    [string]$EnvFile = "",
    [string]$RemoteBundleDir = "/root/game-deploy"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Read-EnvFile([string]$Path) {
    $map = @{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1).Trim()
        # remove comentario inline e aspas
        $value = ($value -split '\s+#')[0].Trim().Trim('"').Trim("'")
        $map[$key] = $value
    }
    return $map
}

function Ask([string]$Label, [string]$Default) {
    if ($Default -ne "") {
        $answer = Read-Host "$Label [$Default]"
    } else {
        $answer = Read-Host "$Label"
    }
    if ($answer -eq "") { return $Default }
    return $answer
}

# ----- Selecao do jogo -----
if ($Game -eq "" -and $AppId -eq "") {
    $available = Get-ChildItem (Join-Path $ScriptDir "games") -Filter "*.env" |
        Where-Object { $_.Name -ne "_template.env" } |
        ForEach-Object { $_.BaseName }
    Write-Host "Informe -Game <nome> ou -AppId <steam_app_id>." -ForegroundColor Yellow
    Write-Host ("Jogos disponiveis: " + ($available -join ", "))
    exit 1
}

$GameEnvContent = $null
if ($Game -ne "") {
    $GameEnvPath = Join-Path $ScriptDir "games\$Game.env"
    if (-not (Test-Path $GameEnvPath)) {
        throw "Jogo desconhecido: $Game (esperado: $GameEnvPath)"
    }
    $GameEnvContent = Get-Content $GameEnvPath -Raw
} else {
    if ($AppId -notmatch '^\d+$') { throw "AppId invalido: $AppId" }
    Write-Host "Deploy generico do app Steam $AppId (script de start sera detectado automaticamente)"
    $GameEnvContent = @"
GAME_KEY=app$AppId
GAME_DISPLAY_NAME="Steam App $AppId"
STEAM_APP_ID=$AppId
START_SCRIPT=
START_ARGS=""
GAME_PORT=
GAME_PORTS=""
"@
}

# ----- Configuracao da infra (.env / interativo) -----
if ($EnvFile -eq "") { $EnvFile = Join-Path $ScriptDir ".env" }
$cfg = Read-EnvFile $EnvFile

if ($ProxmoxHost -eq "") {
    $ProxmoxHost = if ($cfg.ContainsKey("PROXMOX_HOST")) { $cfg["PROXMOX_HOST"] } else { "" }
}

if ($Interactive) {
    Write-Host "`n=== Modo interativo (Enter aceita o valor entre colchetes) ===`n" -ForegroundColor Cyan
    $ProxmoxHost            = Ask "Host Proxmox (ssh root)" $ProxmoxHost
    $cfg["CTID"]            = Ask "ID do container (CTID)" ($cfg["CTID"])
    $cfg["HOSTNAME_OVERRIDE"] = Ask "Hostname do CT (vazio = nome do jogo)" ($cfg["HOSTNAME_OVERRIDE"])
    $cfg["STORAGE"]         = Ask "Storage do rootfs" ($cfg["STORAGE"])
    $cfg["TEMPLATE_STORAGE"] = Ask "Storage de templates" ($cfg["TEMPLATE_STORAGE"])
    $cfg["BRIDGE"]          = Ask "Bridge de rede" ($cfg["BRIDGE"])
    $cfg["IP_CIDR"]         = Ask "IP/CIDR do CT (ou 'dhcp')" ($cfg["IP_CIDR"])
    if ($cfg["IP_CIDR"] -ne "dhcp") {
        $cfg["GATEWAY"]     = Ask "Gateway" ($cfg["GATEWAY"])
    }
    $cfg["MEMORY"]          = Ask "Memoria MB (vazio = recomendado do jogo)" ($cfg["MEMORY"])
    $cfg["CORES"]           = Ask "Cores (vazio = recomendado do jogo)" ($cfg["CORES"])
    $cfg["ROOTFS_SIZE_GB"]  = Ask "Disco GB (vazio = recomendado do jogo)" ($cfg["ROOTFS_SIZE_GB"])
    $cfg["CT_PASSWORD"]     = Ask "Senha root do CT" ($cfg["CT_PASSWORD"])
    $cfg["RECREATE_CT"]     = Ask "Recriar CT se existir? (0/1)" ($cfg["RECREATE_CT"] ?? "0")
} else {
    if (-not (Test-Path $EnvFile)) {
        throw "Modo automatico requer o arquivo .env ($EnvFile). Copie o .env.example ou use -Interactive."
    }
}

if ($ProxmoxHost -eq "") { throw "PROXMOX_HOST nao definido (parametro, .env ou modo interativo)." }
foreach ($required in @("CTID", "STORAGE", "BRIDGE", "IP_CIDR")) {
    if (-not $cfg.ContainsKey($required) -or $cfg[$required] -eq "") {
        throw "Valor obrigatorio ausente: $required (preencha o .env ou use -Interactive)"
    }
}
if ($cfg["IP_CIDR"] -ne "dhcp" -and ($cfg["GATEWAY"] ?? "") -eq "") {
    throw "GATEWAY obrigatorio quando IP_CIDR nao e dhcp"
}

# ----- Monta o bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "game-deploy-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null

Copy-Item (Join-Path $ScriptDir "provision-game-lxc.sh") (Join-Path $BundleDir "provision-game-lxc.sh")
Set-Content -Path (Join-Path $BundleDir "game.env") -Value $GameEnvContent -NoNewline

$deployLines = @()
foreach ($key in @("CTID","HOSTNAME_OVERRIDE","STORAGE","TEMPLATE_STORAGE","TEMPLATE_PATTERN","BRIDGE","IP_CIDR","GATEWAY","CT_PASSWORD","TZ","MEMORY","CORES","ROOTFS_SIZE_GB","SWAP","AUTO_UPDATE","UPDATE_SCHEDULE","RECREATE_CT")) {
    if ($cfg.ContainsKey($key) -and $cfg[$key] -ne "") {
        $deployLines += "$key=`"$($cfg[$key])`""
    }
}
Set-Content -Path (Join-Path $BundleDir "deploy.env") -Value ($deployLines -join "`n")

# ----- Envia e executa no Proxmox -----
Write-Host "`nEnviando bundle para root@$ProxmoxHost..." -ForegroundColor Cyan
ssh "root@$ProxmoxHost" "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
tar -C $BundleDir -czf - . | ssh "root@$ProxmoxHost" "tar -xzf - -C '$RemoteBundleDir'"

Write-Host "Executando provisionamento no Proxmox (o download do jogo pode demorar)...`n" -ForegroundColor Cyan
ssh "root@$ProxmoxHost" "cd '$RemoteBundleDir' && bash ./provision-game-lxc.sh"

Write-Host "Deploy finalizado." -ForegroundColor Green
