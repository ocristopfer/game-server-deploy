param(
    # Proxmox host (empty = PROXMOX_HOST from .env)
    [string]$ProxmoxHost = "",
    # Proxmox root password. The normal path is an authorized SSH key; without one, PROXMOX_PASSWORD from .env.
    [string]$ProxmoxPassword = "",
    [string]$EnvFile = "",
    # Proxmox and OPNsense tokens (outside git). Copy broker.secrets.env.example.
    [string]$SecretsFile = "",
    # Deletes and recreates the broker CT (loses the token, the key and the certificate).
    [switch]$RecreateCt,
    # Generates a new token for the panel (the panel must receive the new one: use -ConfigurePanel).
    [switch]$RotateToken,
    # Generates a new certificate (changes the fingerprint the panel pins: use -ConfigurePanel).
    [switch]$RotateCert,
    # Writes the broker URL, token and fingerprint into the panel (the feature stays OFF there).
    # The old name `-ConfigurarPainel` still works through the Alias: whoever already has the command
    # line saved somewhere does not lose it.
    [Alias('ConfigurarPainel')]
    [switch]$ConfigurePanel,
    # On top of -ConfigurePanel, TURNS the feature ON in the panel. Only after protecting the panel.
    # The old name `-LigarNoPainel` still works through the Alias: whoever already has the command
    # line saved somewhere does not lose it.
    [Alias('LigarNoPainel')]
    [switch]$EnableOnPanel,
    [string]$RemoteBundleDir = "/root/game-broker-deploy"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# `$ScriptDir` is THIS script's folder (where the sibling provision-*.sh lives). `$RepoRoot` is
# the repository root, two levels up, and tools/, lib/, games/ and .env come from there.
# At the root the two were the same thing by accident; here the difference has to be spelled out.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
if ($EnvFile -eq "") { $EnvFile = Join-Path $RepoRoot ".env" }
if ($SecretsFile -eq "") { $SecretsFile = Join-Path $RepoRoot "broker.secrets.env" }

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
        if ($value.StartsWith("#")) { $value = "" }
        $value = ($value -split '\s+#')[0].Trim().Trim('"').Trim("'")
        $map[$key] = $value
    }
    return $map
}

function Get-Cfg($Map, [string]$Key, [string]$Default = "") {
    if ($Map.ContainsKey($Key) -and $Map[$Key] -ne "" -and $null -ne $Map[$Key]) { return $Map[$Key] }
    return $Default
}

# Everything the Proxmox bash reads must go as UTF-8 without BOM and with LF - the Windows CR
# would break the shebang of the .sh files and leave a \r at the end of every value.
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

# Everything this deploy takes to Proxmox is text (.py, .sh, .env): there is no binary here. If
# one day there is, do NOT pass it through here - ReadAllText decodes as UTF-8 and corrupts it (see
# the comment in deploy-admin.ps1, that is how the panel icons arrived broken).
function Copy-AsLf([string]$Source, [string]$Dest) {
    Write-LfFile $Dest ([System.IO.File]::ReadAllText($Source))
}

# Value for bash `source`: in single quotes, with ' escaped. Without this a secret containing
# $, a backtick or quotes would be interpreted, and the error would only show up as an "invalid" token.
function ConvertTo-BashQuoted([string]$Value) {
    if ($Value -match "[\r\n]") { throw "Um valor de configuracao tem quebra de linha (nao suportado)." }
    return "'" + ($Value -replace "'", "'\''") + "'"
}

# ----- Proxmox access (same pattern as deploy-admin.ps1) -----
$script:AskPassFile = ""
$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")

# .gitattributes stores every .ps1 as CRLF: every here-string is born with \r at the end of each
# line, and for the bash on the other side the \r is part of the argument.
function ConvertTo-Lf([string]$Text) { return ($Text -replace "`r", "") }

# ssh/scp write to stderr even when they succeed (Proxmox's `systemctl enable`, for
# example, prints "Created symlink ..." there). In Windows PowerShell 5.1, with output redirected
# and $ErrorActionPreference = "Stop", that line becomes an exception and kills the deploy on top
# of a success. What decides is the exit code ($LASTEXITCODE), which the callers check.
function Invoke-Native([scriptblock]$Block) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Block } finally { $ErrorActionPreference = $previous }
}

function Invoke-Ssh([string]$Target, [string]$Command) {
    Invoke-Native { ssh @script:SshOpts "root@$Target" (ConvertTo-Lf $Command) }
}

function Invoke-Scp([string[]]$Sources, [string]$Destination, [switch]$Recurse) {
    if ($Recurse) { Invoke-Native { scp @script:SshOpts -r @Sources $Destination } }
    else { Invoke-Native { scp @script:SshOpts @Sources $Destination } }
}

function Enable-PasswordAuth([string]$Password) {
    if ($script:AskPassFile -eq "") {
        $script:AskPassFile = Join-Path $env:TEMP "gamebroker-askpass.cmd"
        Set-Content -Path $script:AskPassFile -Encoding ASCII -Value @("@echo off", "echo %GAMEPANEL_SSH_PASSWORD%")
    }
    $env:GAMEPANEL_SSH_PASSWORD = $Password
    $env:SSH_ASKPASS = $script:AskPassFile
    $env:SSH_ASKPASS_REQUIRE = "force"
    if (-not $env:DISPLAY) { $env:DISPLAY = "localhost:0" }
    $script:SshOpts += @("-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password")
}

function Disable-PasswordAuth {
    foreach ($name in @("GAMEPANEL_SSH_PASSWORD", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE")) {
        Remove-Item "env:$name" -ErrorAction SilentlyContinue
    }
    if ($script:AskPassFile -ne "" -and (Test-Path $script:AskPassFile)) {
        Remove-Item $script:AskPassFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-KeyAuth([string]$Target) {
    # "Could not get in" is an expected answer here, not a deploy error.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "root@$Target" "true" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Initialize-ProxmoxAuth([string]$Target, [string]$Password) {
    if (Test-KeyAuth $Target) {
        Write-Host "Proxmox: entrando por chave SSH." -ForegroundColor DarkGray
        return
    }
    if ($Password -eq "") {
        throw ("Nao consegui entrar em root@$Target por chave SSH. Preencha PROXMOX_PASSWORD no .env " +
               "(ou use -ProxmoxPassword), ou autorize sua chave publica no Proxmox.")
    }
    Enable-PasswordAuth $Password
    Write-Host "Proxmox: sem chave autorizada, usando a senha do .env." -ForegroundColor DarkGray
}

# ----- Configuration -----
if (-not (Test-Path $SecretsFile)) {
    throw ("Nao achei $SecretsFile. Copie broker.secrets.env.example para broker.secrets.env e preencha " +
           "(token do Proxmox, chave do OPNsense).")
}
$cfg = Read-EnvFile $EnvFile
$sec = Read-EnvFile $SecretsFile

if ($ProxmoxHost -eq "") { $ProxmoxHost = Get-Cfg $cfg "PROXMOX_HOST" }
if ($ProxmoxHost -eq "") { throw "PROXMOX_HOST nao definido no .env (ou use -ProxmoxHost)." }
if ($ProxmoxPassword -eq "") { $ProxmoxPassword = Get-Cfg $cfg "PROXMOX_PASSWORD" }

if ($EnableOnPanel -and -not $ConfigurePanel) { throw "-EnableOnPanel exige -ConfigurePanel." }

$absent = @()
foreach ($k in @("BROKER_CTID", "BROKER_IP_CIDR", "BROKER_IP_PREFIX")) {
    if ((Get-Cfg $cfg $k) -eq "") { $absent += "$k (.env)" }
}
foreach ($k in @("PROXMOX_URL", "PROXMOX_TOKEN", "PROXMOX_NODE", "PROXMOX_STORAGE", "PROXMOX_BRIDGE",
                 "OPNSENSE_URL", "OPNSENSE_KEY", "OPNSENSE_SECRET")) {
    $v = Get-Cfg $sec $k
    if ($v -eq "" -or $v -match "COLE_|IP_DO_") { $absent += "$k (broker.secrets.env)" }
}
if ($absent.Count -gt 0) { throw ("Faltam valores:`n  - " + ($absent -join "`n  - ")) }

# Panel address: only it may talk to the broker.
$panelIp = Get-Cfg $cfg "ADMIN_HOST"
if ($panelIp -eq "") {
    $adminCidr = Get-Cfg $cfg "ADMIN_IP_CIDR"
    if ($adminCidr -ne "" -and $adminCidr -ne "dhcp") { $panelIp = ($adminCidr -split '/')[0] }
}
if ($panelIp -eq "") { Write-Host "ADMIN_HOST/ADMIN_IP_CIDR vazios: o broker aceitara qualquer origem (so o token). Defina para restringir ao IP do painel." -ForegroundColor Yellow }

# ----- Confirmation before turning the feature on in an exposed panel -----
if ($EnableOnPanel) {
    Write-Host "`nATENCAO: ligar o broker no painel da a quem entrar nele o poder de CRIAR containers e ABRIR portas no firewall." -ForegroundColor Yellow
    Write-Host "Se o painel esta na internet (Cloudflare), proteja-o antes: Cloudflare Access ou 2FA." -ForegroundColor Yellow
    $resp = Read-Host "Digite LIGAR para confirmar"
    if ($resp -ne "LIGAR") { throw "Cancelado: o recurso nao foi ligado." }
}

function New-ReleaseBundle([string]$Package) {
    # Packages here, with the repo's Python. The artifact is deterministic (see
    # tools/build-release.py), so the sha256 that travels with it answers "does the CT have
    # THIS code?", and not just "did the file arrive whole?".
    $builder = Join-Path $RepoRoot "tools/build-release.py"
    if (-not (Test-Path $builder)) { throw "tools/build-release.py nao encontrado em $ScriptDir" }
    $dist = Join-Path ([System.IO.Path]::GetTempPath()) "gamebroker-release"
    if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
    Invoke-Native { python $builder $Package --out $dist }
    if ($LASTEXITCODE -ne 0) { throw "Falha ao empacotar o release (codigo $LASTEXITCODE)" }
    $tarball = Get-ChildItem -Path $dist -Filter "$Package-*.tar.gz" | Select-Object -First 1
    if (-not $tarball) { throw "o empacotador nao gerou nenhum $Package-*.tar.gz em $dist" }
    $sha = ((Get-Content "$($tarball.FullName).sha256" -Raw).Trim() -split "\s+")[0]
    return [pscustomobject]@{ Path = $tarball.FullName; Name = $tarball.Name; Sha = $sha }
}

# ----- Build the bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "game-broker-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null

Copy-AsLf (Join-Path $ScriptDir "provision-broker-lxc.sh") (Join-Path $BundleDir "provision-broker-lxc.sh")
Copy-AsLf (Join-Path $RepoRoot "lib/install-release.sh") (Join-Path $BundleDir "install-release.sh")

# The broker CODE travels in a release tar.gz; lib/ and games/ still go loose because
# they are not the Python package - they are data and scripts the CT reads, and provisioning
# already replaces both entirely. The loop that copied each .py is gone: it was the one that had
# to be revisited for every new subfolder of the package, and that left renamed modules alive in the CT.
$Release = New-ReleaseBundle "gamebroker"
# Copy-Item, never Copy-AsLf: a tar.gz passed through the line-ending normalizer is
# decoded as UTF-8 and arrives on the other side as garbage.
Copy-Item $Release.Path (Join-Path $BundleDir $Release.Name)
Write-LfFile (Join-Path $BundleDir "release.env") (
    "RELEASE_TARBALL='$($Release.Name)'`nRELEASE_SHA256='$($Release.Sha)'`n")
Write-Host "Release do broker: $($Release.Name)" -ForegroundColor DarkGray

foreach ($f in (Get-ChildItem (Join-Path $RepoRoot "lib") -Filter "*.sh" -File)) {
    Copy-AsLf $f.FullName (Join-Path (Join-Path $BundleDir "lib") $f.Name)
}
foreach ($f in (Get-ChildItem (Join-Path $RepoRoot "games") -Filter "*.env" -File)) {
    Copy-AsLf $f.FullName (Join-Path (Join-Path $BundleDir "games") $f.Name)
}

# NON-secret configuration: comes from .env, with the default provisioning would also use.
$conf = [ordered]@{
    BROKER_CTID = (Get-Cfg $cfg "BROKER_CTID"); BROKER_HOSTNAME = (Get-Cfg $cfg "BROKER_HOSTNAME" "gamebroker")
    BROKER_IP_CIDR = (Get-Cfg $cfg "BROKER_IP_CIDR"); BROKER_GATEWAY = (Get-Cfg $cfg "BROKER_GATEWAY" (Get-Cfg $cfg "GATEWAY"))
    STORAGE = (Get-Cfg $cfg "STORAGE"); TEMPLATE_STORAGE = (Get-Cfg $cfg "TEMPLATE_STORAGE")
    TEMPLATE_PATTERN = (Get-Cfg $cfg "TEMPLATE_PATTERN"); BRIDGE = (Get-Cfg $cfg "BRIDGE")
    CT_PASSWORD = (Get-Cfg $cfg "CT_PASSWORD"); TZ = (Get-Cfg $cfg "TZ")
    BROKER_PORT = (Get-Cfg $cfg "BROKER_PORT"); BROKER_MEMORY = (Get-Cfg $cfg "BROKER_MEMORY")
    BROKER_CORES = (Get-Cfg $cfg "BROKER_CORES"); BROKER_DISK_GB = (Get-Cfg $cfg "BROKER_DISK_GB")
    BROKER_IP_PREFIX = (Get-Cfg $cfg "BROKER_IP_PREFIX"); BROKER_IP_INICIO = (Get-Cfg $cfg "BROKER_IP_INICIO")
    BROKER_IP_FIM = (Get-Cfg $cfg "BROKER_IP_FIM"); BROKER_CTID_INICIO = (Get-Cfg $cfg "BROKER_CTID_INICIO")
    BROKER_CTID_FIM = (Get-Cfg $cfg "BROKER_CTID_FIM"); BROKER_MAX_INSTANCIAS = (Get-Cfg $cfg "BROKER_MAX_INSTANCIAS")
    BROKER_MAX_CREATIONS_PER_HOUR = (Get-Cfg $cfg "BROKER_MAX_CREATIONS_PER_HOUR")
    BROKER_CTID_BASE = (Get-Cfg $cfg "BROKER_CTID_BASE"); BROKER_PORT_INICIO = (Get-Cfg $cfg "BROKER_PORT_INICIO")
    BROKER_PORT_FIM = (Get-Cfg $cfg "BROKER_PORT_FIM"); CT_FIREWALL = (Get-Cfg $cfg "CT_FIREWALL")
    BROKER_ALLOW_IPS = (Get-Cfg $cfg "BROKER_ALLOW_IPS" $panelIp)
    ADMIN_CTID = (Get-Cfg $cfg "ADMIN_CTID"); BROKER_PANEL_PUBKEY = (Get-Cfg $cfg "PANEL_PUBKEY")
    RECREATE_BROKER_CT = $(if ($RecreateCt) { "1" } else { "0" })
    BROKER_ROTATE_TOKEN = $(if ($RotateToken) { "1" } else { "0" })
    BROKER_ROTATE_CERT = $(if ($RotateCert) { "1" } else { "0" })
    BROKER_CONFIGURE_PANEL = $(if ($ConfigurePanel) { "1" } else { "0" })
    BROKER_ENABLE_IN_PANEL = $(if ($EnableOnPanel) { "1" } else { "0" })
}
$lines = @()
foreach ($k in $conf.Keys) { if ($conf[$k] -ne "") { $lines += "$k=" + (ConvertTo-BashQuoted $conf[$k]) } }
Write-LfFile (Join-Path $BundleDir "broker.conf.env") (($lines -join "`n") + "`n")

# Secrets: only the keys provisioning knows about (no junk from the file goes along).
$lines = @()
foreach ($k in @("PROXMOX_URL", "PROXMOX_TOKEN", "PROXMOX_NODE", "PROXMOX_POOL", "PROXMOX_STORAGE",
                 "PROXMOX_TEMPLATE_STORAGE", "PROXMOX_TEMPLATE", "PROXMOX_BRIDGE", "PROXMOX_CERT_SHA256",
                 "OPNSENSE_URL", "OPNSENSE_KEY", "OPNSENSE_SECRET", "OPNSENSE_CERT_SHA256", "OPNSENSE_WAN",
                 "STEAM_USER", "STEAM_PASS")) {
    $v = Get-Cfg $sec $k
    if ($v -ne "") { $lines += "$k=" + (ConvertTo-BashQuoted $v) }
}
Write-LfFile (Join-Path $BundleDir "broker.secrets.env") (($lines -join "`n") + "`n")

# ----- Send and run on Proxmox -----
try {
    Initialize-ProxmoxAuth $ProxmoxHost $ProxmoxPassword
    Write-Host "`nEnviando bundle para root@$ProxmoxHost..." -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

    # scp -r: gamebroker/, lib/ and games/ are folders; the loose files go along.
    $items = @(Get-ChildItem -Path $BundleDir | ForEach-Object { $_.FullName })
    Invoke-Scp $items "root@${ProxmoxHost}:$RemoteBundleDir/" -Recurse
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar o bundle para root@$ProxmoxHost" }

    # The bundle carries Proxmox and OPNsense tokens: only root reads it, and provisioning deletes it.
    Invoke-Ssh $ProxmoxHost "chmod 700 '$RemoteBundleDir' && chmod 600 '$RemoteBundleDir/broker.secrets.env'" | Out-Null

    Write-Host "Executando o provisionamento no Proxmox...`n" -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./provision-broker-lxc.sh"
    if ($LASTEXITCODE -ne 0) { throw "Provisionamento do broker falhou no host Proxmox (veja a saida acima)" }
} finally {
    # The local bundle holds a copy of the secrets: do not leave it lying in %TEMP%, nor the remote one.
    if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
    try { Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir'" | Out-Null } catch { }
    Disable-PasswordAuth
}

Write-Host "`nBroker publicado. Confira a IMPRESSAO dos certificados e as REGRAS DE FIREWALL do resumo acima." -ForegroundColor Green
