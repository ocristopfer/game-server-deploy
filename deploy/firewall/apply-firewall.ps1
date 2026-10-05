param(
    # Proxmox host (empty = PROXMOX_HOST from the .env)
    [string]$ProxmoxHost = "",
    [string]$EnvFile = "",
    # Only these CTs (e.g. "302,303"). Empty = panel, broker and all the broker's games.
    [string]$Only = "",
    # Game CTs made by deploy-game.ps1 (outside the broker), e.g. "210,211".
    [string]$ExtraGameCts = "",
    # Only shows the rules each CT would get; applies nothing.
    [switch]$DryRun,
    [string]$RemoteBundleDir = "/root/ct-firewall-deploy"
)

# Applies the in-CT firewall (lib/ct-firewall.sh) to containers that already exist.
# New CTs are already born with it; this script is for the older ones. The work is done by
# apply-firewall.sh, on the host: everything through `pct`, each CT tested afterwards, and turned
# off automatically if the test fails. Emergency on any CT: pct exec <CT> -- ct-firewall off

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
if ($EnvFile -eq "") { $EnvFile = Join-Path $RepoRoot ".env" }

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

# The Proxmox bash reads all of this: UTF-8 without BOM and LF, otherwise the \r gets into every value.
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

function Copy-AsLf([string]$Source, [string]$Dest) {
    Write-LfFile $Dest ([System.IO.File]::ReadAllText($Source))
}

$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")

function ConvertTo-Lf([string]$Text) { return ($Text -replace "`r", "") }

# ssh/scp write to stderr even when they succeed; in PowerShell 5.1 that would become an exception.
# What decides is $LASTEXITCODE.
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

# List "302, 303" -> "302,303", rejecting anything that is not a CT number.
function ConvertTo-CtList([string]$Raw, [string]$Name) {
    $items = @($Raw -split '[,\s]+' | Where-Object { $_ -ne "" })
    foreach ($i in $items) { if ($i -notmatch '^\d{2,9}$') { throw "${Name}: '$i' is not a CT number." } }
    return ($items -join ",")
}

# ----- Configuration -----
$cfg = Read-EnvFile $EnvFile
if ($ProxmoxHost -eq "") { $ProxmoxHost = Get-Cfg $cfg "PROXMOX_HOST" }
if ($ProxmoxHost -eq "") { throw "PROXMOX_HOST is not set in .env (or use -ProxmoxHost)." }
$panelCtid = Get-Cfg $cfg "ADMIN_CTID"
if ($panelCtid -eq "") { throw "ADMIN_CTID is not set in .env: the tests start from the panel." }

$fwLines = @(
    "PANEL_CTID=`"$panelCtid`"",
    "BROKER_CTID=`"$(Get-Cfg $cfg 'BROKER_CTID')`"",
    "PANEL_PORT=`"$(Get-Cfg $cfg 'ADMIN_PORT' '8080')`"",
    "BROKER_PORT=`"$(Get-Cfg $cfg 'BROKER_PORT' '8443')`"",
    "ADMIN_FIREWALL_SOURCES=`"$(Get-Cfg $cfg 'ADMIN_FIREWALL_SOURCES' '192.168.0.0/16')`"",
    "BROKER_IP_PREFIX=`"$(Get-Cfg $cfg 'BROKER_IP_PREFIX')`"",
    "BROKER_IP_INICIO=`"$(Get-Cfg $cfg 'BROKER_IP_INICIO' '102')`"",
    "BROKER_IP_FIM=`"$(Get-Cfg $cfg 'BROKER_IP_FIM' '199')`"",
    "EXTRA_GAME_CTS=`"$(ConvertTo-CtList $ExtraGameCts 'ExtraGameCts')`"",
    "ONLY_CTS=`"$(ConvertTo-CtList $Only 'Only')`"",
    "DRY_RUN=`"$(if ($DryRun) { '1' } else { '0' })`""
)

# ----- Bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "ct-firewall-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null
Copy-AsLf (Join-Path $ScriptDir "apply-firewall.sh") (Join-Path $BundleDir "apply-firewall.sh")
Copy-AsLf (Join-Path $RepoRoot "lib/ct-firewall.sh") (Join-Path $BundleDir "ct-firewall.sh")
# games/*.env: the ports of the legacy games, which are not in the broker's database.
foreach ($f in Get-ChildItem -Path (Join-Path $RepoRoot "games") -Filter "*.env") {
    Copy-AsLf $f.FullName (Join-Path (Join-Path $BundleDir "games") $f.Name)
}
Write-LfFile (Join-Path $BundleDir "fw.env") (($fwLines -join "`n") + "`n")

# ----- Send and run -----
try {
    Write-Host "`nSending to root@$ProxmoxHost..." -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
    if ($LASTEXITCODE -ne 0) { throw "Failed to prepare $RemoteBundleDir on root@$ProxmoxHost" }
    $items = @(Get-ChildItem -Path $BundleDir | ForEach-Object { $_.FullName })
    Invoke-Scp $items "root@${ProxmoxHost}:$RemoteBundleDir/" -Recurse
    if ($LASTEXITCODE -ne 0) { throw "Failed to send the files to root@$ProxmoxHost" }

    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./apply-firewall.sh"
    $code = $LASTEXITCODE
} finally {
    if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
    try { Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir'" | Out-Null } catch { }
}
if ($code -ne 0) { throw "Some CT failed (see FAILED in the summary above). The ones that failed were left WITHOUT a firewall, not locked out." }
