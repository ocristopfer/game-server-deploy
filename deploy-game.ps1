param(
    # Nome do jogo (arquivo games/<nome>.env), ex: dragonwilds
    [string]$Game = "",
    # OU: App ID do servidor dedicado na Steam (deploy generico)
    [string]$AppId = "",
    # Modo interativo: pergunta cada valor (o .env vira apenas default dos prompts)
    [switch]$Interactive,
    # Codigo do Steam Guard (jogos cujo servidor exige conta Steam, ex: dayz).
    # O codigo expira rapido - passe na hora do deploy em vez de deixar no .env.
    [string]$SteamGuardCode = "",
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
        # remove comentario inline e aspas. O caso "CHAVE=   # nota" precisa vir antes:
        # apos o Trim acima o '#' fica no inicio e o split nao casa, fazendo o texto do
        # comentario virar o valor.
        if ($value.StartsWith("#")) { $value = "" }
        $value = ($value -split '\s+#')[0].Trim().Trim('"').Trim("'")
        $map[$key] = $value
    }
    return $map
}

# Le uma chave do mapa com fallback (compativel com Windows PowerShell 5.1, sem '??')
function Get-Cfg($Map, [string]$Key, [string]$Default = "") {
    if ($Map.ContainsKey($Key) -and $Map[$Key] -ne "" -and $null -ne $Map[$Key]) { return $Map[$Key] }
    return $Default
}

# Sufixo usado nas chaves por jogo do .env: dragonwilds -> CTID_DRAGONWILDS
function Get-GameSuffix([string]$Key) {
    return (($Key.ToUpper()) -replace '[^A-Z0-9]', '_')
}

# {valor -> sufixo} das chaves <Key>_<JOGO> que pertencem a OUTROS jogos.
# Serve para detectar que o CTID/IP resolvido ja e o container de outro jogo.
function Get-ScopedOwners($Map, [string]$Key, [string]$SelfSuffix) {
    $owners = @{}
    $prefix = "${Key}_"
    foreach ($k in @($Map.Keys)) {
        if (-not $k.StartsWith($prefix)) { continue }
        $suffix = $k.Substring($prefix.Length)
        if ($suffix -ne $SelfSuffix -and $Map[$k] -ne "") { $owners[$Map[$k]] = $suffix }
    }
    return $owners
}

# "192.168.2.20/24" -> "192.168.2.20" (compara IP ignorando a mascara)
function Get-IpOnly([string]$Cidr) {
    return (($Cidr -split "/")[0]).Trim()
}

# Pergunta sem ecoar na tela (senha da conta Steam). Vazio = mantem o default.
function AskSecret([string]$Label, [string]$Default) {
    $marca = ""
    if ($Default -ne "") { $marca = " [Enter mantem o valor do .env]" }
    $sec = Read-Host "$Label$marca" -AsSecureString
    if ($sec.Length -eq 0) { return $Default }
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
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

# ----- Valores por jogo (CTID_<JOGO>, IP_CIDR_<JOGO>, MEMORY_<JOGO>...) -----
# Cada jogo mora no proprio container. Sem essas chaves, todo deploy cairia no CTID/IP
# generico do .env e o segundo jogo sobrescreveria o container do primeiro.
$GameKey = $Game
if ($GameEnvContent -match '(?m)^\s*GAME_KEY\s*=\s*"?([^"\s#]+)') { $GameKey = $Matches[1] }
$GameSuffix = Get-GameSuffix $GameKey

$OverridableKeys = @("CTID","HOSTNAME_OVERRIDE","STORAGE","TEMPLATE_STORAGE","TEMPLATE_PATTERN",
                     "BRIDGE","IP_CIDR","GATEWAY","CT_PASSWORD","TZ","MEMORY","CORES",
                     "ROOTFS_SIZE_GB","SWAP","AUTO_UPDATE","UPDATE_SCHEDULE","RECREATE_CT","PANEL_PUBKEY")
$overridden = @()
foreach ($key in $OverridableKeys) {
    $scoped = "${key}_${GameSuffix}"
    if ($cfg.ContainsKey($scoped) -and $cfg[$scoped] -ne "") {
        $cfg[$key] = $cfg[$scoped]
        $overridden += $key
    }
}
if ($overridden.Count -gt 0) {
    Write-Host ("Valores especificos de ${GameSuffix}: " + ($overridden -join ", ")) -ForegroundColor DarkGray
} else {
    Write-Host "Sem chaves _${GameSuffix} no .env - usando CTID/IP genericos." -ForegroundColor DarkGray
}

if ($ProxmoxHost -eq "") {
    $ProxmoxHost = if ($cfg.ContainsKey("PROXMOX_HOST")) { $cfg["PROXMOX_HOST"] } else { "" }
}

# Jogos cujo depot do servidor exige conta Steam (STEAM_ANONYMOUS=0 no games/<jogo>.env).
# As credenciais vivem no .env/prompt - nunca no games/*.env, que vai para o git.
$SteamAnon = $true
if ($GameEnvContent -match '(?m)^\s*STEAM_ANONYMOUS\s*=\s*"?0') { $SteamAnon = $false }
if ($SteamGuardCode -ne "") { $cfg["STEAM_GUARD_CODE"] = $SteamGuardCode }

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
    $cfg["RECREATE_CT"]     = Ask "Recriar CT se existir? (0/1)" (Get-Cfg $cfg "RECREATE_CT" "0")
    if (-not $SteamAnon) {
        Write-Host "`n$GameKey nao aceita login anonimo: informe uma conta Steam que POSSUA o jogo." -ForegroundColor Yellow
        $cfg["STEAM_USER"]       = Ask       "Conta Steam (login)" (Get-Cfg $cfg "STEAM_USER")
        $cfg["STEAM_PASS"]       = AskSecret "Senha da conta Steam" (Get-Cfg $cfg "STEAM_PASS")
        $cfg["STEAM_GUARD_CODE"] = Ask       "Codigo do Steam Guard (vazio se a conta nao usa)" (Get-Cfg $cfg "STEAM_GUARD_CODE")
    }
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
if ($cfg["IP_CIDR"] -ne "dhcp" -and (Get-Cfg $cfg "GATEWAY") -eq "") {
    throw "GATEWAY obrigatorio quando IP_CIDR nao e dhcp"
}

if (-not $SteamAnon) {
    foreach ($k in @("STEAM_USER","STEAM_PASS")) {
        if ((Get-Cfg $cfg $k) -eq "") {
            throw ("O servidor de $GameKey nao esta disponivel por login anonimo na Steam. " +
                   "Preencha STEAM_USER e STEAM_PASS no .env (conta que POSSUA o jogo) ou use -Interactive. Faltando: $k")
        }
    }
    if ((Get-Cfg $cfg "STEAM_GUARD_CODE") -eq "") {
        Write-Host "Sem STEAM_GUARD_CODE. Se a conta usa Steam Guard, o login vai falhar - repita com -SteamGuardCode <codigo>." -ForegroundColor Yellow
    }
}

# ----- Guarda contra colisao de container -----
# Deploy e idempotente por CTID: apontar para o CTID de outro jogo NAO cria um container
# novo, reconfigura o que ja existe e troca o jogo que roda la dentro.
$ctidOwners = Get-ScopedOwners $cfg "CTID" $GameSuffix
if ($ctidOwners.ContainsKey($cfg["CTID"])) {
    throw ("CTID $($cfg['CTID']) ja pertence ao jogo $($ctidOwners[$cfg['CTID']]) (CTID_$($ctidOwners[$cfg['CTID']]) no .env). " +
           "Defina CTID_${GameSuffix} com um id livre.")
}
if ((Get-Cfg $cfg "ADMIN_CTID") -eq $cfg["CTID"]) {
    throw "CTID $($cfg['CTID']) e o do painel (ADMIN_CTID). Defina CTID_${GameSuffix} com um id livre."
}

if ($cfg["IP_CIDR"] -ne "dhcp") {
    $meuIp = Get-IpOnly $cfg["IP_CIDR"]
    foreach ($par in (Get-ScopedOwners $cfg "IP_CIDR" $GameSuffix).GetEnumerator()) {
        if ((Get-IpOnly $par.Key) -eq $meuIp) {
            throw ("IP $meuIp ja e do jogo $($par.Value) (IP_CIDR_$($par.Value) no .env). " +
                   "Defina IP_CIDR_${GameSuffix} com um endereco livre.")
        }
    }
    $adminIp = Get-Cfg $cfg "ADMIN_IP_CIDR"
    if ($adminIp -ne "" -and $adminIp -ne "dhcp" -and (Get-IpOnly $adminIp) -eq $meuIp) {
        throw "IP $meuIp e o do painel (ADMIN_IP_CIDR). Defina IP_CIDR_${GameSuffix} com um endereco livre."
    }
}

Write-Host ("Alvo: CT $($cfg['CTID']) ($GameKey) em $($cfg['IP_CIDR'])") -ForegroundColor Cyan

# ----- Monta o bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "game-deploy-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null

# Os arquivos sao lidos pelo bash no Proxmox: gravar sempre em UTF-8 sem BOM e com LF
# (Set-Content usa CRLF e deixaria um \r no fim de cada valor do .env)
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

Copy-Item (Join-Path $ScriptDir "provision-game-lxc.sh") (Join-Path $BundleDir "provision-game-lxc.sh")
Write-LfFile (Join-Path $BundleDir "game.env") $GameEnvContent

$deployLines = @()
foreach ($key in @("CTID","HOSTNAME_OVERRIDE","STORAGE","TEMPLATE_STORAGE","TEMPLATE_PATTERN","BRIDGE","IP_CIDR","GATEWAY","CT_PASSWORD","TZ","MEMORY","CORES","ROOTFS_SIZE_GB","SWAP","AUTO_UPDATE","UPDATE_SCHEDULE","RECREATE_CT","PANEL_PUBKEY","STEAM_USER","STEAM_PASS","STEAM_GUARD_CODE")) {
    if ($cfg.ContainsKey($key) -and $cfg[$key] -ne "") {
        $deployLines += "$key=`"$($cfg[$key])`""
    }
}
Write-LfFile (Join-Path $BundleDir "deploy.env") (($deployLines -join "`n") + "`n")

# ----- Envia e executa no Proxmox -----
Write-Host "`nEnviando bundle para root@$ProxmoxHost..." -ForegroundColor Cyan
ssh "root@$ProxmoxHost" "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

# scp em vez de 'tar -czf - | ssh tar -xzf -': o PowerShell converte para texto o que
# passa por um pipe entre dois executaveis nativos, o que corrompe o stream do tar.gz.
$bundleFiles = @(Get-ChildItem -Path $BundleDir -File | ForEach-Object { $_.FullName })
scp @bundleFiles "root@${ProxmoxHost}:$RemoteBundleDir/"
if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os arquivos do bundle para root@$ProxmoxHost" }

# deploy.env leva senha do CT e, em jogos como o dayz, a senha da conta Steam
ssh "root@$ProxmoxHost" "chmod 700 '$RemoteBundleDir' && chmod 600 '$RemoteBundleDir/deploy.env'" | Out-Null

Write-Host "Executando provisionamento no Proxmox (o download do jogo pode demorar)...`n" -ForegroundColor Cyan
ssh "root@$ProxmoxHost" "cd '$RemoteBundleDir' && bash ./provision-game-lxc.sh"
if ($LASTEXITCODE -ne 0) { throw "Provisionamento falhou no host Proxmox (veja a saida acima)" }

# O bundle local tem copia do deploy.env (senhas) - nao deixa sobrando no %TEMP%
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }

Write-Host "Deploy finalizado." -ForegroundColor Green
