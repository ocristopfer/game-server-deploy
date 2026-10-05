param(
    # Game name (file games/<name>.env), e.g. dragonwilds
    [string]$Game = "",
    # OR: Steam App ID of the dedicated server (generic deploy)
    [string]$AppId = "",
    # Interactive mode: asks for each value (the .env becomes just the prompts' default)
    [switch]$Interactive,
    # Steam Guard code (games whose server requires a Steam account, e.g. dayz).
    # The code expires quickly - pass it at deploy time instead of leaving it in the .env.
    [string]$SteamGuardCode = "",
    # Do not register the server in the panel at the end of the deploy
    [switch]$NoRegister,
    [string]$ProxmoxHost = "",
    # Proxmox root password. Normally it lives in PROXMOX_PASSWORD in the .env.
    [string]$ProxmoxPassword = "",
    # Authorizes your public key on Proxmox and stops depending on a password in later deploys
    [switch]$InstallKey,
    # Turns on the systemd sandbox of the game unit (lib/ct-sandbox-unit.sh) after the first start,
    # with automatic rollback if the game fails under it. Off by default: prove each game first.
    [switch]$UnitSandbox,
    [string]$EnvFile = "",
    [string]$RemoteBundleDir = "/root/game-deploy"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# `$ScriptDir` is the folder of THIS script (where the sibling provision-*.sh lives). `$RepoRoot`
# is the repository root, two levels up, and tools/, lib/, games/ and .env come from there.
# At the root the two were the same thing by accident; here the difference must be explicit.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

function Read-EnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { return @{} }
    return (Read-EnvLines (Get-Content $Path))
}

# Same parser for the text of games/<game>.env, which in the generic deploy (-AppId) is
# generated in memory and never exists as a file.
function Read-EnvText([string]$Text) {
    return (Read-EnvLines ($Text -split "`r?`n"))
}

function Read-EnvLines([string[]]$Lines) {
    $map = @{}
    foreach ($line in $Lines) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1).Trim()
        # strip inline comment and quotes. The "KEY=   # note" case must come first:
        # after the Trim above the '#' is at the start and the split does not match, making the
        # comment text become the value.
        if ($value.StartsWith("#")) { $value = "" }
        $value = ($value -split '\s+#')[0].Trim().Trim('"').Trim("'")
        $map[$key] = $value
    }
    return $map
}

# Reads a key from the map with a fallback (compatible with Windows PowerShell 5.1, no '??')
function Get-Cfg($Map, [string]$Key, [string]$Default = "") {
    if ($Map.ContainsKey($Key) -and $Map[$Key] -ne "" -and $null -ne $Map[$Key]) { return $Map[$Key] }
    return $Default
}

# Suffix used in the per-game keys of the .env: dragonwilds -> CTID_DRAGONWILDS
function Get-GameSuffix([string]$Key) {
    return (($Key.ToUpper()) -replace '[^A-Z0-9]', '_')
}

# {value -> suffix} of the <Key>_<GAME> keys that belong to OTHER games.
# Used to detect that the resolved CTID/IP is already another game's container.
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

# "10.20.1.20/24" -> "10.20.1.20" (compares IPs ignoring the mask)
function Get-IpOnly([string]$Cidr) {
    return (($Cidr -split "/")[0]).Trim()
}

# Asks without echoing to the screen (Steam account password). Empty = keeps the default.
function AskSecret([string]$Label, [string]$Default) {
    $mark = ""
    if ($Default -ne "") { $mark = " [Enter mantem o valor do .env]" }
    $sec = Read-Host "$Label$mark" -AsSecureString
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

# ----- Proxmox access: key when there is one, the .env password when not -----
# Same mechanism as deploy-admin.ps1. Windows ssh/scp does not accept a password as a
# parameter, but OpenSSH 8.4+ calls the program pointed to by SSH_ASKPASS when
# SSH_ASKPASS_REQUIRE=force. The file created below does not store the password: it only echoes
# an environment variable of this process.
$script:AskPassFile = ""
# Options applied to EVERY ssh/scp of the deploy. In password mode they turn off the key
# attempt: without that ssh may fall back to the console prompt, which in a long deploy
# means stopping halfway waiting for someone to type.
$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")
# Host the authentication above applies to (the Proxmox). The panel CT is another machine,
# with another root password - sending it the Proxmox password would only cause an auth failure.
$script:AuthTarget = ""

function Get-SshOptsFor([string]$Target) {
    if ($Target -ne "" -and $Target -eq $script:AuthTarget) { return $script:SshOpts }
    return @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")
}

function Enable-PasswordAuth([string]$Password) {
    if ($script:AskPassFile -eq "") {
        $script:AskPassFile = Join-Path $env:TEMP "gamedeploy-askpass.cmd"
        Set-Content -Path $script:AskPassFile -Encoding ASCII -Value @(
            "@echo off",
            "echo %GAMEDEPLOY_SSH_PASSWORD%"
        )
    }
    $env:GAMEDEPLOY_SSH_PASSWORD = $Password
    $env:SSH_ASKPASS = $script:AskPassFile
    $env:SSH_ASKPASS_REQUIRE = "force"
    # Some builds only consult the askpass when DISPLAY is set.
    if (-not $env:DISPLAY) { $env:DISPLAY = "localhost:0" }
    $script:SshOpts += @("-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password")
}

function Disable-PasswordAuth {
    foreach ($name in @("GAMEDEPLOY_SSH_PASSWORD", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE")) {
        Remove-Item "env:$name" -ErrorAction SilentlyContinue
    }
    if ($script:AskPassFile -ne "" -and (Test-Path $script:AskPassFile)) {
        Remove-Item $script:AskPassFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-KeyAuth([string]$Target) {
    # "Could not log in" is an expected answer here, not a deploy error - hence the relaxed
    # preference (see the comment of the auxiliary ssh block further down).
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new `
            "root@$Target" "true" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Initialize-ProxmoxAuth([string]$Target, [string]$Password) {
    $script:AuthTarget = $Target
    if (Test-KeyAuth $Target) {
        Write-Host "Proxmox: entrando por chave SSH." -ForegroundColor DarkGray
        return $false
    }
    if ($Password -eq "") {
        throw ("Nao consegui entrar em root@$Target por chave SSH. " +
               "Preencha PROXMOX_PASSWORD no .env (ou use -ProxmoxPassword), " +
               "ou autorize sua chave publica no Proxmox.")
    }
    Enable-PasswordAuth $Password
    Write-Host "Proxmox: sem chave autorizada, usando a senha do .env." -ForegroundColor DarkGray
    return $true
}

# Operator's public key: once it is authorized on Proxmox, the following deploys do not
# ask for any password - not even once per ssh call.
function Get-LocalPubKey {
    foreach ($name in @("id_ed25519.pub", "id_rsa.pub")) {
        $path = Join-Path $env:USERPROFILE ".ssh\$name"
        if (Test-Path $path) { return ((Get-Content $path -Raw).Trim()) }
    }
    return ""
}

function Install-KeyOnProxmox([string]$Target) {
    $pub = Get-LocalPubKey
    if ($pub -eq "") {
        Write-Host "Sem chave publica local para instalar (rode ssh-keygen -t ed25519)." -ForegroundColor Yellow
        return
    }
    Write-Host "Autorizando sua chave publica em root@$Target..." -ForegroundColor Cyan
    $cmd = "install -d -m 700 /root/.ssh && touch /root/.ssh/authorized_keys && " +
           "chmod 600 /root/.ssh/authorized_keys && " +
           "grep -qF '$pub' /root/.ssh/authorized_keys || echo '$pub' >> /root/.ssh/authorized_keys"
    Invoke-Ssh $Target $cmd
    if ($LASTEXITCODE -ne 0) { throw "Falha ao autorizar a chave em root@$Target" }
    Write-Host "Pronto: os proximos deploys entram por chave, sem senha." -ForegroundColor Green
}

# ----- auxiliary ssh (queries and registration in the panel) -----
# In PowerShell 5.1 the stderr of a native executable becomes an exception when
# ErrorActionPreference is 'Stop' - even when the command finishes successfully.
# So every call here relaxes the preference: the real error is $LASTEXITCODE.

# .gitattributes stores every .ps1 as CRLF, so every here-string in this file is born
# with a \r at the end of each line. The reader on the other side is bash, and for it the \r is
# part of the argument: 'sleep 3' becomes "invalid interval" and a service name gains a
# \x0d at the end. Every remote command input goes through here first.
function ConvertTo-Lf([string]$Text) { return ($Text -replace "`r", "") }

# ssh/scp of the main flow: they carry $script:SshOpts, which is where the
# authentication lives (key or password via askpass).
function Invoke-Ssh([string]$Target, [string]$Command) {
    $sshOptions = Get-SshOptsFor $Target
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        ssh @sshOptions "root@$Target" (ConvertTo-Lf $Command)
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-Scp([string[]]$Sources, [string]$Destination) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        scp @script:SshOpts @Sources $Destination
    } finally {
        $ErrorActionPreference = $previous
    }
}

# -Batch for targets that are only worth trying by key (the panel CT): without an authorized
# key the query fails right away instead of stalling the deploy on a password prompt.
function Invoke-SshQuery([string]$Target, [string]$Command, [switch]$Batch) {
    $sshOptions = @(Get-SshOptsFor $Target) + @("-o", "ConnectTimeout=10")
    if ($Batch) { $sshOptions += @("-o", "BatchMode=yes") }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = ssh @sshOptions "root@$Target" (ConvertTo-Lf $Command) 2>$null
    } finally {
        $ErrorActionPreference = $previous
    }
    return $output
}

# Same as above, but with the output going to the screen (the panel registration replies
# "servidor 'X' cadastrado").
function Invoke-SshLive([string]$Target, [string]$Command) {
    $sshOptions = Get-SshOptsFor $Target
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        ssh @sshOptions "root@$Target" (ConvertTo-Lf $Command)
    } finally {
        $ErrorActionPreference = $previous
    }
}

# First useful line of an output that may come as an array of lines
function Get-FirstLine($Output) {
    if ($null -eq $Output) { return "" }
    return (($Output | Select-Object -First 1) -as [string]).Trim()
}

# ----- Game selection -----
if ($Game -eq "" -and $AppId -eq "") {
    $available = Get-ChildItem (Join-Path $RepoRoot "games") -Filter "*.env" |
        Where-Object { $_.Name -ne "_template.env" } |
        ForEach-Object { $_.BaseName }
    Write-Host "Informe -Game <nome> ou -AppId <steam_app_id>." -ForegroundColor Yellow
    Write-Host ("Jogos disponiveis: " + ($available -join ", "))
    exit 1
}

$GameEnvContent = $null
if ($Game -ne "") {
    $GameEnvPath = Join-Path $RepoRoot "games\$Game.env"
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

# ----- Infra configuration (.env / interactive) -----
if ($EnvFile -eq "") { $EnvFile = Join-Path $RepoRoot ".env" }
$cfg = Read-EnvFile $EnvFile

# ----- Per-game values (CTID_<GAME>, IP_CIDR_<GAME>, MEMORY_<GAME>...) -----
# Each game lives in its own container. Without these keys, every deploy would land on the
# generic CTID/IP of the .env and the second game would overwrite the first one's container.
# The same text that goes into the bundle, already as a map: GAME_KEY comes from it and, at the
# end of the deploy, the panel registration data (ports, config, player counting).
$game = Read-EnvText $GameEnvContent
$GameKey = Get-Cfg $game "GAME_KEY" $Game
$GameSuffix = Get-GameSuffix $GameKey
$Display = Get-Cfg $game "GAME_DISPLAY_NAME" $GameKey

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

# Games whose server depot requires a Steam account (STEAM_ANONYMOUS=0 in games/<game>.env).
# The credentials live in the .env/prompt - never in games/*.env, which goes into git.
$SteamAnon = (Get-Cfg $game "STEAM_ANONYMOUS" "1") -ne "0"
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

# Authentication is decided ONCE, before any ssh/scp: by key if it is already
# authorized, otherwise by the .env password via askpass. Without that every ssh of the deploy
# opens its own prompt - and this script calls ssh half a dozen times per game.
if ($ProxmoxPassword -eq "") { $ProxmoxPassword = Get-Cfg $cfg "PROXMOX_PASSWORD" }
$UsandoSenha = Initialize-ProxmoxAuth $ProxmoxHost $ProxmoxPassword
if ($InstallKey) {
    if ($UsandoSenha) {
        Install-KeyOnProxmox $ProxmoxHost
    } else {
        Write-Host "Chave SSH ja autorizada no Proxmox - nada a instalar." -ForegroundColor DarkGray
    }
}

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

# ----- Guard against container collision -----
# Deploy is idempotent per CTID: pointing at another game's CTID does NOT create a new
# container, it reconfigures the existing one and swaps the game running inside it.
$ctidOwners = Get-ScopedOwners $cfg "CTID" $GameSuffix
if ($ctidOwners.ContainsKey($cfg["CTID"])) {
    throw ("CTID $($cfg['CTID']) ja pertence ao jogo $($ctidOwners[$cfg['CTID']]) (CTID_$($ctidOwners[$cfg['CTID']]) no .env). " +
           "Defina CTID_${GameSuffix} com um id livre.")
}
if ((Get-Cfg $cfg "ADMIN_CTID") -eq $cfg["CTID"]) {
    throw "CTID $($cfg['CTID']) e o do painel (ADMIN_CTID). Defina CTID_${GameSuffix} com um id livre."
}

if ($cfg["IP_CIDR"] -ne "dhcp") {
    $myIp = Get-IpOnly $cfg["IP_CIDR"]
    foreach ($pair in (Get-ScopedOwners $cfg "IP_CIDR" $GameSuffix).GetEnumerator()) {
        if ((Get-IpOnly $pair.Key) -eq $myIp) {
            throw ("IP $myIp ja e do jogo $($pair.Value) (IP_CIDR_$($pair.Value) no .env). " +
                   "Defina IP_CIDR_${GameSuffix} com um endereco livre.")
        }
    }
    $adminIp = Get-Cfg $cfg "ADMIN_IP_CIDR"
    if ($adminIp -ne "" -and $adminIp -ne "dhcp" -and (Get-IpOnly $adminIp) -eq $myIp) {
        throw "IP $myIp e o do painel (ADMIN_IP_CIDR). Defina IP_CIDR_${GameSuffix} com um endereco livre."
    }
}

Write-Host ("Alvo: CT $($cfg['CTID']) ($GameKey) em $($cfg['IP_CIDR'])") -ForegroundColor Cyan

# ----- Panel: where it runs and what its public key is -----
# Fixed paths of the panel CT (provision-admin-lxc.sh). Registration runs as the
# panel user, not as root: sqlite creates the -wal/-shm files next to the
# database, and if root created them the panel (which runs as gamepanel) would lose write access.
# The package lives under the `current` symlink (one release per version; see install-release.sh).
# The `test -f` below fails SILENTLY when this path goes stale: the deploy only says "painel
# nao encontrado" and goes on WITHOUT registering the server. It happened twice already, first
# when the code moved to src/ and again when the release became a folder per version.
# Running the file directly works because app.py puts the parent folder on sys.path.
$PanelApp = "/opt/gamepanel/current/gamepanel/app.py"
$PanelUser = "gamepanel"
$PanelPubKeyPath = "/etc/gamepanel/id_ed25519.pub"
$AdminCtid = Get-Cfg $cfg "ADMIN_CTID"

# Panel address to talk to it directly (panel outside this Proxmox).
function Resolve-PanelHost($Map) {
    $fromEnv = Get-Cfg $Map "ADMIN_HOST"
    if ($fromEnv -ne "") { return $fromEnv }
    $cidr = Get-Cfg $Map "ADMIN_IP_CIDR"
    if ($cidr -ne "" -and $cidr -ne "dhcp") { return (Get-IpOnly $cidr) }
    return ""
}
$PanelHost = Resolve-PanelHost $cfg

# Without PANEL_PUBKEY the CT is born without letting the panel in, and the registration at the
# end of the deploy would show up as a server that does not respond. The key belongs to the panel,
# so we can fetch it instead of requiring it to be copied into the .env.
if ((Get-Cfg $cfg "PANEL_PUBKEY") -eq "") {
    $readBack = ""
    if ($AdminCtid -ne "") {
        $readBack = Get-FirstLine (Invoke-SshQuery $ProxmoxHost "pct exec $AdminCtid -- cat $PanelPubKeyPath")
        if ($LASTEXITCODE -ne 0) { $readBack = "" }
    }
    if ($readBack -eq "" -and $PanelHost -ne "") {
        $readBack = Get-FirstLine (Invoke-SshQuery $PanelHost "cat $PanelPubKeyPath" -Batch)
        if ($LASTEXITCODE -ne 0) { $readBack = "" }
    }
    if ($readBack -ne "") {
        $cfg["PANEL_PUBKEY"] = $readBack
        Write-Host "Chave publica do painel lida do proprio painel (PANEL_PUBKEY vazio no .env)." -ForegroundColor DarkGray
    } else {
        Write-Host ("Sem PANEL_PUBKEY e sem painel acessivel: o CT nao vai aceitar o painel por SSH. " +
                    "Suba o painel (.\deploy-admin.ps1) ou preencha PANEL_PUBKEY no .env.") -ForegroundColor Yellow
    }
}

# ----- Build the bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "game-deploy-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null

# The files are read by bash on Proxmox: always write them as UTF-8 without BOM and with LF
# (Set-Content uses CRLF and would leave a \r at the end of each .env value)
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

# Which .sh to send to Proxmox: provision-game-lxc.sh (SteamCMD) for almost every game, or the
# one games/<game>.env itself asks for in PROVISION_SCRIPT (an installer that does not depend on
# Steam; no game uses it today). Without the key, behavior is identical to before.
$ProvisionScript = Get-Cfg $game "PROVISION_SCRIPT" "provision-game-lxc.sh"
Copy-Item (Join-Path $ScriptDir $ProvisionScript) (Join-Path $BundleDir $ProvisionScript)
# The phases that run inside the CT (SteamCMD, Wine/Proton, systemd) live in lib/ct-phases.sh,
# which provision-game-lxc.sh reads with `source`. The bundle is a folder without subfolders (scp
# carries only loose files), so it travels next to the script. LF guaranteed: bash reads it.
if ($ProvisionScript -eq "provision-game-lxc.sh") {
    Write-LfFile (Join-Path $BundleDir "ct-phases.sh") ([System.IO.File]::ReadAllText((Join-Path $RepoRoot "lib\ct-phases.sh")))
    Write-LfFile (Join-Path $BundleDir "ct-firewall.sh") ([System.IO.File]::ReadAllText((Join-Path $RepoRoot "lib\ct-firewall.sh")))
    # The gamepanel user, sudo rules and root helpers (the panel no longer logs in as root).
    Write-LfFile (Join-Path $BundleDir "ct-panel-access.sh") ([System.IO.File]::ReadAllText((Join-Path $RepoRoot "lib\ct-panel-access.sh")))
    # The opt-in game unit sandbox (it only runs with -UnitSandbox).
    Write-LfFile (Join-Path $BundleDir "ct-sandbox-unit.sh") ([System.IO.File]::ReadAllText((Join-Path $RepoRoot "lib\ct-sandbox-unit.sh")))
}
Write-LfFile (Join-Path $BundleDir "game.env") $GameEnvContent

$deployLines = @()
foreach ($key in @("CTID","HOSTNAME_OVERRIDE","STORAGE","TEMPLATE_STORAGE","TEMPLATE_PATTERN","BRIDGE","IP_CIDR","GATEWAY","CT_PASSWORD","TZ","MEMORY","CORES","ROOTFS_SIZE_GB","SWAP","AUTO_UPDATE","UPDATE_SCHEDULE","RECREATE_CT","PANEL_PUBKEY","STEAM_USER","STEAM_PASS","STEAM_GUARD_CODE")) {
    if ($cfg.ContainsKey($key) -and $cfg[$key] -ne "") {
        $deployLines += "$key=`"$($cfg[$key])`""
    }
}
# CT firewall: only the panel opens SSH on this server (the broker does not touch CTs made here).
# Without the panel address the firewall is NOT applied - applying it would lock the panel out.
if ($PanelHost -ne "") { $deployLines += "FW_MGMT_SOURCES=`"$PanelHost`"" }
else { Write-Host "ADMIN_HOST/ADMIN_IP_CIDR vazios: o CT sobe SEM firewall interno." -ForegroundColor Yellow }
if ((Get-Cfg $cfg "CT_FIREWALL") -eq "0") { $deployLines += "CT_FIREWALL=`"0`"" }
if ($UnitSandbox) { $deployLines += "GAME_UNIT_SANDBOX=`"1`"" }
Write-LfFile (Join-Path $BundleDir "deploy.env") (($deployLines -join "`n") + "`n")

# ----- Send and run on Proxmox -----
Write-Host "`nEnviando bundle para root@$ProxmoxHost..." -ForegroundColor Cyan
Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

# scp instead of 'tar -czf - | ssh tar -xzf -': PowerShell converts to text whatever
# goes through a pipe between two native executables, which corrupts the tar.gz stream.
$bundleFiles = @(Get-ChildItem -Path $BundleDir -File | ForEach-Object { $_.FullName })
Invoke-Scp $bundleFiles "root@${ProxmoxHost}:$RemoteBundleDir/"
if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os arquivos do bundle para root@$ProxmoxHost" }

# deploy.env carries the CT password and, in games like dayz, the Steam account password
Invoke-Ssh $ProxmoxHost "chmod 700 '$RemoteBundleDir' && chmod 600 '$RemoteBundleDir/deploy.env'" | Out-Null

Write-Host "Executando provisionamento no Proxmox (o download do jogo pode demorar)...`n" -ForegroundColor Cyan
Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./$ProvisionScript"
if ($LASTEXITCODE -ne 0) { throw "Provisionamento falhou no host Proxmox (veja a saida acima)" }

# The local bundle has a copy of deploy.env (passwords) - do not leave it lying in %TEMP%
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }

# ----- Registration in the panel -----
# Same path as the Docker deploy: the panel registers it through its own CLI
# (app.py --register-server), which is idempotent - on a redeploy it updates the
# existing server instead of duplicating it.

# Escapes a value to become a single-quoted argument in the remote shell.
function ConvertTo-ShQuoted([string]$Value) {
    return "'" + ($Value -replace "'", "'\''") + "'"
}

# Address of the game CT: with a fixed IP we already know it; with dhcp only the CT knows.
function Get-CtIp([string]$Cidr, [string]$Ctid) {
    if ($Cidr -ne "dhcp") { return (Get-IpOnly $Cidr) }
    $output = Get-FirstLine (Invoke-SshQuery $ProxmoxHost "pct exec $Ctid -- hostname -I")
    if ($LASTEXITCODE -ne 0 -or $output -eq "") { return "" }
    return (($output -split '\s+')[0])
}

$registered = $false
$CtIp = ""
if (-not $NoRegister) {
    $CtIp = Get-CtIp $cfg["IP_CIDR"] $cfg["CTID"]
    if ($CtIp -eq "") {
        Write-Host "Nao consegui descobrir o IP do CT $($cfg['CTID']) - cadastre o servidor pela tela Adicionar." -ForegroundColor Yellow
    } else {
        $cmdArgs = @(
            "--register-server", $Display,
            "--server-host", $CtIp,
            "--service", "$GameKey.service",
            # With the panel key the provisioning created the gamepanel user and LOCKED root
            # login over SSH: registering as root would leave the panel knocking on a closed door.
            # On a redeploy this also switches an old root-mode server to gamepanel.
            "--ssh-user", $(if ((Get-Cfg $cfg "PANEL_PUBKEY") -ne "") { "gamepanel" } else { "root" }),
            "--game-port", (Get-Cfg $game "GAME_PORTS"),
            "--query-port", (Get-Cfg $game "QUERY_PORT" "0"),
            "--config-path", (Get-Cfg $game "CONFIG_PATH"),
            "--config-files", (Get-Cfg $game "CONFIG_FILES"),
            # Save folders that the panel's Backups screen keeps. On a redeploy the panel
            # keeps what was already there: whoever adjusted it on screen does not lose it.
            "--backup-paths", (Get-Cfg $game "BACKUP_PATHS"),
            "--player-source", (Get-Cfg $game "PLAYER_SOURCE"),
            # Slots: the panel shows "2/6" when the count does not bring the total (log, connections).
            "--max-players", $(if ((Get-Cfg $game "MAX_PLAYERS") -match '^\d+$') { (Get-Cfg $game "MAX_PLAYERS") } else { "0" }),
            # Counting by log: patterns and, when the name only exists in a separate file
            # (DayZ's .ADM), its path.
            "--join-re", (Get-Cfg $game "JOIN_RE"),
            "--leave-re", (Get-Cfg $game "LEAVE_RE"),
            "--log-path", (Get-Cfg $game "LOG_PATH"),
            "--notes", "CT $($cfg['CTID']) no Proxmox $ProxmoxHost (deploy-game.ps1)."
        )
        $parts = @("runuser", "-u", $PanelUser, "--", "python3", $PanelApp)
        foreach ($value in $cmdArgs) { $parts += (ConvertTo-ShQuoted $value) }
        $registerCmd = ($parts -join " ")

        # 1) Through the Proxmox host itself, which is the path that always exists in an LXC deploy:
        #    the panel lives in a CT on the same host and does not need to accept SSH from outside.
        if ($AdminCtid -ne "") {
            Invoke-SshQuery $ProxmoxHost "pct exec $AdminCtid -- test -f $PanelApp" | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "`nCadastrando $Display no painel (CT $AdminCtid)..." -ForegroundColor Cyan
                Invoke-SshLive $ProxmoxHost "pct exec $AdminCtid -- $registerCmd"
                $registered = ($LASTEXITCODE -eq 0)
            } else {
                Write-Host "Painel nao encontrado no CT $AdminCtid ($PanelApp)." -ForegroundColor DarkGray
            }
        }
        # 2) Panel outside this Proxmox (ADMIN_HOST/ADMIN_IP_CIDR), talking to it directly.
        if (-not $registered -and $PanelHost -ne "") {
            Invoke-SshQuery $PanelHost "test -f $PanelApp" -Batch | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "`nCadastrando $Display no painel ($PanelHost)..." -ForegroundColor Cyan
                Invoke-SshLive $PanelHost $registerCmd
                $registered = ($LASTEXITCODE -eq 0)
            }
        }
        if (-not $registered) {
            Write-Host "Nao consegui cadastrar no painel - use a tela Adicionar (host $CtIp, servico $GameKey.service)." -ForegroundColor Yellow
        }
    }
}

# Removes the password from the environment and deletes the askpass from %TEMP%. It does not
# linger for the next command in this same PowerShell window.
Disable-PasswordAuth

Write-Host "Deploy finalizado." -ForegroundColor Green
if ($registered) {
    Write-Host "Servidor cadastrado no painel: $Display ($CtIp) - a tela Config ja abre o arquivo do jogo." -ForegroundColor Green
}
if ($UsandoSenha -and -not $InstallKey) {
    Write-Host "Dica: rode uma vez com -InstallKey para autorizar sua chave e parar de usar senha." -ForegroundColor DarkGray
}
