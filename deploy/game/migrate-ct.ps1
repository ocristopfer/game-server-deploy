param(
    # The game CT to migrate (e.g. 210).
    [Parameter(Mandatory = $true)]
    [string]$Ctid,
    # The game's systemd unit. Empty = the single service in the CT that runs as steam.
    [string]$Service = "",
    # Install and switch the panel to gamepanel, but keep root login open (a first, softer step).
    [switch]$NoLock,
    [string]$ProxmoxHost = "",
    [string]$ProxmoxPassword = "",
    [string]$EnvFile = "",
    [string]$RemoteBundleDir = "/root/ct-migrate"
)

# Moves ONE existing game container from root access to the unprivileged `gamepanel` user
# (docs/security-hardening.md, phase 8). The work is done by migrate-ct.sh on the Proxmox host,
# through pct: root is only locked after the new path was proven from the panel container, and
# the way back is always `pct enter <CTID>`.

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
if ($Ctid -notmatch '^\d{2,9}$') { throw "-Ctid '$Ctid' is not a CT number." }
if ($Service -ne "" -and $Service -notmatch '^[A-Za-z0-9@._-]+$') { throw "-Service '$Service' is invalid." }
$cfg = Read-EnvFile $EnvFile
if ($ProxmoxHost -eq "") { $ProxmoxHost = Get-Cfg $cfg "PROXMOX_HOST" }
if ($ProxmoxHost -eq "") { throw "PROXMOX_HOST is not set in .env (or use -ProxmoxHost)." }
$panelCtid = Get-Cfg $cfg "ADMIN_CTID"
if ($panelCtid -eq "") { throw "ADMIN_CTID is not set in .env: the new path is tested from the panel." }
if ($ProxmoxPassword -eq "") { $ProxmoxPassword = Get-Cfg $cfg "PROXMOX_PASSWORD" }

# ----- Bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "ct-migrate-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null
Copy-AsLf (Join-Path $ScriptDir "migrate-ct.sh") (Join-Path $BundleDir "migrate-ct.sh")
Copy-AsLf (Join-Path $RepoRoot "lib/ct-panel-access.sh") (Join-Path $BundleDir "ct-panel-access.sh")
Write-LfFile (Join-Path $BundleDir "migrate.env") ((@(
    "CTID=`"$Ctid`"",
    "SERVICE=`"$Service`"",
    "PANEL_CTID=`"$panelCtid`"",
    "LOCK=`"$(if ($NoLock) { '0' } else { '1' })`""
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
    if ($LASTEXITCODE -ne 0) { throw "Failed to prepare $RemoteBundleDir on root@$ProxmoxHost" }
    $items = @(Get-ChildItem -Path $BundleDir | ForEach-Object { $_.FullName })
    Invoke-Scp $items "root@${ProxmoxHost}:$RemoteBundleDir/"
    if ($LASTEXITCODE -ne 0) { throw "Failed to send the files to root@$ProxmoxHost" }

    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./migrate-ct.sh"
    $code = $LASTEXITCODE
} finally {
    if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
    try { Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir'" | Out-Null } catch { }
    Disable-PasswordAuth
}
if ($code -ne 0) { throw "The migration of CT $Ctid stopped (see [ERROR] above). Emergency: pct enter $Ctid" }
