param(
    # Host do Proxmox (vazio = PROXMOX_HOST do .env)
    [string]$ProxmoxHost = "",
    [string]$EnvFile = "",
    # So estes CTs (ex.: "302,303"). Vazio = painel, broker e todos os jogos do broker.
    [string]$Only = "",
    # CTs de jogo feitos pelo deploy-game.ps1 (fora do broker), ex.: "210,211".
    [string]$ExtraGameCts = "",
    # So mostra as regras que cada CT receberia; nao aplica nada.
    [switch]$DryRun,
    [string]$RemoteBundleDir = "/root/ct-firewall-deploy"
)

# Aplica o firewall de dentro do CT (lib/ct-firewall.sh) nos containers que ja existem.
# Os CTs novos ja nascem com ele; este script e para os de antes. Quem faz o trabalho e o
# apply-firewall.sh, no host: tudo por `pct`, cada CT testado depois, e desligado sozinho se
# o teste falhar. Emergencia em qualquer CT: pct exec <CT> -- ct-firewall off

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

# O bash do Proxmox le tudo isto: UTF-8 sem BOM e LF, senao o \r entra em cada valor.
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

# ssh/scp escrevem no stderr mesmo dando certo; no PowerShell 5.1 isso viraria excecao.
# Quem decide e o $LASTEXITCODE.
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

# Lista "302, 303" -> "302,303", recusando o que nao for numero de CT.
function ConvertTo-CtList([string]$Raw, [string]$Name) {
    $items = @($Raw -split '[,\s]+' | Where-Object { $_ -ne "" })
    foreach ($i in $items) { if ($i -notmatch '^\d{2,9}$') { throw "${Name}: '$i' nao e um numero de CT." } }
    return ($items -join ",")
}

# ----- Configuracao -----
$cfg = Read-EnvFile $EnvFile
if ($ProxmoxHost -eq "") { $ProxmoxHost = Get-Cfg $cfg "PROXMOX_HOST" }
if ($ProxmoxHost -eq "") { throw "PROXMOX_HOST nao definido no .env (ou use -ProxmoxHost)." }
$panelCtid = Get-Cfg $cfg "ADMIN_CTID"
if ($panelCtid -eq "") { throw "ADMIN_CTID nao definido no .env: e do painel que os testes partem." }

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
# games/*.env: as portas dos jogos legados, que nao estao no banco do broker.
foreach ($f in Get-ChildItem -Path (Join-Path $RepoRoot "games") -Filter "*.env") {
    Copy-AsLf $f.FullName (Join-Path (Join-Path $BundleDir "games") $f.Name)
}
Write-LfFile (Join-Path $BundleDir "fw.env") (($fwLines -join "`n") + "`n")

# ----- Envia e executa -----
try {
    Write-Host "`nEnviando para root@$ProxmoxHost..." -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }
    $items = @(Get-ChildItem -Path $BundleDir | ForEach-Object { $_.FullName })
    Invoke-Scp $items "root@${ProxmoxHost}:$RemoteBundleDir/" -Recurse
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os arquivos para root@$ProxmoxHost" }

    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./apply-firewall.sh"
    $code = $LASTEXITCODE
} finally {
    if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
    try { Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir'" | Out-Null } catch { }
}
if ($code -ne 0) { throw "Algum CT falhou (veja FALHOU no resumo acima). Os que falharam ficaram SEM firewall, nao trancados." }
