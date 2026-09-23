param(
    # Host do Proxmox (vazio = PROXMOX_HOST do .env)
    [string]$ProxmoxHost = "",
    # Senha do root do Proxmox. O normal e chave SSH autorizada; sem ela, PROXMOX_PASSWORD do .env.
    [string]$ProxmoxPassword = "",
    [string]$EnvFile = "",
    # Tokens do Proxmox e do OPNsense (fora do git). Copie broker.secrets.env.example.
    [string]$SecretsFile = "",
    # Apaga e recria o CT do broker (perde o token, a chave e o certificado).
    [switch]$RecreateCt,
    # Gera um token novo para o painel (o painel precisa receber o novo: use -ConfigurePanel).
    [switch]$RotateToken,
    # Gera um certificado novo (muda a impressao que o painel fixa: use -ConfigurePanel).
    [switch]$RotateCert,
    # Grava URL, token e impressao do broker no painel (o recurso continua DESLIGADO la).
    # O nome antigo `-ConfigurarPainel` continua valendo pelo Alias: quem ja tem a linha de
    # comando salva nao a perde.
    [Alias('ConfigurarPainel')]
    [switch]$ConfigurePanel,
    # Alem de -ConfigurePanel, LIGA o recurso no painel. So depois de proteger o painel.
    # O nome antigo `-LigarNoPainel` continua valendo pelo Alias: quem ja tem a linha de
    # comando salva nao a perde.
    [Alias('LigarNoPainel')]
    [switch]$EnableOnPanel,
    [string]$RemoteBundleDir = "/root/game-broker-deploy"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# `$ScriptDir` e a pasta DESTE script (onde mora o provision-*.sh irmao). `$RepoRoot` e a
# raiz do repositorio, dois niveis acima, e e de la que saem tools/, lib/, games/ e .env.
# Na raiz os dois eram a mesma coisa por acidente; aqui a diferenca precisa ser dita.
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

# Tudo que o bash do Proxmox le precisa ir em UTF-8 sem BOM e com LF - o CR do Windows
# quebraria o shebang dos .sh e deixaria um \r no fim de cada valor.
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

# Tudo que este deploy leva para o Proxmox e texto (.py, .sh, .env): nao ha binario aqui. Se um
# dia houver, NAO passe por aqui - ReadAllText decodifica como UTF-8 e corrompe (ver o
# comentario em deploy-admin.ps1, foi assim que os icones do painel chegaram quebrados).
function Copy-AsLf([string]$Source, [string]$Dest) {
    Write-LfFile $Dest ([System.IO.File]::ReadAllText($Source))
}

# Valor para o `source` do bash: entre aspas simples, com ' escapado. Sem isto um segredo com
# $, crase ou aspas seria interpretado, e o erro so apareceria como um token "invalido".
function ConvertTo-BashQuoted([string]$Value) {
    if ($Value -match "[\r\n]") { throw "Um valor de configuracao tem quebra de linha (nao suportado)." }
    return "'" + ($Value -replace "'", "'\''") + "'"
}

# ----- Acesso ao Proxmox (mesmo padrao do deploy-admin.ps1) -----
$script:AskPassFile = ""
$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")

# O .gitattributes guarda todo .ps1 em CRLF: toda here-string nasce com \r no fim de cada
# linha, e para o bash do outro lado o \r faz parte do argumento.
function ConvertTo-Lf([string]$Text) { return ($Text -replace "`r", "") }

# O ssh/scp escrevem no stderr mesmo quando dao certo (o `systemctl enable` do Proxmox, por
# exemplo, imprime "Created symlink ..." la). No Windows PowerShell 5.1, com a saida redirecionada
# e $ErrorActionPreference = "Stop", essa linha vira excecao e derruba o deploy em cima de um
# sucesso. O que decide e o codigo de saida ($LASTEXITCODE), que os chamadores conferem.
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
    # "Nao entrou" e resposta esperada aqui, nao erro do deploy.
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

# ----- Configuracao -----
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

# Endereco do painel: so ele pode falar com o broker.
$panelIp = Get-Cfg $cfg "ADMIN_HOST"
if ($panelIp -eq "") {
    $adminCidr = Get-Cfg $cfg "ADMIN_IP_CIDR"
    if ($adminCidr -ne "" -and $adminCidr -ne "dhcp") { $panelIp = ($adminCidr -split '/')[0] }
}
if ($panelIp -eq "") { Write-Host "ADMIN_HOST/ADMIN_IP_CIDR vazios: o broker aceitara qualquer origem (so o token). Defina para restringir ao IP do painel." -ForegroundColor Yellow }

# ----- Confirmacao para ligar o recurso num painel exposto -----
if ($EnableOnPanel) {
    Write-Host "`nATENCAO: ligar o broker no painel da a quem entrar nele o poder de CRIAR containers e ABRIR portas no firewall." -ForegroundColor Yellow
    Write-Host "Se o painel esta na internet (Cloudflare), proteja-o antes: Cloudflare Access ou 2FA." -ForegroundColor Yellow
    $resp = Read-Host "Digite LIGAR para confirmar"
    if ($resp -ne "LIGAR") { throw "Cancelado: o recurso nao foi ligado." }
}

function New-ReleaseBundle([string]$Package) {
    # Empacota aqui, com o Python do repo. O artefato e determinista (ver
    # tools/build-release.py), entao o sha256 que viaja com ele responde "o CT esta com
    # ESTE codigo?", e nao so "o arquivo chegou inteiro?".
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

# ----- Monta o bundle -----
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "game-broker-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null

Copy-AsLf (Join-Path $ScriptDir "provision-broker-lxc.sh") (Join-Path $BundleDir "provision-broker-lxc.sh")
Copy-AsLf (Join-Path $RepoRoot "lib/install-release.sh") (Join-Path $BundleDir "install-release.sh")

# O CODIGO do broker viaja num tar.gz de release; lib/ e games/ continuam soltos porque
# nao sao o pacote Python - sao dados e scripts que o CT le, e o provisionamento ja troca
# os dois por inteiro. O loop que copiava cada .py saiu daqui: era ele que precisava ser
# revisto a cada subpasta nova do pacote, e que deixava modulo renomeado vivo no CT.
$Release = New-ReleaseBundle "gamebroker"
# Copy-Item, nunca Copy-AsLf: um tar.gz passado pelo normalizador de fim de linha e
# decodificado como UTF-8 e chega do outro lado como lixo.
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

# Configuracao NAO secreta: vem do .env, com o padrao que o provisionamento tambem usaria.
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
    BROKER_PORT_FIM = (Get-Cfg $cfg "BROKER_PORT_FIM")
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

# Segredos: so as chaves que o provisionamento conhece (nada de lixo do arquivo vai junto).
$lines = @()
foreach ($k in @("PROXMOX_URL", "PROXMOX_TOKEN", "PROXMOX_NODE", "PROXMOX_POOL", "PROXMOX_STORAGE",
                 "PROXMOX_TEMPLATE_STORAGE", "PROXMOX_TEMPLATE", "PROXMOX_BRIDGE", "PROXMOX_CERT_SHA256",
                 "OPNSENSE_URL", "OPNSENSE_KEY", "OPNSENSE_SECRET", "OPNSENSE_CERT_SHA256", "OPNSENSE_WAN")) {
    $v = Get-Cfg $sec $k
    if ($v -ne "") { $lines += "$k=" + (ConvertTo-BashQuoted $v) }
}
Write-LfFile (Join-Path $BundleDir "broker.secrets.env") (($lines -join "`n") + "`n")

# ----- Envia e executa no Proxmox -----
try {
    Initialize-ProxmoxAuth $ProxmoxHost $ProxmoxPassword
    Write-Host "`nEnviando bundle para root@$ProxmoxHost..." -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

    # scp -r: gamebroker/, lib/ e games/ sao pastas; os arquivos soltos vao junto.
    $items = @(Get-ChildItem -Path $BundleDir | ForEach-Object { $_.FullName })
    Invoke-Scp $items "root@${ProxmoxHost}:$RemoteBundleDir/" -Recurse
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar o bundle para root@$ProxmoxHost" }

    # O bundle leva tokens do Proxmox e do OPNsense: so o root le, e o provisionamento apaga.
    Invoke-Ssh $ProxmoxHost "chmod 700 '$RemoteBundleDir' && chmod 600 '$RemoteBundleDir/broker.secrets.env'" | Out-Null

    Write-Host "Executando o provisionamento no Proxmox...`n" -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./provision-broker-lxc.sh"
    if ($LASTEXITCODE -ne 0) { throw "Provisionamento do broker falhou no host Proxmox (veja a saida acima)" }
} finally {
    # O bundle local tem copia dos segredos: nao deixa sobrando no %TEMP%, nem o remoto.
    if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
    try { Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir'" | Out-Null } catch { }
    Disable-PasswordAuth
}

Write-Host "`nBroker publicado. Confira a IMPRESSAO dos certificados e as REGRAS DE FIREWALL do resumo acima." -ForegroundColor Green
