param(
    # Interactive mode: asks for each value (the .env becomes just the prompts' defaults)
    [switch]$Interactive,
    # Forces the full path through Proxmox (create/reconfigure the CT). Without it, if the
    # panel container already exists and answers over SSH, the code goes straight to it.
    [switch]$Full,
    [string]$ProxmoxHost = "",
    # Proxmox root password. Without it (and without an authorized key) the deploy cannot get in.
    # The usual thing is to keep it in PROXMOX_PASSWORD in the .env.
    [string]$ProxmoxPassword = "",
    # After logging in by password, authorizes your public key on Proxmox so the
    # next deploys ask for nothing else.
    [switch]$InstallKey,
    # Address of the panel CT for the direct push (empty = deduced from the .env)
    [string]$PanelHost = "",
    [string]$EnvFile = "",
    [string]$RemoteBundleDir = "/root/game-admin-deploy"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# `$ScriptDir` is THIS script's folder (where the sibling provision-*.sh lives). `$RepoRoot`
# is the repository root, two levels up, and that is where tools/, lib/, games/ and .env come from.
# At the root the two were the same thing by accident; here the difference must be spelled out.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

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
        # Empty value followed by a comment ("KEY=   # note"): after the Trim above the '#'
        # is at the start and the split below does not match, so the comment text becomes
        # the value. Handle it first, otherwise "ADMIN_PASSWORD=  # note" sets the note as the password.
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

# Everything the Proxmox bash reads must go as UTF-8 without BOM and with LF - the Windows CR
# would break the shebang of the .sh files and leave a \r at the end of every .env value.
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

function Copy-AsLf([string]$Source, [string]$Dest) {
    Write-LfFile $Dest ([System.IO.File]::ReadAllText($Source))
}

# Copy-AsLf is only for TEXT, and today only text is left for it: the .sh scripts that go
# to the bash on the other side. The panel code travels inside the release tar.gz, which is
# a byte copy.
#
# There used to be a list of "text" extensions here and a Copy-ArquivoDoAdmin that chose
# between it and a binary copy, because the deploy passed EVERY file of the package through this
# path. ReadAllText decodes as UTF-8: every byte outside the ASCII plane becomes the
# replacement character (U+FFFD), and the \r`n -> `n swap also eats a 0x0D that happened
# to fall after a 0x0A. That is how the manifest icons arrived corrupted
# on the server - the PNG signature (89 50 4E 47 0D 0A 1A 0A) became EF BF BD 50 4E 47 0A
# 1A 0A, and Chrome stopped accepting any app icon (error "no-acceptable-icon").
# With the release in a tar, no package file passes through here anymore, and the whole
# class of that defect ceased to exist. Do not bring the loop back.

# ----- Proxmox access: key when there is one, .env password when not -----

# Windows ssh/scp does not accept a password as a parameter, but OpenSSH 8.4+ calls the
# program pointed to by SSH_ASKPASS when SSH_ASKPASS_REQUIRE=force. The file below
# does not store the password: it only echoes an environment variable of this process.
$script:AskPassFile = ""
# Extra options applied to every ssh/scp of the deploy. In password mode they turn off the
# key attempt: without that ssh may fall into the console prompt, which in a
# non-interactive deploy simply hangs.
$script:SshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")

# The .gitattributes stores every .ps1 as CRLF, so every here-string in this file is born
# with a \r at the end of each line. On the other side the reader is bash, and for it the \r is
# part of the argument: 'sleep 3' becomes "invalid interval", 'gamepanel.service' becomes a
# service that does not exist and even the 'set -e' at the top fails - the script goes on broken
# and the deploy ends saying it succeeded. Strip it here, once, instead of in every
# here-string.
function ConvertTo-Lf([string]$Text) { return ($Text -replace "`r", "") }

function Invoke-Ssh([string]$Target, [string]$Command) {
    ssh @script:SshOpts "root@$Target" (ConvertTo-Lf $Command)
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
    # Some builds only consult askpass with DISPLAY set.
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
    # "Did not get in" is an expected answer here; see the comment in Test-PanelReachable.
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

# ----- Direct push to the panel CT (without going through Proxmox) -----

# Panel address: parameter > ADMIN_HOST > the fixed IP from ADMIN_IP_CIDR.
# With ADMIN_IP_CIDR=dhcp it cannot be deduced - set ADMIN_HOST or -PanelHost.
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
    # "Did not answer" is a valid answer here, not a deploy error. In PowerShell
    # 5.1 redirected ssh stderr becomes an exception when ErrorActionPreference is
    # 'Stop', so strict mode is suspended only for this check.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # BatchMode: without an authorized key, fail right away instead of asking for a password.
        # The question is "does this CT already have the release mechanism?", which is why the
        # marker is the `current` symlink -- not the package. A CT older than that mechanism
        # NEEDS the full path: the shortcut only pushes the tarball, and the unit there
        # still points outside `current`, so the release would land without ever being
        # served. The old probe tested the package DIRECTLY in /opt/gamepanel, which was the
        # old layout: after the migration it failed ALWAYS, and every incremental deploy
        # silently turned into a full provisioning -- which goes through Proxmox, runs
        # apt and resets the admin password every time.
        ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new `
            "root@$Target" "test -L /opt/gamepanel/current" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previous
    }
}

# Operator's public key: with it in the CT, the next deploys go direct.
function Get-LocalPubKey([string]$Configured) {
    if ($Configured -ne "") { return $Configured }
    foreach ($name in @("id_ed25519.pub", "id_rsa.pub")) {
        $path = Join-Path $env:USERPROFILE ".ssh\$name"
        if (Test-Path $path) { return ((Get-Content $path -Raw).Trim()) }
    }
    return ""
}

# Native executable whose stderr is NOT an error. The packager writes the dirty-tree warning
# to stderr, and with ErrorActionPreference='Stop' that would become an exception on top of a
# success. What decides here is the exit code.
function Invoke-Native([scriptblock]$Command, [string]$What) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) { throw "Falha ao $What (codigo $LASTEXITCODE)" }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function New-ReleaseBundle([string]$Package) {
    # Packages here, with the repo's Python. The artifact is deterministic (see
    # tools/build-release.py), so the sha256 that travels with it answers "does the CT have
    # THIS code?", and not just "did the file arrive whole?".
    $builder = Join-Path $RepoRoot "tools/build-release.py"
    if (-not (Test-Path $builder)) { throw "tools/build-release.py nao encontrado em $ScriptDir" }
    $dist = Join-Path ([System.IO.Path]::GetTempPath()) "gamepanel-release"
    if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
    Invoke-Native { python $builder $Package --out $dist } "empacotar o release"
    $tarball = Get-ChildItem -Path $dist -Filter "$Package-*.tar.gz" | Select-Object -First 1
    if (-not $tarball) { throw "o empacotador nao gerou nenhum $Package-*.tar.gz em $dist" }
    $sha = ((Get-Content "$($tarball.FullName).sha256" -Raw).Trim() -split "\s+")[0]
    return [pscustomobject]@{ Path = $tarball.FullName; Name = $tarball.Name; Sha = $sha }
}

function Invoke-DirectDeploy([string]$Target, [string]$Port) {
    Write-Host "`nCT do painel encontrado em $Target - enviando o release direto (sem Proxmox)." -ForegroundColor Cyan
    $release = New-ReleaseBundle "gamepanel"
    Write-Host "  $($release.Name)  sha256 $($release.Sha.Substring(0, 12))..." -ForegroundColor DarkGray

    $remoteTmp = "/tmp/gamepanel-release"
    Invoke-Ssh $Target "rm -rf '$remoteTmp' && mkdir -p '$remoteTmp'"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $remoteTmp em root@$Target" }

    # TWO files, and that is all: the package and the installer. The old push copied the whole
    # tree and kept, on the other side, a hand-written list of which folders to delete
    # first - a list that fell behind with every new folder in the package and left a renamed
    # module alive in the container. Here the release is a new folder: there is nothing to leave behind.
    #
    # It is a BYTE copy: the old loop passed every file through a line-ending
    # normalizer, and any PNG caught in that sieve arrived corrupted (the PWA icon did).
    Invoke-Scp @($release.Path, (Join-Path $RepoRoot "lib/install-release.sh")) "root@${Target}:$remoteTmp/"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar o release do painel" }

    # The health probe decides whether the release stays: if it does not answer, the
    # installer points the symlink back to the previous version and exits with an error. Cleanup comes
    # AFTERWARDS, in a separate command, so that the exit code that reaches here is the
    # installer's and not the 'rm''s.
    # wget and not curl: the panel CT does NOT have curl (install_packages installs wget, and
    # not even that was there before -- it was there by chance, from the template). With `curl` here the
    # installer's `eval` failed with "command not found" in all ten attempts, and the
    # rollback undid a release that had come up perfectly: the service answered,
    # only the probe's TOOL did not exist. A false negative is worse than no probe at all.
    # No quotes on purpose: this command travels inside an argument already in single quotes.
    $healthCmd = "wget -q -O /dev/null http://127.0.0.1:$Port/health"
    Invoke-Ssh $Target "bash '$remoteTmp/install-release.sh' gamepanel '$remoteTmp/$($release.Name)' '$($release.Sha)' /opt/gamepanel gamepanel.service '$healthCmd'"
    $installed = ($LASTEXITCODE -eq 0)
    Invoke-Ssh $Target "rm -rf '$remoteTmp'"
    if (-not $installed) {
        Write-Host "`nO painel nao voltou. Ultimas linhas do log:" -ForegroundColor Yellow
        Invoke-Ssh $Target "journalctl -u gamepanel.service --no-pager -n 30"
        throw "gamepanel.service nao ficou ativo apos o envio direto"
    }

    # Confirms via /health that the LIVE process is the one just published. A
    # satisfied "systemctl is-active" is compatible with "systemd restarted the old
    # version": both show green, and only the version tells the two cases apart.
    $live = (Invoke-Ssh $Target "wget -q -O - http://127.0.0.1:$Port/health").Trim()
    Write-Host "`nPainel atualizado em http://${Target}:$Port" -ForegroundColor Green
    Write-Host "  /health: $live" -ForegroundColor DarkGray
    Write-Host "Config (ADMIN_*), recursos do CT e usuario so mudam no modo completo: .\deploy-admin.ps1 -Full" -ForegroundColor DarkGray
}

# ----- Configuration -----
if ($EnvFile -eq "") { $EnvFile = Join-Path $RepoRoot ".env" }
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

# ----- Shortcut: CT already exists and answers? Send the release straight to it -----
# Before the bundle on purpose: this path does not use the bundle, only the tarball that
# Invoke-DirectDeploy packages. Assembling the whole tree here was wasted work on
# every incremental deploy - which is most of them.
if (-not $Interactive -and -not $Full) {
    $TargetPanel = Resolve-PanelHost $cfg $PanelHost
    if (Test-PanelReachable $TargetPanel) {
        Invoke-DirectDeploy $TargetPanel (Get-Cfg $cfg "ADMIN_PORT" "8080")
        return
    }
    if ($TargetPanel -ne "") {
        Write-Host "CT do painel nao respondeu em $TargetPanel - seguindo pelo Proxmox." -ForegroundColor DarkGray
    }
}

# ----- Assembles the full-provisioning bundle -----
# The Proxmox path carries the provisioning script, the .env and the SAME release
# tarball the direct push uses: a single artifact, published the same way on both
# paths. The loop that copied file by file went away together with the hand-written list
# of which folders to clean on the other side.
$BundleDir = Join-Path ([System.IO.Path]::GetTempPath()) "game-admin-bundle"
if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
New-Item -ItemType Directory -Path $BundleDir | Out-Null

Copy-AsLf (Join-Path $ScriptDir "provision-admin-lxc.sh") (Join-Path $BundleDir "provision-admin-lxc.sh")
Copy-AsLf (Join-Path $RepoRoot "lib/install-release.sh") (Join-Path $BundleDir "install-release.sh")
Copy-AsLf (Join-Path $RepoRoot "lib/ct-firewall.sh") (Join-Path $BundleDir "ct-firewall.sh")

$Release = New-ReleaseBundle "gamepanel"
# Copy-Item, never Copy-AsLf: a tar.gz passed through the line-ending normalizer is
# decoded as UTF-8 and arrives on the other side as garbage.
Copy-Item $Release.Path (Join-Path $BundleDir $Release.Name)
Write-LfFile (Join-Path $BundleDir "release.env") (
    "RELEASE_TARBALL='$($Release.Name)'`nRELEASE_SHA256='$($Release.Sha)'`n")
Write-Host "Release do painel: $($Release.Name)" -ForegroundColor DarkGray

# ----- Full path: create/reconfigure the CT through the Proxmox host -----
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

# The operator's key goes along: it is what enables the direct push on the next deploys.
$cfg["ADMIN_SSH_PUBKEY"] = Get-LocalPubKey (Get-Cfg $cfg "ADMIN_SSH_PUBKEY")
if ((Get-Cfg $cfg "ADMIN_SSH_PUBKEY") -eq "") {
    Write-Host "Sem chave publica SSH local: o CT nao vai aceitar envio direto (rode ssh-keygen)." -ForegroundColor DarkGray
}

if ($ProxmoxPassword -eq "") { $ProxmoxPassword = Get-Cfg $cfg "PROXMOX_PASSWORD" }
$usingPassword = Initialize-ProxmoxAuth $ProxmoxHost $ProxmoxPassword
if ($usingPassword -and $InstallKey) {
    Install-KeyOnProxmox $ProxmoxHost (Get-Cfg $cfg "ADMIN_SSH_PUBKEY")
}

$adminKeys = @(
    "ADMIN_CTID","ADMIN_HOSTNAME","ADMIN_IP_CIDR","ADMIN_GATEWAY","ADMIN_SSH_PUBKEY",
    "ADMIN_MEMORY","ADMIN_CORES","ADMIN_DISK_GB","ADMIN_SWAP","ADMIN_PORT",
    "ADMIN_USER","ADMIN_PASSWORD","ADMIN_ALLOW_SHELL","ADMIN_AUTHORIZE_CTIDS",
    "ADMIN_ALLOW_FILES","ADMIN_REQUIRE_2FA","ADMIN_WEBAUTHN_ORIGIN","ADMIN_LANG","ADMIN_FILE_MAX_KB","ADMIN_FILE_PREVIEW_KB",
    "ADMIN_FILE_DOWNLOAD_MAX_MB","ADMIN_FILE_ROOTS","ADMIN_FILE_DEFAULT",
    "ADMIN_TERM_MAX","ADMIN_TERM_IDLE","ADMIN_METRICS_TTL",
    "ADMIN_QUERY_TIMEOUT","ADMIN_PLAYERS_TTL",
    "RECREATE_ADMIN_CT","ADMIN_FIREWALL_SOURCES","CT_FIREWALL",
    "STORAGE","TEMPLATE_STORAGE","TEMPLATE_PATTERN","BRIDGE","GATEWAY","CT_PASSWORD","TZ"
)
$adminLines = @()
foreach ($key in $adminKeys) {
    $value = Get-Cfg $cfg $key
    if ($value -ne "") { $adminLines += "$key=`"$value`"" }
}
Write-LfFile (Join-Path $BundleDir "admin.env") (($adminLines -join "`n") + "`n")

# ----- Send and run on Proxmox -----
try {
    Write-Host "`nEnviando bundle do painel para root@$ProxmoxHost..." -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "rm -rf '$RemoteBundleDir' && mkdir -p '$RemoteBundleDir'"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar $RemoteBundleDir em root@$ProxmoxHost" }

    # A flat folder, no subfolders at all: six files, one of them the tarball. The recursive
    # push of the tree left this place - it was what required checking, with every new folder
    # in the package, whether -Recurse still reached everything.
    $topLevel = @(
        (Join-Path $BundleDir "provision-admin-lxc.sh"),
        (Join-Path $BundleDir "install-release.sh"),
        (Join-Path $BundleDir "ct-firewall.sh"),
        (Join-Path $BundleDir "release.env"),
        (Join-Path $BundleDir $Release.Name),
        (Join-Path $BundleDir "admin.env")
    )
    Invoke-Scp $topLevel "root@${ProxmoxHost}:$RemoteBundleDir/"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao enviar os arquivos do bundle para root@$ProxmoxHost" }

    Write-Host "Provisionando o painel no Proxmox...`n" -ForegroundColor Cyan
    Invoke-Ssh $ProxmoxHost "cd '$RemoteBundleDir' && bash ./provision-admin-lxc.sh"
    if ($LASTEXITCODE -ne 0) { throw "Provisionamento do painel falhou no host Proxmox (veja a saida acima)" }

    Write-Host "Painel implantado." -ForegroundColor Green
    if ($usingPassword -and -not $InstallKey) {
        Write-Host "Dica: rode com -InstallKey uma vez para autorizar sua chave e parar de usar senha." -ForegroundColor DarkGray
    }
} finally {
    # The password leaves the environment even if the deploy fails midway.
    Disable-PasswordAuth
}
