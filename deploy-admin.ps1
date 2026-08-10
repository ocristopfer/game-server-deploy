param(
    # Modo interativo: pergunta cada valor (o .env vira apenas default dos prompts)
    [switch]$Interactive,
    # Forca o caminho completo pelo Proxmox (criar/reconfigurar o CT). Sem isto, se o
    # container do painel ja existe e responde por SSH, o codigo vai direto para ele.
    [switch]$Full,
    [string]$ProxmoxHost = "",
    # Senha do root do Proxmox. Sem isto (e sem chave autorizada) o deploy nao entra.
    # O normal e deixar em PROXMOX_PASSWORD no .env.
    [string]$ProxmoxPassword = "",
    # Depois de entrar por senha, autoriza sua chave publica no Proxmox para os
    # proximos deploys nao pedirem mais nada.
    [switch]$InstallKey,
    # Endereco do CT do painel para o envio direto (vazio = deduz do .env)
    [string]$PanelHost = "",
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

# ----- Acesso ao Proxmox: chave quando existe, senha do .env quando nao -----

# O ssh/scp do Windows nao aceita senha por parametro, mas o OpenSSH 8.4+ chama o
# programa apontado por SSH_ASKPASS quando SSH_ASKPASS_REQUIRE=force. O arquivo abaixo
# nao guarda a senha: ele so ecoa uma variavel de ambiente deste processo.
$script:AskPassFile = ""
# Opcoes extras aplicadas a todo ssh/scp do deploy. No modo senha elas desligam a
# tentativa por chave: sem isso o ssh pode cair no prompt do console, que num deploy
# nao-interativo simplesmente trava.
$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")

function Invoke-Ssh([string]$Target, [string]$Command) {
    ssh @script:SshOpts "root@$Target" $Command
}

function Invoke-Scp([string[]]$Sources, [string]$Destination, [switch]$Recurse) {
    if ($Recurse) {
        scp @script:SshOpts -r @Sources $Destination
    } else {
        scp @script:SshOpts @Sources $Destination
    }
}

function Enable-PasswordAuth([string]$Password) {
    if ($script:AskPassFile -eq "") {
        $script:AskPassFile = Join-Path $env:TEMP "gamepanel-askpass.cmd"
        Set-Content -Path $script:AskPassFile -Encoding ASCII -Value @(
            "@echo off",
            "echo %GAMEPANEL_SSH_PASSWORD%"
        )
    }
    $env:GAMEPANEL_SSH_PASSWORD = $Password
    $env:SSH_ASKPASS = $script:AskPassFile
    $env:SSH_ASKPASS_REQUIRE = "force"
    # Alguns builds so consultam o askpass com DISPLAY definido.
    if (-not $env:DISPLAY) { $env:DISPLAY = "localhost:0" }
    $script:SshOpts += @("-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password")
}

function Disable-PasswordAuth {
    foreach ($nome in @("GAMEPANEL_SSH_PASSWORD", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE")) {
        Remove-Item "env:$nome" -ErrorAction SilentlyContinue
    }
    if ($script:AskPassFile -ne "" -and (Test-Path $script:AskPassFile)) {
        Remove-Item $script:AskPassFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-KeyAuth([string]$Target) {
    # "Nao entrou" e resposta esperada aqui; ver o comentario em Test-PanelReachable.
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new `
            "root@$Target" "true" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $anterior
    }
}

function Initialize-ProxmoxAuth([string]$Target, [string]$Password) {
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

function Install-KeyOnProxmox([string]$Target, [string]$PubKey) {
    if ($PubKey -eq "") {
        Write-Host "Sem chave publica local para instalar (rode ssh-keygen)." -ForegroundColor Yellow
        return
    }
    Write-Host "Autorizando sua chave publica em root@$Target..." -ForegroundColor Cyan
    $cmd = "install -d -m 700 /root/.ssh && touch /root/.ssh/authorized_keys && " +
           "chmod 600 /root/.ssh/authorized_keys && " +
           "grep -qF '$PubKey' /root/.ssh/authorized_keys || echo '$PubKey' >> /root/.ssh/authorized_keys"
    Invoke-Ssh $Target $cmd
    if ($LASTEXITCODE -ne 0) { throw "Falha ao autorizar a chave em root@$Target" }
    Write-Host "Pronto: os proximos deploys entram por chave, sem senha." -ForegroundColor Green
}

# ----- Envio direto para o CT do painel (sem passar pelo Proxmox) -----

# Endereco do painel: parametro > ADMIN_HOST > o IP fixo do ADMIN_IP_CIDR.
# Com ADMIN_IP_CIDR=dhcp nao da para deduzir - informe ADMIN_HOST ou -PanelHost.
function Resolve-PanelHost($Map, [string]$Override) {
    if ($Override -ne "") { return $Override }
    $fromEnv = Get-Cfg $Map "ADMIN_HOST"
    if ($fromEnv -ne "") { return $fromEnv }
    $cidr = Get-Cfg $Map "ADMIN_IP_CIDR"
    if ($cidr -ne "" -and $cidr -ne "dhcp") { return ($cidr -split '/')[0] }
    return ""
}

function Test-PanelReachable([string]$Target) {
    if ($Target -eq "") { return $false }
    # "Nao respondeu" e uma resposta valida aqui, nao um erro do deploy. No PowerShell
    # 5.1 o stderr do ssh redirecionado vira excecao quando ErrorActionPreference e
    # 'Stop', entao o modo estrito fica suspenso so nesta checagem.
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # BatchMode: sem chave autorizada, falha na hora em vez de pedir senha.
        ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new `
            "root@$Target" "test -f /opt/gamepanel/app.py" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $anterior
    }
}

# Chave publica do operador: com ela no CT, os proximos deploys vao direto.
function Get-LocalPubKey([string]$Configured) {
    if ($Configured -ne "") { return $Configured }
    foreach ($name in @("id_ed25519.pub", "id_rsa.pub")) {
        $path = Join-Path $env:USERPROFILE ".ssh\$name"
        if (Test-Path $path) { return ((Get-Content $path -Raw).Trim()) }
    }
    return ""
}

function Invoke-DirectDeploy([string]$Target, [string]$SrcDir, [string]$Port) {
    $remoteTmp = "/tmp/gamepanel-deploy"
    Write-Host "`nCT do painel encontrado em $Target - enviando o codigo direto (sem Proxmox)." -ForegroundColor Cyan

    Invoke-Ssh $Target "rm -rf '$remoteTmp' && mkdir -p '$remoteTmp/templates' '$remoteTmp/static'"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $remoteTmp em root@$Target" }

    Invoke-Scp @((Join-Path $SrcDir "app.py")) "root@${Target}:$remoteTmp/app.py"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar app.py" }
    Invoke-Scp @((Join-Path $SrcDir "templates\*.html")) "root@${Target}:$remoteTmp/templates/"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os templates" }
    Invoke-Scp @((Join-Path $SrcDir "static\*")) "root@${Target}:$remoteTmp/static/"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os estaticos" }

    # Troca o conteudo e reinicia. Os templates antigos sao removidos para um arquivo
    # renomeado no repo nao continuar vivo no container.
    $install = @'
set -e
install -d /opt/gamepanel/templates /opt/gamepanel/static
rm -f /opt/gamepanel/templates/*.html /opt/gamepanel/static/*
install -m 0644 /tmp/gamepanel-deploy/app.py /opt/gamepanel/app.py
install -m 0644 /tmp/gamepanel-deploy/templates/*.html /opt/gamepanel/templates/
install -m 0644 /tmp/gamepanel-deploy/static/* /opt/gamepanel/static/
chown -R root:root /opt/gamepanel
rm -rf /tmp/gamepanel-deploy
systemctl restart gamepanel.service
sleep 3
systemctl is-active --quiet gamepanel.service
'@
    Invoke-Ssh $Target $install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nO painel nao voltou. Ultimas linhas do log:" -ForegroundColor Yellow
        Invoke-Ssh $Target "journalctl -u gamepanel.service --no-pager -n 30"
        throw "gamepanel.service nao ficou ativo apos o envio direto"
    }

    $count = (Invoke-Ssh $Target "ls /opt/gamepanel/templates | wc -l").Trim()
    Write-Host "`nPainel atualizado em http://${Target}:$Port ($count templates)." -ForegroundColor Green
    Write-Host "Config (ADMIN_*), recursos do CT e usuario so mudam no modo completo: .\deploy-admin.ps1 -Full" -ForegroundColor DarkGray
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

# ----- Atalho: CT ja existe e responde? Manda o codigo direto para ele -----
if (-not $Interactive -and -not $Full) {
    $TargetPanel = Resolve-PanelHost $cfg $PanelHost
    if (Test-PanelReachable $TargetPanel) {
        Invoke-DirectDeploy $TargetPanel (Join-Path $BundleDir "admin") (Get-Cfg $cfg "ADMIN_PORT" "8080")
        return
    }
    if ($TargetPanel -ne "") {
        Write-Host "CT do painel nao respondeu em $TargetPanel - seguindo pelo Proxmox." -ForegroundColor DarkGray
    }
}

# ----- Caminho completo: cria/reconfigura o CT pelo host Proxmox -----
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

# Chave do operador vai junto: e ela que habilita o envio direto nos proximos deploys.
$cfg["ADMIN_SSH_PUBKEY"] = Get-LocalPubKey (Get-Cfg $cfg "ADMIN_SSH_PUBKEY")
if ((Get-Cfg $cfg "ADMIN_SSH_PUBKEY") -eq "") {
    Write-Host "Sem chave publica SSH local: o CT nao vai aceitar envio direto (rode ssh-keygen)." -ForegroundColor DarkGray
}

if ($ProxmoxPassword -eq "") { $ProxmoxPassword = Get-Cfg $cfg "PROXMOX_PASSWORD" }
$UsandoSenha = Initialize-ProxmoxAuth $ProxmoxHost $ProxmoxPassword
if ($UsandoSenha -and $InstallKey) {
    Install-KeyOnProxmox $ProxmoxHost (Get-Cfg $cfg "ADMIN_SSH_PUBKEY")
}

$adminKeys = @(
    "ADMIN_CTID","ADMIN_HOSTNAME","ADMIN_IP_CIDR","ADMIN_GATEWAY","ADMIN_SSH_PUBKEY",
    "ADMIN_MEMORY","ADMIN_CORES","ADMIN_DISK_GB","ADMIN_SWAP","ADMIN_PORT",
    "ADMIN_USER","ADMIN_PASSWORD","ADMIN_ALLOW_SHELL","ADMIN_AUTHORIZE_CTIDS",
    "ADMIN_ALLOW_FILES","ADMIN_FILE_MAX_KB","ADMIN_FILE_PREVIEW_KB",
    "ADMIN_FILE_DOWNLOAD_MAX_MB","ADMIN_FILE_ROOTS","ADMIN_FILE_DEFAULT",
    "ADMIN_TERM_MAX","ADMIN_TERM_IDLE","ADMIN_METRICS_TTL",
    "ADMIN_QUERY_TIMEOUT","ADMIN_PLAYERS_TTL",
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
try {
    Write-Host "`nEnviando bundle do painel para root@$ProxmoxHost..." -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

    $topLevel = @(
        (Join-Path $BundleDir "provision-admin-lxc.sh"),
        (Join-Path $BundleDir "admin.env")
    )
    Invoke-Scp $topLevel "root@${ProxmoxHost}:$RemoteBundleDir/"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os arquivos do bundle para root@$ProxmoxHost" }

    Invoke-Scp @((Join-Path $BundleDir "admin")) "root@${ProxmoxHost}:$RemoteBundleDir/" -Recurse
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar a aplicacao para root@$ProxmoxHost" }

    Write-Host "Provisionando o painel no Proxmox...`n" -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./provision-admin-lxc.sh"
    if ($LASTEXITCODE -ne 0) { throw "Provisionamento do painel falhou no host Proxmox (veja a saida acima)" }

    Write-Host "Painel implantado." -ForegroundColor Green
    if ($UsandoSenha -and -not $InstallKey) {
        Write-Host "Dica: rode com -InstallKey uma vez para autorizar sua chave e parar de usar senha." -ForegroundColor DarkGray
    }
} finally {
    # A senha some do ambiente mesmo se o deploy falhar no meio.
    Disable-PasswordAuth
}
