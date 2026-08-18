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
    # Nao cadastra o servidor no painel ao final do deploy
    [switch]$NoRegister,
    [string]$ProxmoxHost = "",
    # Senha do root do Proxmox. O normal e deixar em PROXMOX_PASSWORD no .env.
    [string]$ProxmoxPassword = "",
    # Autoriza sua chave publica no Proxmox e para de depender de senha nos proximos deploys
    [switch]$InstallKey,
    [string]$EnvFile = "",
    [string]$RemoteBundleDir = "/root/game-deploy"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Read-EnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { return @{} }
    return (Read-EnvLines (Get-Content $Path))
}

# Mesmo parser para o texto do games/<jogo>.env, que no deploy generico (-AppId) e
# gerado em memoria e nunca chega a existir como arquivo.
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

# ----- Acesso ao Proxmox: chave quando existe, senha do .env quando nao -----
# Mesmo mecanismo do deploy-admin.ps1. O ssh/scp do Windows nao aceita senha por
# parametro, mas o OpenSSH 8.4+ chama o programa apontado por SSH_ASKPASS quando
# SSH_ASKPASS_REQUIRE=force. O arquivo criado abaixo nao guarda a senha: ele so ecoa
# uma variavel de ambiente deste processo.
$script:AskPassFile = ""
# Opcoes aplicadas a TODO ssh/scp do deploy. No modo senha elas desligam a tentativa
# por chave: sem isso o ssh pode cair no prompt do console, que num deploy longo
# significa parar no meio esperando alguem digitar.
$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")
# Host a que a autenticacao acima se aplica (o Proxmox). O CT do painel e outra maquina,
# com outra senha de root - mandar a senha do Proxmox para ele so geraria falha de auth.
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
    # Alguns builds so consultam o askpass com DISPLAY definido.
    if (-not $env:DISPLAY) { $env:DISPLAY = "localhost:0" }
    $script:SshOpts += @("-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password")
}

function Disable-PasswordAuth {
    foreach ($nome in @("GAMEDEPLOY_SSH_PASSWORD", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE")) {
        Remove-Item "env:$nome" -ErrorAction SilentlyContinue
    }
    if ($script:AskPassFile -ne "" -and (Test-Path $script:AskPassFile)) {
        Remove-Item $script:AskPassFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-KeyAuth([string]$Target) {
    # "Nao entrou" e resposta esperada aqui, nao erro do deploy - por isso a preferencia
    # relaxada (ver o comentario do bloco de ssh auxiliar mais abaixo).
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

# Chave publica do operador: com ela autorizada no Proxmox, os deploys seguintes nao
# pedem senha nenhuma - nem uma vez por chamada de ssh.
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

# ----- ssh auxiliar (consultas e cadastro no painel) -----
# No PowerShell 5.1 o stderr de um executavel nativo vira excecao quando
# ErrorActionPreference e 'Stop' - inclusive quando o comando termina com sucesso.
# Por isso toda chamada daqui relaxa a preferencia: o erro de verdade e o $LASTEXITCODE.

# ssh/scp do fluxo principal: carregam o $script:SshOpts, que e onde vive a
# autenticacao (chave ou senha via askpass).
function Invoke-Ssh([string]$Target, [string]$Command) {
    $opcoes = Get-SshOptsFor $Target
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        ssh @opcoes "root@$Target" $Command
    } finally {
        $ErrorActionPreference = $anterior
    }
}

function Invoke-Scp([string[]]$Sources, [string]$Destination) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        scp @script:SshOpts @Sources $Destination
    } finally {
        $ErrorActionPreference = $anterior
    }
}

# -Batch para destinos que so valem a pena por chave (o CT do painel): sem chave
# autorizada a consulta falha na hora em vez de parar o deploy num prompt de senha.
function Invoke-SshQuery([string]$Target, [string]$Command, [switch]$Batch) {
    $opcoes = @(Get-SshOptsFor $Target) + @("-o", "ConnectTimeout=10")
    if ($Batch) { $opcoes += @("-o", "BatchMode=yes") }
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $saida = ssh @opcoes "root@$Target" $Command 2>$null
    } finally {
        $ErrorActionPreference = $anterior
    }
    return $saida
}

# Igual a de cima, mas com a saida indo para a tela (o cadastro no painel responde
# "servidor 'X' cadastrado").
function Invoke-SshLive([string]$Target, [string]$Command) {
    $opcoes = Get-SshOptsFor $Target
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        ssh @opcoes "root@$Target" $Command
    } finally {
        $ErrorActionPreference = $anterior
    }
}

# Primeira linha util de uma saida que pode vir como array de linhas
function Get-FirstLine($Output) {
    if ($null -eq $Output) { return "" }
    return (($Output | Select-Object -First 1) -as [string]).Trim()
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
# O mesmo texto que vai no bundle, ja como mapa: dele saem GAME_KEY e, no fim do
# deploy, os dados do cadastro no painel (portas, config, contagem de jogadores).
$jogo = Read-EnvText $GameEnvContent
$GameKey = Get-Cfg $jogo "GAME_KEY" $Game
$GameSuffix = Get-GameSuffix $GameKey
$Display = Get-Cfg $jogo "GAME_DISPLAY_NAME" $GameKey

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
$SteamAnon = (Get-Cfg $jogo "STEAM_ANONYMOUS" "1") -ne "0"
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

# Autenticacao decidida UMA vez, antes de qualquer ssh/scp: por chave se ela ja estiver
# autorizada, senao pela senha do .env via askpass. Sem isso cada ssh do deploy abre seu
# proprio prompt - e este script chama ssh meia duzia de vezes por jogo.
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

# ----- Painel: onde ele roda e qual e a chave publica dele -----
# Caminhos fixos do CT do painel (provision-admin-lxc.sh). O cadastro roda como o
# usuario do painel, nao como root: o sqlite cria os arquivos -wal/-shm ao lado do
# banco, e criados por root o painel (que roda como gamepanel) perderia a escrita.
$PanelApp = "/opt/gamepanel/app.py"
$PanelUser = "gamepanel"
$PanelPubKeyPath = "/etc/gamepanel/id_ed25519.pub"
$AdminCtid = Get-Cfg $cfg "ADMIN_CTID"

# Endereco do painel para falar direto com ele (painel fora deste Proxmox).
function Resolve-PanelHost($Map) {
    $fromEnv = Get-Cfg $Map "ADMIN_HOST"
    if ($fromEnv -ne "") { return $fromEnv }
    $cidr = Get-Cfg $Map "ADMIN_IP_CIDR"
    if ($cidr -ne "" -and $cidr -ne "dhcp") { return (Get-IpOnly $cidr) }
    return ""
}
$PanelHost = Resolve-PanelHost $cfg

# Sem PANEL_PUBKEY o CT nasce sem deixar o painel entrar, e o cadastro do fim do deploy
# apareceria na tela como um servidor que nao responde. A chave e do proprio painel,
# entao da para busca-la em vez de exigir que ela esteja copiada no .env.
if ((Get-Cfg $cfg "PANEL_PUBKEY") -eq "") {
    $lida = ""
    if ($AdminCtid -ne "") {
        $lida = Get-FirstLine (Invoke-SshQuery $ProxmoxHost "pct exec $AdminCtid -- cat $PanelPubKeyPath")
        if ($LASTEXITCODE -ne 0) { $lida = "" }
    }
    if ($lida -eq "" -and $PanelHost -ne "") {
        $lida = Get-FirstLine (Invoke-SshQuery $PanelHost "cat $PanelPubKeyPath" -Batch)
        if ($LASTEXITCODE -ne 0) { $lida = "" }
    }
    if ($lida -ne "") {
        $cfg["PANEL_PUBKEY"] = $lida
        Write-Host "Chave publica do painel lida do proprio painel (PANEL_PUBKEY vazio no .env)." -ForegroundColor DarkGray
    } else {
        Write-Host ("Sem PANEL_PUBKEY e sem painel acessivel: o CT nao vai aceitar o painel por SSH. " +
                    "Suba o painel (.\deploy-admin.ps1) ou preencha PANEL_PUBKEY no .env.") -ForegroundColor Yellow
    }
}

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
Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

# scp em vez de 'tar -czf - | ssh tar -xzf -': o PowerShell converte para texto o que
# passa por um pipe entre dois executaveis nativos, o que corrompe o stream do tar.gz.
$bundleFiles = @(Get-ChildItem -Path $BundleDir -File | ForEach-Object { $_.FullName })
Invoke-Scp $bundleFiles "root@${ProxmoxHost}:$RemoteBundleDir/"
if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os arquivos do bundle para root@$ProxmoxHost" }

# deploy.env leva senha do CT e, em jogos como o dayz, a senha da conta Steam
Invoke-Ssh $ProxmoxHost "chmod 700 '$RemoteBundleDir' && chmod 600 '$RemoteBundleDir/deploy.env'" | Out-Null

Write-Host "Executando provisionamento no Proxmox (o download do jogo pode demorar)...`n" -ForegroundColor Cyan
Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./provision-game-lxc.sh"
if ($LASTEXITCODE -ne 0) { throw "Provisionamento falhou no host Proxmox (veja a saida acima)" }

# O bundle local tem copia do deploy.env (senhas) - nao deixa sobrando no %TEMP%
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }

# ----- Cadastro no painel -----
# Mesmo caminho do deploy em Docker: o painel se cadastra pela propria CLI
# (app.py --register-server), que e idempotente - num redeploy ele atualiza o
# servidor existente em vez de duplicar.

# Escapa um valor para virar um argumento entre aspas simples no shell remoto.
function ConvertTo-ShQuoted([string]$Value) {
    return "'" + ($Value -replace "'", "'\''") + "'"
}

# Endereco do CT do jogo: com IP fixo ja sabemos; com dhcp so o CT sabe.
function Get-CtIp([string]$Cidr, [string]$Ctid) {
    if ($Cidr -ne "dhcp") { return (Get-IpOnly $Cidr) }
    $saida = Get-FirstLine (Invoke-SshQuery $ProxmoxHost "pct exec $Ctid -- hostname -I")
    if ($LASTEXITCODE -ne 0 -or $saida -eq "") { return "" }
    return (($saida -split '\s+')[0])
}

$registrado = $false
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
            "--game-port", (Get-Cfg $jogo "GAME_PORTS"),
            "--query-port", (Get-Cfg $jogo "QUERY_PORT" "0"),
            "--config-path", (Get-Cfg $jogo "CONFIG_PATH"),
            "--config-files", (Get-Cfg $jogo "CONFIG_FILES"),
            # Pastas de save que a tela Backups do painel guarda. Num redeploy o painel
            # mantem o que ja estava la: quem ajustou pela tela nao perde o ajuste.
            "--backup-paths", (Get-Cfg $jogo "BACKUP_PATHS"),
            "--player-source", (Get-Cfg $jogo "PLAYER_SOURCE"),
            # Contagem pelo log: padroes e, quando o nome so existe em arquivo proprio
            # (o .ADM do DayZ), o caminho dele.
            "--join-re", (Get-Cfg $jogo "JOIN_RE"),
            "--leave-re", (Get-Cfg $jogo "LEAVE_RE"),
            "--log-path", (Get-Cfg $jogo "LOG_PATH"),
            "--notes", "CT $($cfg['CTID']) no Proxmox $ProxmoxHost (deploy-game.ps1)."
        )
        $partes = @("runuser", "-u", $PanelUser, "--", "python3", $PanelApp)
        foreach ($valor in $cmdArgs) { $partes += (ConvertTo-ShQuoted $valor) }
        $registerCmd = ($partes -join " ")

        # 1) Pelo proprio host Proxmox, que e o caminho que sempre existe num deploy LXC:
        #    o painel mora num CT do mesmo host e nao precisa aceitar SSH de fora.
        if ($AdminCtid -ne "") {
            Invoke-SshQuery $ProxmoxHost "pct exec $AdminCtid -- test -f $PanelApp" | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "`nCadastrando $Display no painel (CT $AdminCtid)..." -ForegroundColor Cyan
                Invoke-SshLive $ProxmoxHost "pct exec $AdminCtid -- $registerCmd"
                $registrado = ($LASTEXITCODE -eq 0)
            } else {
                Write-Host "Painel nao encontrado no CT $AdminCtid ($PanelApp)." -ForegroundColor DarkGray
            }
        }
        # 2) Painel fora deste Proxmox (ADMIN_HOST/ADMIN_IP_CIDR), falando direto com ele.
        if (-not $registrado -and $PanelHost -ne "") {
            Invoke-SshQuery $PanelHost "test -f $PanelApp" -Batch | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "`nCadastrando $Display no painel ($PanelHost)..." -ForegroundColor Cyan
                Invoke-SshLive $PanelHost $registerCmd
                $registrado = ($LASTEXITCODE -eq 0)
            }
        }
        if (-not $registrado) {
            Write-Host "Nao consegui cadastrar no painel - use a tela Adicionar (host $CtIp, servico $GameKey.service)." -ForegroundColor Yellow
        }
    }
}

# Tira a senha do ambiente e apaga o askpass do %TEMP%. Nao fica para o proximo comando
# desta mesma janela do PowerShell.
Disable-PasswordAuth

Write-Host "Deploy finalizado." -ForegroundColor Green
if ($registrado) {
    Write-Host "Servidor cadastrado no painel: $Display ($CtIp) - a tela Config ja abre o arquivo do jogo." -ForegroundColor Green
}
if ($UsandoSenha -and -not $InstallKey) {
    Write-Host "Dica: rode uma vez com -InstallKey para autorizar sua chave e parar de usar senha." -ForegroundColor DarkGray
}
