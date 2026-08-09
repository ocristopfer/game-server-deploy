param(
    # Modo interativo: pergunta cada valor (o .env vira apenas default dos prompts)
    [switch]$Interactive,
    [string]$ProxmoxHost = "",
    [string]$EnvFile = "",
    [string]$RemoteBundleDir = "/root/game-admin-deploy"
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
        # Valor vazio seguido de comentario ("CHAVE=   # nota"): apos o Trim acima o '#'
        # fica no inicio e o split abaixo nao casa, fazendo o texto do comentario virar
        # o valor. Tratar antes, senao "ADMIN_PASSWORD=  # nota" define a nota como senha.
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

function Ask([string]$Label, [string]$Default) {
    if ($Default -ne "") { $answer = Read-Host "$Label [$Default]" } else { $answer = Read-Host "$Label" }
    if ($answer -eq "") { return $Default }
    return $answer
}

# Tudo que o bash do Proxmox le precisa ir em UTF-8 sem BOM e com LF - o CR do Windows
# quebraria o shebang dos .sh e deixaria um \r no fim de cada valor do .env.
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

function Copy-AsLf([string]$Source, [string]$Dest) {
    Write-LfFile $Dest ([System.IO.File]::ReadAllText($Source))
}

# ----- Configuracao -----
if ($EnvFile -eq "") { $EnvFile = Join-Path $ScriptDir ".env" }
$cfg = Read-EnvFile $EnvFile

if ($ProxmoxHost -eq "") { $ProxmoxHost = Get-Cfg $cfg "PROXMOX_HOST" }

if ($Interactive) {
    Write-Host "`n=== Painel administrativo - modo interativo (Enter aceita o valor entre colchetes) ===`n" -ForegroundColor Cyan
    $ProxmoxHost               = Ask "Host Proxmox (ssh root)" $ProxmoxHost
    $cfg["ADMIN_CTID"]         = Ask "ID do container do painel (ADMIN_CTID)" (Get-Cfg $cfg "ADMIN_CTID" "200")
    $cfg["ADMIN_HOSTNAME"]     = Ask "Hostname do CT" (Get-Cfg $cfg "ADMIN_HOSTNAME" "gamepanel")
    $cfg["STORAGE"]            = Ask "Storage do rootfs" (Get-Cfg $cfg "STORAGE")
    $cfg["TEMPLATE_STORAGE"]   = Ask "Storage de templates" (Get-Cfg $cfg "TEMPLATE_STORAGE")
    $cfg["BRIDGE"]             = Ask "Bridge de rede" (Get-Cfg $cfg "BRIDGE")
    $cfg["ADMIN_IP_CIDR"]      = Ask "IP/CIDR do painel (ou 'dhcp')" (Get-Cfg $cfg "ADMIN_IP_CIDR" "dhcp")
    if ($cfg["ADMIN_IP_CIDR"] -ne "dhcp") {
        $cfg["ADMIN_GATEWAY"]  = Ask "Gateway" (Get-Cfg $cfg "ADMIN_GATEWAY" (Get-Cfg $cfg "GATEWAY"))
    }
    $cfg["ADMIN_MEMORY"]       = Ask "Memoria MB" (Get-Cfg $cfg "ADMIN_MEMORY" "512")
    $cfg["ADMIN_CORES"]        = Ask "Cores" (Get-Cfg $cfg "ADMIN_CORES" "1")
    $cfg["ADMIN_DISK_GB"]      = Ask "Disco GB" (Get-Cfg $cfg "ADMIN_DISK_GB" "4")
    $cfg["ADMIN_PORT"]         = Ask "Porta do painel" (Get-Cfg $cfg "ADMIN_PORT" "8080")
    $cfg["ADMIN_USER"]         = Ask "Usuario do painel" (Get-Cfg $cfg "ADMIN_USER" "admin")
    $cfg["ADMIN_PASSWORD"]     = Ask "Senha do painel (vazio = gerar automaticamente)" (Get-Cfg $cfg "ADMIN_PASSWORD")
    $cfg["ADMIN_AUTHORIZE_CTIDS"] = Ask "CTIDs de jogo para ja autorizar (ex: 210 211)" (Get-Cfg $cfg "ADMIN_AUTHORIZE_CTIDS")
    $cfg["ADMIN_ALLOW_SHELL"]  = Ask "Habilitar console/terminal no painel? (1/0)" (Get-Cfg $cfg "ADMIN_ALLOW_SHELL" "1")
    $cfg["ADMIN_ALLOW_FILES"]  = Ask "Habilitar editor de arquivos de config? (1/0)" (Get-Cfg $cfg "ADMIN_ALLOW_FILES" "1")
    $cfg["CT_PASSWORD"]        = Ask "Senha root do CT" (Get-Cfg $cfg "CT_PASSWORD")
    $cfg["RECREATE_ADMIN_CT"]  = Ask "Recriar CT se existir? (0/1)" (Get-Cfg $cfg "RECREATE_ADMIN_CT" "0")
} elseif (-not (Test-Path $EnvFile)) {
    throw "Modo automatico requer o arquivo .env ($EnvFile). Copie o .env.example ou use -Interactive."
}

if ($ProxmoxHost -eq "") { throw "PROXMOX_HOST nao definido (parametro, .env ou modo interativo)." }
foreach ($required in @("ADMIN_CTID", "STORAGE", "BRIDGE")) {
    if ((Get-Cfg $cfg $required) -eq "") {
        throw "Valor obrigatorio ausente: $required (preencha o .env ou use -Interactive)"
    }
}
if ((Get-Cfg $cfg "ADMIN_IP_CIDR" "dhcp") -ne "dhcp" -and
    (Get-Cfg $cfg "ADMIN_GATEWAY" (Get-Cfg $cfg "GATEWAY")) -eq "") {
    throw "ADMIN_GATEWAY (ou GATEWAY) obrigatorio quando ADMIN_IP_CIDR nao e dhcp"
}
if ((Get-Cfg $cfg "ADMIN_CTID") -eq (Get-Cfg $cfg "CTID")) {
    throw "ADMIN_CTID nao pode ser igual ao CTID usado pelos servidores de jogo ($($cfg['CTID']))"
}

# ----- Monta o bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "game-admin-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null

Copy-AsLf (Join-Path $ScriptDir "provision-admin-lxc.sh") (Join-Path $BundleDir "provision-admin-lxc.sh")

$AdminSrc = Join-Path $ScriptDir "admin"
if (-not (Test-Path $AdminSrc)) { throw "Diretorio 'admin' nao encontrado em $ScriptDir" }
foreach ($file in Get-ChildItem -Path $AdminSrc -File -Recurse) {
    $relative = $file.FullName.Substring($AdminSrc.Length).TrimStart('\', '/')
    Copy-AsLf $file.FullName (Join-Path (Join-Path $BundleDir "admin") $relative)
}

$adminKeys = @(
    "ADMIN_CTID","ADMIN_HOSTNAME","ADMIN_IP_CIDR","ADMIN_GATEWAY",
    "ADMIN_MEMORY","ADMIN_CORES","ADMIN_DISK_GB","ADMIN_SWAP","ADMIN_PORT",
    "ADMIN_USER","ADMIN_PASSWORD","ADMIN_ALLOW_SHELL","ADMIN_AUTHORIZE_CTIDS",
    "ADMIN_ALLOW_FILES","ADMIN_FILE_MAX_KB","ADMIN_FILE_PREVIEW_KB",
    "ADMIN_FILE_DOWNLOAD_MAX_MB","ADMIN_FILE_ROOTS","ADMIN_FILE_DEFAULT",
    "ADMIN_TERM_MAX","ADMIN_TERM_IDLE",
    "RECREATE_ADMIN_CT",
    "STORAGE","TEMPLATE_STORAGE","TEMPLATE_PATTERN","BRIDGE","GATEWAY","CT_PASSWORD","TZ"
)
$adminLines = @()
foreach ($key in $adminKeys) {
    $value = Get-Cfg $cfg $key
    if ($value -ne "") { $adminLines += "$key=`"$value`"" }
}
Write-LfFile (Join-Path $BundleDir "admin.env") (($adminLines -join "`n") + "`n")

# ----- Envia e executa no Proxmox -----
Write-Host "`nEnviando bundle do painel para root@$ProxmoxHost..." -ForegroundColor Cyan
ssh "root@$ProxmoxHost" "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

$topLevel = @(
    (Join-Path $BundleDir "provision-admin-lxc.sh"),
    (Join-Path $BundleDir "admin.env")
)
scp @topLevel "root@${ProxmoxHost}:$RemoteBundleDir/"
if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os arquivos do bundle para root@$ProxmoxHost" }

scp -r (Join-Path $BundleDir "admin") "root@${ProxmoxHost}:$RemoteBundleDir/"
if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar a aplicacao para root@$ProxmoxHost" }

Write-Host "Provisionando o painel no Proxmox...`n" -ForegroundColor Cyan
ssh "root@$ProxmoxHost" "cd '$RemoteBundleDir' && bash ./provision-admin-lxc.sh"
if ($LASTEXITCODE -ne 0) { throw "Provisionamento do painel falhou no host Proxmox (veja a saida acima)" }

Write-Host "Painel implantado." -ForegroundColor Green
