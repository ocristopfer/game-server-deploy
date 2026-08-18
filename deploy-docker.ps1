param(
    # Nome do jogo (arquivo games/<nome>.env), ex: dragonwilds
    [string]$Game = "",
    # OU: App ID do servidor dedicado na Steam (deploy generico)
    [string]$AppId = "",
    # Sobe/atualiza o painel administrativo em Docker
    [switch]$Panel,
    # Para e remove o container do alvo (os volumes com o jogo NAO sao apagados)
    [switch]$Down,
    # Recria o container do zero (equivale a -Down seguido do deploy)
    [switch]$Recreate,
    # Nao cadastra o servidor no painel ao final
    [switch]$NoRegister,
    # Revalida os arquivos do jogo pelo SteamCMD neste deploy
    [switch]$UpdateOnStart,
    # Codigo do Steam Guard (jogos cujo servidor exige conta Steam, ex: dayz)
    [string]$SteamGuardCode = "",
    # Docker de destino. Vazio = o daemon local. Remoto: "ssh://root@192.168.1.50"
    [string]$DockerHost = "",
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StackDir = Join-Path $ScriptDir "docker\stacks"
$Network = "games"
$PanelContainer = "gamepanel"

# ---------------------------------------------------------------- utilidades

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

# Sufixo das chaves por jogo do .env: dragonwilds -> MEMORY_DRAGONWILDS
function Get-GameSuffix([string]$Key) {
    return (($Key.ToUpper()) -replace '[^A-Z0-9]', '_')
}

# Le a chave do .env preferindo a versao especifica do jogo (CHAVE_<JOGO>)
function Get-Scoped($Map, [string]$Key, [string]$Suffix, [string]$Default = "") {
    $escopada = "${Key}_${Suffix}"
    if ($Map.ContainsKey($escopada) -and $Map[$escopada] -ne "") { return $Map[$escopada] }
    return (Get-Cfg $Map $Key $Default)
}

# Os arquivos sao lidos pelo docker/bash: UTF-8 sem BOM e com LF
function Write-LfFile([string]$Path, [string]$Content) {
    $normalized = $Content -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($Path, $normalized, (New-Object System.Text.UTF8Encoding($false)))
}

# O docker escreve progresso no stderr, e o PowerShell 5.1 transforma stderr de
# executavel em erro terminante sempre que a saida esta sendo redirecionada (basta o
# usuario fazer "... | Tee-Object log.txt"). Por isso toda chamada ao docker passa por
# aqui, com a preferencia relaxada: o erro de verdade e o codigo de saida.
# Nao devolve nada de proposito: a saida do docker vai direto para a tela (build e
# download sao demorados) e quem chama confere o $LASTEXITCODE, que e global.
function Invoke-DockerLive([string[]]$Argumentos) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & docker @Argumentos } finally { $ErrorActionPreference = $anterior }
}

# Consulta silenciosa (a saida volta como texto, o stderr e descartado).
function Invoke-DockerQuery([string[]]$Argumentos) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $saida = & docker @Argumentos 2>$null } finally { $ErrorActionPreference = $anterior }
    return $saida
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "O comando 'docker' nao foi encontrado. Instale o Docker Desktop ou o docker CLI."
    }
    Invoke-DockerQuery @("version", "--format", "{{.Server.Version}}") | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $alvo = "daemon local"
        if ($env:DOCKER_HOST) { $alvo = $env:DOCKER_HOST }
        throw "Nao consegui falar com o Docker ($alvo). O Docker Desktop esta rodando?"
    }
}

# As consultas de existencia usam 'ls --filter' em vez de 'inspect' porque um 'inspect'
# que nao acha o objeto sai com erro - e aqui "nao existe" e resposta esperada.
function Test-Network([string]$Nome) {
    $achado = Invoke-DockerQuery @("network", "ls", "--filter", "name=^$Nome$", "--format", "{{.Name}}")
    return ($achado -contains $Nome)
}

function Test-Container([string]$Nome) {
    $achado = Invoke-DockerQuery @("ps", "-a", "--filter", "name=^$Nome$", "--format", "{{.Names}}")
    return ($achado -contains $Nome)
}

function Ensure-Network {
    if (-not (Test-Network $Network)) {
        Write-Host "Criando a rede docker '$Network' (painel e jogos conversam por ela)" -ForegroundColor DarkGray
        Invoke-DockerLive @("network", "create", $Network)
        if ($LASTEXITCODE -ne 0) { throw "Falha ao criar a rede docker '$Network'" }
    }
}

function Invoke-Compose([string]$File, [string]$Project, [string[]]$ComposeArgs) {
    $todos = @("compose", "-f", $File, "-p", $Project) + $ComposeArgs
    Invoke-DockerLive $todos
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') falhou (veja a saida acima)"
    }
}

# Chave publica do painel: sem ela o container do jogo nasce sem deixar o painel entrar
function Get-PanelPubKey($Map) {
    if (Test-Container $PanelContainer) {
        $doContainer = Invoke-DockerQuery @("exec", $PanelContainer, "cat", "/etc/gamepanel/id_ed25519.pub")
        if ($doContainer) { return ($doContainer | Select-Object -First 1).Trim() }
    }
    return (Get-Cfg $Map "PANEL_PUBKEY")
}

# ------------------------------------------------------------------ contexto

if ($EnvFile -eq "") { $EnvFile = Join-Path $ScriptDir ".env" }
$cfg = Read-EnvFile $EnvFile

if ($DockerHost -eq "") { $DockerHost = Get-Cfg $cfg "DOCKER_HOST" }
if ($DockerHost -ne "") {
    $env:DOCKER_HOST = $DockerHost
    Write-Host "Docker de destino: $DockerHost" -ForegroundColor Cyan
}

if (-not $Panel -and $Game -eq "" -and $AppId -eq "") {
    $available = Get-ChildItem (Join-Path $ScriptDir "games") -Filter "*.env" |
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

# ------------------------------------------------------------------- painel

if ($Panel) {
    $porta = Get-Cfg $cfg "ADMIN_PORT" "8080"
    $usuario = Get-Cfg $cfg "ADMIN_USER" "admin"
    $senha = Get-Cfg $cfg "ADMIN_PASSWORD"
    $gerada = $false
    if ($senha -eq "") {
        $senha = -join ((48..57) + (97..122) + (65..90) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
        $gerada = $true
    }

    $arquivo = Join-Path $StackDir "panel.yml"
    Write-LfFile $arquivo @"
# Gerado por deploy-docker.ps1 - edite o .env e rode de novo em vez de mexer aqui.
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
      PANEL_USER: "$usuario"
      PANEL_PASSWORD: "$senha"
      TZ: "$(Get-Cfg $cfg 'TZ' 'America/Sao_Paulo')"
      GAMEPANEL_ALLOW_SHELL: "$(Get-Cfg $cfg 'ADMIN_ALLOW_SHELL' '1')"
      GAMEPANEL_ALLOW_FILES: "$(Get-Cfg $cfg 'ADMIN_ALLOW_FILES' '1')"
      GAMEPANEL_FILE_DEFAULT: "$(Get-Cfg $cfg 'ADMIN_FILE_DEFAULT' '/opt/game')"
      GAMEPANEL_FILE_ROOTS: "$(Get-Cfg $cfg 'ADMIN_FILE_ROOTS' '/')"
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
        Invoke-Compose $arquivo "gamepanel" @("down")
        Write-Host "Painel parado (os cadastros e a chave SSH ficam nos volumes)." -ForegroundColor Green
        if ($Game -eq "" -and $AppId -eq "") { exit 0 }
    } else {
        if ($Recreate) { Invoke-Compose $arquivo "gamepanel" @("down") }
        Write-Host "`nSubindo o painel..." -ForegroundColor Cyan
        Invoke-Compose $arquivo "gamepanel" @("up", "-d", "--build")

        Write-Host ""
        Write-Host "Painel: http://localhost:$porta" -ForegroundColor Green
        Write-Host "Usuario: $usuario"
        if ($gerada) {
            Write-Host "Senha gerada agora: $senha" -ForegroundColor Yellow
            Write-Host "(preencha ADMIN_PASSWORD no .env para fixar uma senha sua)"
        }
        $pub = Get-PanelPubKey $cfg
        if ($pub -ne "") { Write-Host "Chave SSH do painel: $pub" -ForegroundColor DarkGray }
    }
}

if ($Game -eq "" -and $AppId -eq "") { exit 0 }

# --------------------------------------------------------------------- jogo

if ($Game -ne "") {
    $GameEnvPath = Join-Path $ScriptDir "games\$Game.env"
    if (-not (Test-Path $GameEnvPath)) { throw "Jogo desconhecido: $Game (esperado: $GameEnvPath)" }
    $GameEnvRel = "games/$Game.env"
} else {
    if ($AppId -notmatch '^\d+$') { throw "AppId invalido: $AppId" }
    # Deploy generico: gera um games/app<id>.env minimo para a imagem ter o que copiar.
    $Game = "app$AppId"
    $GameEnvPath = Join-Path $ScriptDir "games\$Game.env"
    $GameEnvRel = "games/$Game.env"
    if (-not (Test-Path $GameEnvPath)) {
        Write-LfFile $GameEnvPath @"
# Gerado por deploy-docker.ps1 -AppId $AppId (script de start detectado automaticamente).
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

$jogo = Read-EnvFile $GameEnvPath
$GameKey = Get-Cfg $jogo "GAME_KEY" $Game
$GameSuffix = Get-GameSuffix $GameKey
$Display = Get-Cfg $jogo "GAME_DISPLAY_NAME" $GameKey
$Container = "game-$GameKey"
$Projeto = "game-$GameKey"
$arquivo = Join-Path $StackDir "$GameKey.yml"
$segredos = Join-Path $StackDir "$GameKey.secret.env"

if ($Down) {
    if (Test-Path $arquivo) {
        Invoke-Compose $arquivo $Projeto @("down")
        Write-Host "$Display parado. O mundo continua no volume ${Container}-data." -ForegroundColor Green
    } else {
        Write-Host "Nao ha stack gerada para $GameKey ($arquivo)." -ForegroundColor Yellow
    }
    exit 0
}

# ----- portas -----
$portas = @()
$listaPortas = Get-Cfg $jogo "GAME_PORTS"
foreach ($entrada in ($listaPortas -split '\s+')) {
    if ($entrada -eq "") { continue }
    $partes = $entrada -split '/'
    $numero = $partes[0]
    $proto = if ($partes.Count -gt 1) { $partes[1] } else { "tcp" }
    if ($numero -notmatch '^\d+$') { continue }
    $portas += "      - `"${numero}:${numero}/${proto}`""
}
# Porta SSH publicada so quando pedida: por padrao o painel entra pela rede interna.
$sshPort = Get-Scoped $cfg "SSH_PORT" $GameSuffix
if ($sshPort -ne "") { $portas += "      - `"${sshPort}:22`"" }
if ($portas.Count -eq 0) { $portas += "      []" }

# ----- recursos e opcoes -----
$memoria = Get-Scoped $cfg "MEMORY" $GameSuffix (Get-Cfg $jogo "RECOMMENDED_MEMORY" "4096")
$cores = Get-Scoped $cfg "CORES" $GameSuffix (Get-Cfg $jogo "RECOMMENDED_CORES" "2")
$tz = Get-Cfg $cfg "TZ" "America/Sao_Paulo"
$autoUpdate = Get-Scoped $cfg "AUTO_UPDATE" $GameSuffix "1"
$updateTime = Get-Cfg $cfg "UPDATE_TIME" "06:00"
# Nome diferente do parametro -UpdateOnStart: no PowerShell $x e $X sao a MESMA
# variavel, e atribuir texto por cima de um [switch] quebra na hora.
$revalidar = Get-Cfg $cfg "UPDATE_ON_START" "0"
if ($UpdateOnStart) { $revalidar = "1" }

$pub = Get-PanelPubKey $cfg
if ($pub -eq "") {
    Write-Host "Aviso: nao achei a chave publica do painel." -ForegroundColor Yellow
    Write-Host "  Suba o painel antes (.\deploy-docker.ps1 -Panel) ou preencha PANEL_PUBKEY no .env;" -ForegroundColor Yellow
    Write-Host "  sem ela o painel nao consegue entrar neste container." -ForegroundColor Yellow
}

# ----- conta Steam (jogos com STEAM_ANONYMOUS=0, hoje o dayz) -----
$anon = (Get-Cfg $jogo "STEAM_ANONYMOUS" "1") -ne "0"
$linhasSegredo = @()
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
    $linhasSegredo += "STEAM_USER=$steamUser"
    $linhasSegredo += "STEAM_PASS=$steamPass"
    if ($steamGuard -ne "") { $linhasSegredo += "STEAM_GUARD_CODE=$steamGuard" }
}
# O arquivo existe sempre (o compose exige o env_file declarado), mas so tem conteudo
# quando o jogo precisa de conta. Ele esta no .gitignore.
Write-LfFile $segredos (($linhasSegredo -join "`n") + "`n")

# ----- stack -----
Write-LfFile $arquivo @"
# Gerado por deploy-docker.ps1 para $Display - edite o .env/games/$GameKey.env e rode de
# novo em vez de mexer aqui.
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
    # O jogo precisa receber o TERM e ter tempo de salvar o mundo antes do KILL.
    stop_grace_period: 120s
    ports:
$($portas -join "`n")
    environment:
      TZ: "$tz"
      PANEL_PUBKEY: "$pub"
      AUTO_UPDATE: "$autoUpdate"
      UPDATE_TIME: "$updateTime"
      UPDATE_ON_START: "$revalidar"
    env_file:
      - $GameKey.secret.env
    volumes:
      - ${Container}-data:/opt/game
      - ${Container}-steam:/home/steam
    mem_limit: ${memoria}m
    cpus: $cores
    networks:
      - $Network

volumes:
  ${Container}-data:
  ${Container}-steam:

networks:
  ${Network}:
    external: true
"@

if ($Recreate) { Invoke-Compose $arquivo $Projeto @("down") }

Write-Host "`nSubindo $Display (o primeiro deploy baixa o jogo inteiro, pode demorar)..." -ForegroundColor Cyan
Invoke-Compose $arquivo $Projeto @("up", "-d", "--build")

Write-Host "`nAcompanhe a instalacao com:" -ForegroundColor DarkGray
Write-Host "  docker logs -f $Container"

# ----- cadastro no painel -----
$registrado = $false
if (-not $NoRegister) {
    if (Test-Container $PanelContainer) {
        $cmdArgs = @(
            "exec", $PanelContainer, "python3", "/opt/gamepanel/app.py",
            "--register-server", $Display,
            "--server-host", $Container,
            "--service", "$GameKey.service",
            "--game-port", (Get-Cfg $jogo "GAME_PORTS"),
            "--query-port", (Get-Cfg $jogo "QUERY_PORT" "0"),
            "--config-path", (Get-Cfg $jogo "CONFIG_PATH"),
            "--config-files", (Get-Cfg $jogo "CONFIG_FILES"),
            # Pastas de save que a tela Backups do painel guarda. Num redeploy o painel
            # mantem o que ja estava la: quem ajustou pela tela nao perde o ajuste.
            "--backup-paths", (Get-Cfg $jogo "BACKUP_PATHS"),
            "--player-source", (Get-Cfg $jogo "PLAYER_SOURCE"),
            "--notes", "Container Docker $Container (deploy-docker.ps1)."
        )
        Invoke-DockerLive $cmdArgs
        if ($LASTEXITCODE -eq 0) {
            $registrado = $true
        } else {
            Write-Host "Nao consegui cadastrar no painel (faca pela tela Adicionar)." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Painel nao encontrado no Docker: cadastre o servidor manualmente ou rode -Panel." -ForegroundColor DarkGray
    }
}

# ----- resumo -----
$portasTexto = if ($listaPortas -ne "") { $listaPortas } else { "(nao definidas para este jogo)" }
Write-Host ""
Write-Host "========================================================================"
Write-Host " Deploy em Docker concluido: $Display"
Write-Host "========================================================================"
Write-Host ""
Write-Host "Container : $Container (rede $Network, ${memoria}MB, $cores cpu)"
Write-Host "Volumes   : ${Container}-data (jogo) e ${Container}-steam (conta/Steam)"
Write-Host "Portas    : $portasTexto"
$notas = Get-Cfg $jogo "PORT_NOTES"
if ($notas -ne "") { Write-Host "Nota      : $notas" }
$hints = Get-Cfg $jogo "CONFIG_HINT"
if ($hints -ne "") { Write-Host "Config    : $hints" }
Write-Host ""
if ($registrado) {
    Write-Host "Ja cadastrado no painel - a tela Config abre o arquivo do jogo direto." -ForegroundColor Green
}
Write-Host "Atalhos dentro do container:"
Write-Host "  docker exec $Container game-status"
Write-Host "  docker exec $Container game-logs -n 50"
Write-Host "  docker exec $Container update-game"
Write-Host "  docker exec -it $Container bash"
Write-Host ""
