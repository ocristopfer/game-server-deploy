param(
    # Game name (file games/<name>.env), e.g. dragonwilds
    [string]$Game = "",
    # OR: Steam App ID of the dedicated server (generic deploy)
    [string]$AppId = "",
    # Brings up/updates the admin panel in Docker
    [switch]$Panel,
    # Stops and removes the target container (the volumes with the game are NOT deleted)
    [switch]$Down,
    # Recreates the container from scratch (same as -Down followed by the deploy)
    [switch]$Recreate,
    # Do not register the server in the panel at the end
    [switch]$NoRegister,
    # Revalidates the game files through SteamCMD in this deploy
    [switch]$UpdateOnStart,
    # Steam Guard code (games whose server requires a Steam account, e.g. dayz)
    [string]$SteamGuardCode = "",
    # Target Docker. Empty = the local daemon. Remote: "ssh://root@10.20.0.50"
    [string]$DockerHost = "",
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# `$ScriptDir` is the folder of THIS script (where the sibling provision-*.sh lives). `$RepoRoot`
# is the repository root, two levels up, and tools/, lib/, games/ and .env come from there.
# At the root the two were the same thing by accident; here the difference must be explicit.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$StackDir = Join-Path $RepoRoot "docker\stacks"
$Network = "games"
$PanelContainer = "gamepanel"

# ----------------------------------------------------------------- utilities

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

# Suffix of the per-game keys of the .env: dragonwilds -> MEMORY_DRAGONWILDS
function Get-GameSuffix([string]$Key) {
    return (($Key.ToUpper()) -replace '[^A-Z0-9]', '_')
}

# Reads the .env key preferring the game-specific version (KEY_<GAME>)
function Get-Scoped($Map, [string]$Key, [string]$Suffix, [string]$Default = "") {
    $scopedKey = "${Key}_${Suffix}"
    if ($Map.ContainsKey($scopedKey) -and $Map[$scopedKey] -ne "") { return $Map[$scopedKey] }
    return (Get-Cfg $Map $Key $Default)
}

# The files are read by docker/bash: UTF-8 without BOM and with LF
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

# docker writes progress to stderr, and PowerShell 5.1 turns an executable's stderr
# into a terminating error whenever the output is being redirected (it is enough for the
# user to do "... | Tee-Object log.txt"). So every docker call goes through
# here, with the preference relaxed: the real error is the exit code.
# Returns nothing on purpose: docker output goes straight to the screen (build and
# download are slow) and the caller checks $LASTEXITCODE, which is global.
function Invoke-DockerLive([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & docker @Arguments } finally { $ErrorActionPreference = $previous }
}

# Silent query (the output comes back as text, stderr is discarded).
function Invoke-DockerQuery([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $output = & docker @Arguments 2>$null } finally { $ErrorActionPreference = $previous }
    return $output
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "O comando 'docker' nao foi encontrado. Instale o Docker Desktop ou o docker CLI."
    }
    Invoke-DockerQuery @("version", "--format", "{{.Server.Version}}") | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $target = "daemon local"
        if ($env:DOCKER_HOST) { $target = $env:DOCKER_HOST }
        throw "Nao consegui falar com o Docker ($target). O Docker Desktop esta rodando?"
    }
}

# Existence queries use 'ls --filter' instead of 'inspect' because an 'inspect'
# that does not find the object exits with an error - and here "does not exist" is an expected answer.
function Test-Network([string]$Name) {
    $found = Invoke-DockerQuery @("network", "ls", "--filter", "name=^$Name$", "--format", "{{.Name}}")
    return ($found -contains $Name)
}

function Test-Container([string]$Name) {
    $found = Invoke-DockerQuery @("ps", "-a", "--filter", "name=^$Name$", "--format", "{{.Names}}")
    return ($found -contains $Name)
}

function Ensure-Network {
    if (-not (Test-Network $Network)) {
        Write-Host "Criando a rede docker '$Network' (painel e jogos conversam por ela)" -ForegroundColor DarkGray
        Invoke-DockerLive @("network", "create", $Network)
        if ($LASTEXITCODE -ne 0) { throw "Falha ao criar a rede docker '$Network'" }
    }
}

function Invoke-Compose([string]$File, [string]$Project, [string[]]$ComposeArgs) {
    $all = @("compose", "-f", $File, "-p", $Project) + $ComposeArgs
    Invoke-DockerLive $all
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') falhou (veja a saida acima)"
    }
}

# Panel public key: without it the game container is born without letting the panel in
function Get-PanelPubKey($Map) {
    if (Test-Container $PanelContainer) {
        $fromContainer = Invoke-DockerQuery @("exec", $PanelContainer, "cat", "/etc/gamepanel/id_ed25519.pub")
        if ($fromContainer) { return ($fromContainer | Select-Object -First 1).Trim() }
    }
    return (Get-Cfg $Map "PANEL_PUBKEY")
}

# ------------------------------------------------------------------- context

if ($EnvFile -eq "") { $EnvFile = Join-Path $RepoRoot ".env" }
$cfg = Read-EnvFile $EnvFile

if ($DockerHost -eq "") { $DockerHost = Get-Cfg $cfg "DOCKER_HOST" }
if ($DockerHost -ne "") {
    $env:DOCKER_HOST = $DockerHost
    Write-Host "Docker de destino: $DockerHost" -ForegroundColor Cyan
}

if (-not $Panel -and $Game -eq "" -and $AppId -eq "") {
    $available = Get-ChildItem (Join-Path $RepoRoot "games") -Filter "*.env" |
        Where-Object { $_.Name -ne "_template.env" } |
        ForEach-Object { $_.BaseName }
    Write-Host "Informe -Game <nome>, -AppId <steam_app_id> ou -Panel." -ForegroundColor Yellow
    Write-Host ("Jogos disponiveis: " + ($available -join ", "))
    Write-Host ""
    Write-Host "Exemplos:"
    Write-Host "  .\deploy-docker.ps1 -Panel                 # sobe o painel"
    Write-Host "  .\deploy-docker.ps1 -Game palworld         # sobe o jogo e o cadastra no painel"
    Write-Host "  .\deploy-docker.ps1 -Game dayz -SteamGuardCode 12345"
    Write-Host "  .\deploy-docker.ps1 -Game palworld -Down   # para o servidor (o mundo fica no volume)"
    exit 1
}

Assert-Docker
if (-not (Test-Path $StackDir)) { New-Item -ItemType Directory -Path $StackDir | Out-Null }
Ensure-Network

# -------------------------------------------------------------------- panel

if ($Panel) {
    $port = Get-Cfg $cfg "ADMIN_PORT" "8080"
    $user = Get-Cfg $cfg "ADMIN_USER" "admin"
    $password = Get-Cfg $cfg "ADMIN_PASSWORD"
    $generated = $false
    if ($password -eq "") {
        $password = -join ((48..57) + (97..122) + (65..90) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
        $generated = $true
    }

    $file = Join-Path $StackDir "panel.yml"
    Write-LfFile $file @"
# Generated by deploy-docker.ps1 - edit the .env and run it again instead of changing this.
services:
  panel:
    build:
      context: ../..
      dockerfile: docker/panel/Dockerfile.prod
    image: gamepanel:local
    container_name: $PanelContainer
    restart: unless-stopped
    ports:
      - "${porta}:8080"
    environment:
      PANEL_USER: "$user"
      PANEL_PASSWORD: "$password"
      TZ: "$(Get-Cfg $cfg 'TZ' 'America/Sao_Paulo')"
      GAMEPANEL_ALLOW_SHELL: "$(Get-Cfg $cfg 'ADMIN_ALLOW_SHELL' '1')"
      GAMEPANEL_ALLOW_FILES: "$(Get-Cfg $cfg 'ADMIN_ALLOW_FILES' '1')"
      GAMEPANEL_FILE_DEFAULT: "$(Get-Cfg $cfg 'ADMIN_FILE_DEFAULT' '/opt/game')"
      GAMEPANEL_FILE_ROOTS: "$(Get-Cfg $cfg 'ADMIN_FILE_ROOTS' '/opt/game,/home/steam')"
    volumes:
      - gamepanel-conf:/etc/gamepanel
      - gamepanel-data:/var/lib/gamepanel
    networks:
      - $Network

volumes:
  gamepanel-conf:
  gamepanel-data:

networks:
  ${Network}:
    external: true
"@

    if ($Down) {
        Invoke-Compose $file "gamepanel" @("down")
        Write-Host "Painel parado (os cadastros e a chave SSH ficam nos volumes)." -ForegroundColor Green
        if ($Game -eq "" -and $AppId -eq "") { exit 0 }
    } else {
        if ($Recreate) { Invoke-Compose $file "gamepanel" @("down") }
        Write-Host "`nSubindo o painel..." -ForegroundColor Cyan
        Invoke-Compose $file "gamepanel" @("up", "-d", "--build")

        Write-Host ""
        Write-Host "Painel: http://localhost:$port" -ForegroundColor Green
        Write-Host "Usuario: $user"
        if ($generated) {
            Write-Host "Senha gerada agora: $password" -ForegroundColor Yellow
            Write-Host "(preencha ADMIN_PASSWORD no .env para fixar uma senha sua)"
        }
        $pub = Get-PanelPubKey $cfg
        if ($pub -ne "") { Write-Host "Chave SSH do painel: $pub" -ForegroundColor DarkGray }
    }
}

if ($Game -eq "" -and $AppId -eq "") { exit 0 }

# --------------------------------------------------------------------- game

if ($Game -ne "") {
    $GameEnvPath = Join-Path $RepoRoot "games\$Game.env"
    if (-not (Test-Path $GameEnvPath)) { throw "Jogo desconhecido: $Game (esperado: $GameEnvPath)" }
    $GameEnvRel = "games/$Game.env"
} else {
    if ($AppId -notmatch '^\d+$') { throw "AppId invalido: $AppId" }
    # Generic deploy: generates a minimal games/app<id>.env so the image has something to copy.
    $Game = "app$AppId"
    $GameEnvPath = Join-Path $RepoRoot "games\$Game.env"
    $GameEnvRel = "games/$Game.env"
    if (-not (Test-Path $GameEnvPath)) {
        Write-LfFile $GameEnvPath @"
# Generated by deploy-docker.ps1 -AppId $AppId (start script detected automatically).
GAME_KEY=$Game
GAME_DISPLAY_NAME="Steam App $AppId"
STEAM_APP_ID=$AppId
START_SCRIPT=
START_ARGS=""
GAME_PORT=
GAME_PORTS=""
"@
        Write-Host "Criado $GameEnvRel - ajuste portas e START_SCRIPT se precisar." -ForegroundColor DarkGray
    }
}

$game = Read-EnvFile $GameEnvPath
$GameKey = Get-Cfg $game "GAME_KEY" $Game
$GameSuffix = Get-GameSuffix $GameKey
$Display = Get-Cfg $game "GAME_DISPLAY_NAME" $GameKey
$Container = "game-$GameKey"
$composeProject = "game-$GameKey"
$file = Join-Path $StackDir "$GameKey.yml"
$secretsPath = Join-Path $StackDir "$GameKey.secret.env"

if ($Down) {
    if (Test-Path $file) {
        Invoke-Compose $file $composeProject @("down")
        Write-Host "$Display parado. O mundo continua no volume ${Container}-data." -ForegroundColor Green
    } else {
        Write-Host "Nao ha stack gerada para $GameKey ($file)." -ForegroundColor Yellow
    }
    exit 0
}

# ----- ports -----
$portLines = @()
$portList = Get-Cfg $game "GAME_PORTS"
foreach ($entry in ($portList -split '\s+')) {
    if ($entry -eq "") { continue }
    $parts = $entry -split '/'
    $portNumber = $parts[0]
    $proto = if ($parts.Count -gt 1) { $parts[1] } else { "tcp" }
    if ($portNumber -notmatch '^\d+$') { continue }
    $portLines += "      - `"${portNumber}:${portNumber}/${proto}`""
}
# SSH port published only when requested: by default the panel gets in through the internal network.
$sshPort = Get-Scoped $cfg "SSH_PORT" $GameSuffix
if ($sshPort -ne "") { $portLines += "      - `"${sshPort}:22`"" }
if ($portLines.Count -eq 0) { $portLines += "      []" }

# ----- resources and options -----
$memory = Get-Scoped $cfg "MEMORY" $GameSuffix (Get-Cfg $game "RECOMMENDED_MEMORY" "4096")
$cores = Get-Scoped $cfg "CORES" $GameSuffix (Get-Cfg $game "RECOMMENDED_CORES" "2")
$tz = Get-Cfg $cfg "TZ" "America/Sao_Paulo"
$autoUpdate = Get-Scoped $cfg "AUTO_UPDATE" $GameSuffix "1"
$updateTime = Get-Cfg $cfg "UPDATE_TIME" "06:00"
# Name differs from the -UpdateOnStart parameter: in PowerShell $x and $X are the SAME
# variable, and assigning text over a [switch] breaks immediately.
$revalidate = Get-Cfg $cfg "UPDATE_ON_START" "0"
if ($UpdateOnStart) { $revalidate = "1" }

$pub = Get-PanelPubKey $cfg
if ($pub -eq "") {
    Write-Host "Aviso: nao achei a chave publica do painel." -ForegroundColor Yellow
    Write-Host "  Suba o painel antes (.\deploy-docker.ps1 -Panel) ou preencha PANEL_PUBKEY no .env;" -ForegroundColor Yellow
    Write-Host "  sem ela o painel nao consegue entrar neste container." -ForegroundColor Yellow
}

# ----- Steam account (games with STEAM_ANONYMOUS=0, today dayz) -----
$anon = (Get-Cfg $game "STEAM_ANONYMOUS" "1") -ne "0"
$secretLines = @()
if (-not $anon) {
    $steamUser = Get-Cfg $cfg "STEAM_USER"
    $steamPass = Get-Cfg $cfg "STEAM_PASS"
    if ($SteamGuardCode -ne "") { $cfg["STEAM_GUARD_CODE"] = $SteamGuardCode }
    $steamGuard = Get-Cfg $cfg "STEAM_GUARD_CODE"
    if ($steamUser -eq "" -or $steamPass -eq "") {
        throw ("O servidor de $GameKey nao sai por login anonimo na Steam. " +
               "Preencha STEAM_USER e STEAM_PASS no .env (conta que POSSUA o jogo).")
    }
    if ($steamGuard -eq "") {
        Write-Host "Sem SteamGuardCode: se a conta usa Steam Guard o login falha - repita com -SteamGuardCode <codigo>." -ForegroundColor Yellow
    }
    $secretLines += "STEAM_USER=$steamUser"
    $secretLines += "STEAM_PASS=$steamPass"
    if ($steamGuard -ne "") { $secretLines += "STEAM_GUARD_CODE=$steamGuard" }
}
# The file always exists (compose requires the declared env_file), but it only has content
# when the game needs an account. It is in .gitignore.
Write-LfFile $secretsPath (($secretLines -join "`n") + "`n")

# ----- stack -----
Write-LfFile $file @"
# Generated by deploy-docker.ps1 for $Display - edit the .env/games/$GameKey.env and run it
# again instead of changing this.
services:
  game:
    build:
      context: ../..
      dockerfile: docker/gameserver/Dockerfile
      args:
        GAME_ENV: $GameEnvRel
    image: gamesrv-${GameKey}:local
    container_name: $Container
    hostname: $GameKey
    restart: unless-stopped
    # The game must receive the TERM and have time to save the world before the KILL.
    stop_grace_period: 120s
    ports:
$($portLines -join "`n")
    environment:
      TZ: "$tz"
      PANEL_PUBKEY: "$pub"
      AUTO_UPDATE: "$autoUpdate"
      UPDATE_TIME: "$updateTime"
      UPDATE_ON_START: "$revalidate"
    env_file:
      - $GameKey.secret.env
    volumes:
      - ${Container}-data:/opt/game
      - ${Container}-steam:/home/steam
      # Backups the panel takes, and the Mods screen's environment overlay: both outlive a
      # recreated container (docker/gameserver/Dockerfile says why).
      - ${Container}-backups:/var/backups/gamepanel
      - ${Container}-modenv:/etc/gamepanel/game-env
    mem_limit: ${memory}m
    cpus: $cores
    networks:
      - $Network

volumes:
  ${Container}-data:
  ${Container}-steam:
  ${Container}-backups:
  ${Container}-modenv:

networks:
  ${Network}:
    external: true
"@

if ($Recreate) { Invoke-Compose $file $composeProject @("down") }

Write-Host "`nSubindo $Display (o primeiro deploy baixa o jogo inteiro, pode demorar)..." -ForegroundColor Cyan
Invoke-Compose $file $composeProject @("up", "-d", "--build")

Write-Host "`nAcompanhe a instalacao com:" -ForegroundColor DarkGray
Write-Host "  docker logs -f $Container"

# ----- registration in the panel -----
$registered = $false
if (-not $NoRegister) {
    if (Test-Container $PanelContainer) {
        $cmdArgs = @(
            # /opt/gamepanel/gamepanel: that is where Dockerfile.prod copies the package.
            "exec", $PanelContainer, "python3", "/opt/gamepanel/gamepanel/app.py",
            "--register-server", $Display,
            "--server-host", $Container,
            "--service", "$GameKey.service",
            # The gameserver image refuses root over SSH: the panel logs in as gamepanel and
            # reaches steam and the root helpers through sudo (lib/ct-panel-access.sh).
            "--ssh-user", "gamepanel",
            "--game-port", (Get-Cfg $game "GAME_PORTS"),
            "--query-port", (Get-Cfg $game "QUERY_PORT" "0"),
            "--config-path", (Get-Cfg $game "CONFIG_PATH"),
            "--config-files", (Get-Cfg $game "CONFIG_FILES"),
            # Save folders that the panel's Backups screen keeps. On a redeploy the panel
            # keeps what was already there: whoever adjusted it on screen does not lose it.
            "--backup-paths", (Get-Cfg $game "BACKUP_PATHS"),
            "--player-source", (Get-Cfg $game "PLAYER_SOURCE"),
            # Slots: the panel shows "2/6" when the count does not bring the total (log, connections).
            "--max-players", $(if ((Get-Cfg $game "MAX_PLAYERS") -match '^\d+$') { (Get-Cfg $game "MAX_PLAYERS") } else { "0" }),
            # Counting by log: patterns and, when the name only exists in a separate file
            # (DayZ's .ADM), its path.
            "--join-re", (Get-Cfg $game "JOIN_RE"),
            "--leave-re", (Get-Cfg $game "LEAVE_RE"),
            "--log-path", (Get-Cfg $game "LOG_PATH"),
            "--notes", "Container Docker $Container (deploy-docker.ps1)."
        )
        Invoke-DockerLive $cmdArgs
        if ($LASTEXITCODE -eq 0) {
            $registered = $true
        } else {
            Write-Host "Nao consegui cadastrar no painel (faca pela tela Adicionar)." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Painel nao encontrado no Docker: cadastre o servidor manualmente ou rode -Panel." -ForegroundColor DarkGray
    }
}

# ----- summary -----
$portasTexto = if ($portList -ne "") { $portList } else { "(nao definidas para este jogo)" }
Write-Host ""
Write-Host "========================================================================"
Write-Host " Deploy em Docker concluido: $Display"
Write-Host "========================================================================"
Write-Host ""
Write-Host "Container : $Container (rede $Network, ${memory}MB, $cores cpu)"
Write-Host "Volumes   : ${Container}-data (jogo), ${Container}-steam (conta/Steam), ${Container}-backups e ${Container}-modenv"
Write-Host "Portas    : $portasTexto"
$notes = Get-Cfg $game "PORT_NOTES"
if ($notes -ne "") { Write-Host "Nota      : $notes" }
$hints = Get-Cfg $game "CONFIG_HINT"
if ($hints -ne "") { Write-Host "Config    : $hints" }
Write-Host ""
if ($registered) {
    Write-Host "Ja cadastrado no painel - a tela Config abre o arquivo do jogo direto." -ForegroundColor Green
}
Write-Host "Atalhos dentro do container:"
Write-Host "  docker exec $Container game-status"
Write-Host "  docker exec $Container game-logs -n 50"
Write-Host "  docker exec $Container update-game"
Write-Host "  docker exec -it $Container bash"
Write-Host ""
