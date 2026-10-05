param(
    # The game CT (e.g. 302).
    [Parameter(Mandatory = $true)]
    [string]$Ctid,
    # on = apply the drop-in, restart the game and keep it only if the game survives it;
    # off = remove it and restart; status = show what is installed and what the running game has.
    [ValidateSet("on", "off", "status")]
    [string]$Action = "status",
    # The game's systemd unit. Empty = GAME_UNIT of /etc/gamepanel/ct.env, or the single steam service.
    [string]$Service = "",
    # Seconds the game must stay up under the sandbox (default 60 in the tool).
    [string]$Settle = "",
    # Seconds the game has to reopen its ports after the restart (default 300 in the tool).
    [string]$PortTimeout = "",
    # Extra ports that must be open after the restart, e.g. "7777/udp,27015/udp". The ports the
    # game already had open before are checked anyway (unless -NoBaselinePorts).
    [string]$Ports = "",
    # Directives to leave out for a game proven to need them, e.g. "LockPersonality".
    [string]$Without = "",
    [switch]$NoBaselinePorts,
    [string]$ProxmoxHost = "",
    [string]$ProxmoxPassword = "",
    [string]$EnvFile = "",
    [string]$RemoteBundleDir = "/root/ct-sandbox-unit"
)

# Opt-in systemd sandbox of ONE game container's unit (docs/security-hardening.md, phase 9).
# The work is done by sandbox-ct.sh on the Proxmox host, through pct (root SSH is locked on a
# migrated CT); the logic is lib/ct-sandbox-unit.sh. Same transport as migrate-ct.ps1.

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

# The Proxmox bash reads these files: UTF-8 without BOM and LF, otherwise a \r gets into every value.
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

function Copy-AsLf([string]$Source, [string]$Dest) {
    Write-LfFile $Dest ([System.IO.File]::ReadAllText($Source))
}

function ConvertTo-Lf([string]$Text) { return ($Text -replace "`r", "") }

# ssh/scp write to stderr even when they succeed; in PowerShell 5.1 that would become an
# exception. What decides is $LASTEXITCODE.
function Invoke-Native([scriptblock]$Block) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Block } finally { $ErrorActionPreference = $previous }
}

$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")
$script:AskPassFile = ""

function Invoke-Ssh([string]$Target, [string]$Command) {
    Invoke-Native { ssh @script:SshOpts "root@$Target" (ConvertTo-Lf $Command) }
}

function Invoke-Scp([string[]]$Sources, [string]$Destination) {
    Invoke-Native { scp @script:SshOpts @Sources $Destination }
}

function Test-KeyAuth([string]$Target) {
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

# Same trick as deploy-admin.ps1: OpenSSH on Windows has no password flag, so the password
# comes from an askpass helper that reads an environment variable, removed at the end.
function Enable-PasswordAuth([string]$Password) {
    $script:AskPassFile = Join-Path $env:TEMP "gamepanel-askpass.cmd"
    Set-Content -Path $script:AskPassFile -Encoding ASCII -Value @(
        "@echo off",
        "echo %GAMEPANEL_SSH_PASSWORD%"
    )
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

# ----- Configuration -----
# Each value is checked here AND again by the tool in the CT: these end up in a file bash sources.
if ($Ctid -notmatch '^\d{2,9}$') { throw "-Ctid '$Ctid' is not a CT number." }
if ($Service -ne "" -and $Service -notmatch '^[A-Za-z0-9@._-]+$') { throw "-Service '$Service' is invalid." }
if ($Settle -ne "" -and $Settle -notmatch '^\d{1,4}$') { throw "-Settle '$Settle' must be seconds." }
if ($PortTimeout -ne "" -and $PortTimeout -notmatch '^\d{1,4}$') { throw "-PortTimeout '$PortTimeout' must be seconds." }
$portList = @($Ports -split '[,\s]+' | Where-Object { $_ -ne "" })
foreach ($p in $portList) { if ($p -notmatch '^\d{1,5}/(udp|tcp)$') { throw "-Ports: '$p' is not like 7777/udp." } }
$withoutList = @($Without -split '[,\s]+' | Where-Object { $_ -ne "" })
foreach ($d in $withoutList) { if ($d -notmatch '^[A-Za-z]+$') { throw "-Without: '$d' is not a directive name." } }

$cfg = Read-EnvFile $EnvFile
if ($ProxmoxHost -eq "") { $ProxmoxHost = Get-Cfg $cfg "PROXMOX_HOST" }
if ($ProxmoxHost -eq "") { throw "PROXMOX_HOST is not set in .env (or use -ProxmoxHost)." }
if ($ProxmoxPassword -eq "") { $ProxmoxPassword = Get-Cfg $cfg "PROXMOX_PASSWORD" }

# ----- Bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "ct-sandbox-unit-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null
Copy-AsLf (Join-Path $ScriptDir "sandbox-ct.sh") (Join-Path $BundleDir "sandbox-ct.sh")
Copy-AsLf (Join-Path $RepoRoot "lib/ct-sandbox-unit.sh") (Join-Path $BundleDir "ct-sandbox-unit.sh")
Write-LfFile (Join-Path $BundleDir "sandbox.env") ((@(
    "CTID=`"$Ctid`"",
    "ACTION=`"$Action`"",
    "SERVICE=`"$Service`"",
    "SETTLE=`"$Settle`"",
    "PORT_TIMEOUT=`"$PortTimeout`"",
    "PORTS=`"$($portList -join ' ')`"",
    "WITHOUT=`"$($withoutList -join ' ')`"",
    "NO_BASELINE=`"$(if ($NoBaselinePorts) { '1' } else { '0' })`""
) -join "`n") + "`n")

# ----- Send and run -----
$code = 1
try {
    if (-not (Test-KeyAuth $ProxmoxHost)) {
        if ($ProxmoxPassword -eq "") { throw "No key and no PROXMOX_PASSWORD to log in to root@$ProxmoxHost." }
        Enable-PasswordAuth $ProxmoxPassword
    }
    Write-Host "`nSending to root@$ProxmoxHost..." -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare $RemoteBundleDir on root@$ProxmoxHost" }
    $items = @(Get-ChildItem -Path $BundleDir | ForEach-Object { $_.FullName })
    Invoke-Scp $items "root@${ProxmoxHost}:$RemoteBundleDir/"
    if ($LASTEXITCODE -ne 0) { throw "Could not send the files to root@$ProxmoxHost" }

    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./sandbox-ct.sh"
    $code = $LASTEXITCODE
} finally {
    if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
    try { Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir'" | Out-Null } catch { }
    Disable-PasswordAuth
}
if ($code -ne 0) { throw "sandbox-ct ($Action) on CT $Ctid did not finish (see [ERROR] above)." }
