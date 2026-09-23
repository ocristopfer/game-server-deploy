<#
Spike da Fase 0 (ESCRITA): responde, com o token e a chave reais, o que o broker
precisa saber antes de existir.

  Proxmox : o token de privilegio minimo consegue criar um CT no pool com
            features nesting/keyctl, tag e chave SSH? E destruir depois?
  OPNsense: a chave consegue criar, aplicar e apagar um redirect (d_nat)?

Tudo que cria e apagado no fim (try/finally), e SO apaga o que ele mesmo criou,
conferindo o nome/descricao antes. O CT nunca e iniciado; a regra nasce DESATIVADA.
Le broker.secrets.env e nunca imprime segredo.

Uso:  .\spike-broker-write.ps1 [-ProxmoxOnly] [-OpnsenseOnly]
#>
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "broker.secrets.env"),
    [int]$Ctid = 399,
    [string]$Ip = "192.168.2.250",
    [string]$Gateway = "192.168.2.1",
    [int]$Port = 65001,
    # O nome antigo `-SoProxmox` continua valendo pelo Alias: quem ja tem a linha de
    # comando salva nao a perde.
    [Alias('SoProxmox')]
    [switch]$ProxmoxOnly,
    # O nome antigo `-SoOpnsense` continua valendo pelo Alias: quem ja tem a linha de
    # comando salva nao a perde.
    [Alias('SoOpnsense')]
    [switch]$OpnsenseOnly,
    # Liga o CT de teste e entra por SSH (confere sshd, rede, apt e keyctl) antes de destruir.
    # O nome antigo `-ComSsh` continua valendo pelo Alias: quem ja tem a linha de
    # comando salva nao a perde.
    [Alias('ComSsh')]
    [switch]$WithSsh
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$TestHostname = "spike-broker"
$TestDescription = "gamepanel:spike"

# ----- Saida -----
$script:Falhas = 0
function Say([string]$Status, [string]$Text) {
    $cores = @{ OK = "Green"; FALHA = "Red"; AVISO = "Yellow"; INFO = "Gray" }
    if ($Status -eq "FALHA") { $script:Falhas++ }
    Write-Host ("[{0,-5}] {1}" -f $Status, $Text) -ForegroundColor $cores[$Status]
}

# ----- Segredos -----
function Read-Secrets([string]$Path) {
    if (-not (Test-Path $Path)) { throw "Nao achei $Path." }
    $cfg = @{}
    foreach ($line in Get-Content $Path) {
        $t = $line.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -lt 1) { continue }
        $value = $t.Substring($i + 1).Trim()
        $c = $value.IndexOf(" #")
        if ($c -ge 0) { $value = $value.Substring(0, $c).Trim() }
        $cfg[$t.Substring(0, $i).Trim()] = $value.Trim('"').Trim("'")
    }
    return $cfg
}

# ----- TLS (certificado autoassinado aceito SO neste teste; ver check-broker-access.ps1) -----
if (-not ("GuardaCert" -as [type])) {
    Add-Type @"
using System.Collections.Generic;
using System.Net;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
public class GuardaCert : ICertificatePolicy {
    public static Dictionary<string, string> Impressoes = new Dictionary<string, string>();
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int problema) {
        using (SHA256 sha = SHA256.Create()) {
            byte[] h = sha.ComputeHash(cert.GetRawCertData());
            Impressoes[sp.Address.Host] = System.BitConverter.ToString(h).Replace("-", ":");
        }
        return true;
    }
}
"@
}
[Net.ServicePointManager]::CertificatePolicy = New-Object GuardaCert
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ----- HTTP -----
# Body: hashtable (formulario, o que o Proxmox espera) ou texto JSON (o que o OPNsense espera).
function Invoke-Api([string]$Method, [string]$Url, [hashtable]$Headers, $Body = $null) {
    $p = @{ Method = $Method; Uri = $Url; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 30 }
    if ($null -ne $Body) {
        $p.Body = $Body
        if ($Body -is [string]) { $p.ContentType = "application/json" }
    }
    try {
        $r = Invoke-WebRequest @p
    } catch {
        $resp = $_.Exception.Response
        if ($null -eq $resp) { return @{ Status = 0; Json = $null; Texto = $_.Exception.Message } }
        $text = ""
        try {
            $reader = New-Object IO.StreamReader($resp.GetResponseStream())
            $text = $reader.ReadToEnd()
        } catch { $text = "" }
        # O Proxmox devolve o motivo ("Permission check failed (/vms/399, VM.Allocate)") na
        # linha de status HTTP, nao no corpo.
        if ([string]::IsNullOrWhiteSpace($text)) { $text = [string]$resp.StatusDescription }
        return @{ Status = [int]$resp.StatusCode; Json = $null; Texto = $text }
    }
    $json = $null
    try { $json = $r.Content | ConvertFrom-Json } catch { $json = $null }
    return @{ Status = [int]$r.StatusCode; Json = $json; Texto = $r.Content }
}

function Short([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return "(sem corpo)" }
    $t = ($Text -replace "\s+", " ").Trim()
    if ($t.Length -gt 300) { return $t.Substring(0, 300) + "..." }
    return $t
}

# ============================== Proxmox ==============================
function Wait-PveTask([string]$Base, [hashtable]$H, [string]$Node, [string]$Upid) {
    $enc = [uri]::EscapeDataString($Upid)
    for ($i = 0; $i -lt 90; $i++) {
        $r = Invoke-Api "GET" "$Base/nodes/$Node/tasks/$enc/status" $H
        if ($r.Status -eq 200 -and $r.Json.data.status -eq "stopped") {
            # "WARNINGS: 1" e sucesso com avisos (ex.: "Systemd 257: pode precisar de nesting").
            $output = [string]$r.Json.data.exitstatus
            if ($output -like "WARNINGS*") { return "OK" }
            return $output
        }
        if ($r.Status -ne 200) { return "sem acesso ao status da tarefa (HTTP $($r.Status))" }
        Start-Sleep -Seconds 2
    }
    return "timeout esperando a tarefa"
}

function Get-PveTaskLog([string]$Base, [hashtable]$H, [string]$Node, [string]$Upid) {
    $enc = [uri]::EscapeDataString($Upid)
    $r = Invoke-Api "GET" "$Base/nodes/$Node/tasks/$enc/log?limit=20" $H
    if ($r.Status -ne 200) { return @() }
    return @($r.Json.data | Select-Object -Last 4 | ForEach-Object { $_.t })
}

function New-TestKey {
    $dir = Join-Path ([IO.Path]::GetTempPath()) ("spike-key-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $dir | Out-Null
    $keyFile = Join-Path $dir "id"
    # ssh-keygen escreve no stderr mesmo com sucesso; -N '""' porque o PS 5.1 descarta argumento vazio.
    $before = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & ssh-keygen -q -t ed25519 -N '""' -f $keyFile 2>&1 | Out-Null
    $ErrorActionPreference = $before
    if (-not (Test-Path "$keyFile.pub")) { throw "ssh-keygen nao gerou a chave de teste" }
    $pub = (Get-Content "$keyFile.pub" -Raw).Trim()
    # A pasta fica de pe (a chave privada e usada no teste de SSH); quem chama a apaga no finally.
    return @{ Pub = $pub; Dir = $dir; Priv = $keyFile }
}

function Test-ProxmoxWrite([hashtable]$Cfg) {
    Write-Host "`n== Proxmox: criar e destruir CT $Ctid no pool ==" -ForegroundColor Cyan
    $base = $Cfg["PROXMOX_URL"].TrimEnd("/") + "/api2/json"
    $h = @{ Authorization = "PVEAPIToken=" + $Cfg["PROXMOX_TOKEN"] }
    $node = $Cfg["PROXMOX_NODE"]
    $pool = $Cfg["PROXMOX_POOL"]

    if (Test-Connection -ComputerName $Ip -Count 1 -Quiet) {
        Say "FALHA" "$Ip responde a ping: escolha outro IP com -Ip (nada foi criado)"
        return
    }
    $existing = Invoke-Api "GET" "$base/nodes/$node/lxc/$Ctid/config" $h
    if ($existing.Status -eq 200) {
        Say "FALHA" "o CT $Ctid ja existe (nome '$($existing.Json.data.hostname)'): escolha outro com -Ctid (nada foi criado)"
        return
    }

    $pair = New-TestKey
    $key = $pair.Pub
    $bodyBase = [ordered]@{
        vmid = $Ctid; hostname = $TestHostname
        ostemplate = "$($Cfg['PROXMOX_TEMPLATE_STORAGE']):vztmpl/debian-13-standard_13.6-1_amd64.tar.zst"
        rootfs = "$($Cfg['PROXMOX_STORAGE']):4"; memory = 256; swap = 0; cores = 1; unprivileged = 1
        net0 = "name=eth0,bridge=$($Cfg['PROXMOX_BRIDGE']),ip=$Ip/24,gw=$Gateway,type=veth"
        pool = $pool; start = 0; onboot = 0
    }
    # Ja sabido (rodadas anteriores): tag na criacao exige VM.Config.Options em /vms/<id> e
    # keyctl=1 so o root@pam pode. Aqui a variante realista do broker: nesting + chave SSH.
    $variants = @(
        @{ Nome = "nesting + chave SSH"; Extra = @{ features = "nesting=1"; "ssh-public-keys" = $key } },
        @{ Nome = "so chave SSH"; Extra = @{ "ssh-public-keys" = $key } }
    )

    $createdAny = $false
    try {
        foreach ($v in $variants) {
            $body = @{}
            foreach ($k in $bodyBase.Keys) { $body[$k] = $bodyBase[$k] }
            foreach ($k in $v.Extra.Keys) { $body[$k] = $v.Extra[$k] }

            $r = Invoke-Api "POST" "$base/nodes/$node/lxc" $h $body
            if ($r.Status -ne 200) {
                Say "FALHA" "criar CT, variante $($v.Nome): HTTP $($r.Status) - $(Short $r.Texto)"
                continue
            }
            $upid = [string]$r.Json.data
            $createdAny = $true
            $output = Wait-PveTask $base $h $node $upid
            if ($output -ne "OK") {
                Say "FALHA" "criar CT, variante $($v.Nome): tarefa terminou com '$output'"
                Get-PveTaskLog $base $h $node $upid | ForEach-Object { Say "INFO" "  log: $_" }
                Remove-TestCt $base $h $node
                $createdAny = $false
                continue
            }
            Say "OK" "criar CT, variante $($v.Nome): FUNCIONOU"
            Confirm-TestCt $base $h $node $pool $v
            if ($WithSsh) { Test-SshDoCt $base $h $node $pair.Priv }
            break
        }
    } finally {
        if ($createdAny) { Remove-TestCt $base $h $node }
        if (Test-Path $pair.Dir) { Remove-Item -Recurse -Force $pair.Dir }
    }
}

function Test-SshDoCt([string]$Base, [hashtable]$H, [string]$Node, [string]$PrivateKey) {
    Write-Host "`n-- SSH no CT de teste --" -ForegroundColor Cyan
    $r = Invoke-Api "POST" "$Base/nodes/$Node/lxc/$Ctid/status/start" $H @{}
    if ($r.Status -ne 200) { Say "FALHA" "iniciar o CT: HTTP $($r.Status) - $(Short $r.Texto)"; return }
    $output = Wait-PveTask $Base $H $Node ([string]$r.Json.data)
    if ($output -ne "OK") { Say "FALHA" "iniciar o CT: tarefa terminou com '$output'"; return }
    Say "OK" "CT iniciado"

    # Espera a porta 22 abrir (boot + sshd). 90 s e folga de sobra para um Debian de CT.
    $isOpen = $false
    for ($i = 0; $i -lt 30 -and -not $isOpen; $i++) {
        $tcp = New-Object Net.Sockets.TcpClient
        try {
            $ar = $tcp.BeginConnect($Ip, 22, $null, $null)
            if ($ar.AsyncWaitHandle.WaitOne(2000) -and $tcp.Connected) { $isOpen = $true }
        } catch { $isOpen = $false } finally { $tcp.Close() }
        if (-not $isOpen) { Start-Sleep -Seconds 1 }
    }
    if (-not $isOpen) {
        Say "FALHA" "a porta 22 de $Ip nao abriu em ~90 s (o CT nao tem sshd, ou esta maquina nao alcanca a rede 192.168.2.x)"
        return
    }
    Say "OK" "porta 22 de $Ip aberta a partir desta maquina"

    # Sem aspas duplas de proposito: o PowerShell 5.1 as estraga ao passar argumento para o ssh.exe.
    $remoteLine = 'echo SSH_OK; id -u; grep PRETTY_NAME /etc/os-release; systemctl is-active ssh; dpkg -s openssh-server | grep ^Status; getent hosts deb.debian.org && echo DNS_OK || echo DNS_FALHOU; timeout 90 apt-get update -qq >/dev/null 2>&1 && echo APT_OK || echo APT_FALHOU; timeout 90 apt-get install -y -qq keyutils >/dev/null 2>&1; keyctl show @s >/dev/null 2>&1 && echo KEYCTL_OK || echo KEYCTL_BLOQUEADO'
    $before = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $text = (& ssh -i $PrivateKey -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=10 "root@$Ip" $remoteLine 2>&1 | Out-String)
    $ErrorActionPreference = $before

    if ($text -notmatch "SSH_OK") { Say "FALHA" "ssh nao entrou: $(Short $text)"; return }
    Say "OK" "entrou por SSH como root com a chave temporaria (senha desligada: BatchMode)"
    foreach ($line in ($text -split "`r?`n" | Where-Object { $_.Trim() -ne "" -and $_ -notmatch "Warning: Permanently added" })) { Say "INFO" "  remoto: $($line.Trim())" }
    if ($text -match "Status: install ok installed") { Say "OK" "openssh-server ja vem instalado no template (template dourado NAO e necessario para o sshd)" }
    else { Say "AVISO" "openssh-server nao consta como instalado" }
    if ($text -match "APT_OK") { Say "OK" "apt update funciona no CT (rede e DNS de saida ok)" } else { Say "FALHA" "apt update falhou no CT: sem internet ou DNS" }
    if ($text -match "KEYCTL_OK") { Say "OK" "keyctl funciona SEM a feature keyctl=1" }
    elseif ($text -match "KEYCTL_BLOQUEADO") { Say "AVISO" "keyctl bloqueado sem a feature: se algum jogo/instalador precisar, sera preciso clonar de um CT-template feito pelo root" }
}

function Confirm-TestCt([string]$Base, [hashtable]$H, [string]$Node, [string]$Pool, $Variant) {
    $c = Invoke-Api "GET" "$Base/nodes/$Node/lxc/$Ctid/config" $H
    if ($c.Status -ne 200) { Say "AVISO" "nao consegui ler a config do CT criado (HTTP $($c.Status))"; return }
    $d = $c.Json.data
    Say "INFO" "config gravada: unprivileged=$($d.unprivileged) features='$($d.features)' tags='$($d.tags)'"
    $p = Invoke-Api "GET" "$Base/pools/$Pool" $H
    if ($p.Status -eq 200) {
        $no_pool = @($p.Json.data.members | Where-Object { $_.vmid -eq $Ctid }).Count -gt 0
        if ($no_pool) { Say "OK" "o CT aparece como membro do pool '$Pool'" } else { Say "FALHA" "o CT nao entrou no pool '$Pool'" }
    }
    # Com o CT ja dentro do pool, as permissoes do pool passam a valer para /vms/<id>:
    # e o momento em que a tag (identidade do broker) pode ser gravada.
    $t = Invoke-Api "PUT" "$Base/nodes/$Node/lxc/$Ctid/config" $H @{ tags = "gamepanel-broker" }
    if ($t.Status -eq 200) { Say "OK" "tag gravada DEPOIS da criacao (o CT ja esta no pool)" }
    else { Say "AVISO" "tag depois da criacao: HTTP $($t.Status) - $(Short $t.Texto) (o pool basta como identidade)" }
}

function Remove-TestCt([string]$Base, [hashtable]$H, [string]$Node) {
    $c = Invoke-Api "GET" "$Base/nodes/$Node/lxc/$Ctid/config" $H
    if ($c.Status -ne 200) { return }
    if ($c.Json.data.hostname -ne $TestHostname) {
        Say "FALHA" "o CT $Ctid NAO e o de teste (nome '$($c.Json.data.hostname)'): nao vou apagar"
        return
    }
    $st = Invoke-Api "GET" "$Base/nodes/$Node/lxc/$Ctid/status/current" $H
    if ($st.Status -eq 200 -and $st.Json.data.status -eq "running") {
        $pair = Invoke-Api "POST" "$Base/nodes/$Node/lxc/$Ctid/status/shutdown" $H @{ forceStop = 1; timeout = 20 }
        if ($pair.Status -eq 200) { Wait-PveTask $Base $H $Node ([string]$pair.Json.data) | Out-Null }
    }
    $r = Invoke-Api "DELETE" "$Base/nodes/$Node/lxc/${Ctid}?purge=1&destroy-unreferenced-disks=1" $H
    if ($r.Status -ne 200) { Say "FALHA" "destruir o CT de teste: HTTP $($r.Status) - $(Short $r.Texto). APAGUE A MAO o CT $Ctid" ; return }
    $output = Wait-PveTask $Base $H $Node ([string]$r.Json.data)
    $stillThere = Invoke-Api "GET" "$Base/nodes/$Node/lxc/$Ctid/config" $H
    if ($output -eq "OK" -and $stillThere.Status -ne 200) { Say "OK" "CT de teste destruido e confirmado ausente" }
    else { Say "FALHA" "destruir o CT: tarefa '$output'. CONFIRA se o CT $Ctid ainda existe" }
}

# ============================== OPNsense ==============================
function Test-OpnsenseWrite([hashtable]$Cfg) {
    Write-Host "`n== OPNsense: criar, aplicar e apagar um redirect desativado ==" -ForegroundColor Cyan
    $base = $Cfg["OPNSENSE_URL"].TrimEnd("/") + "/api/firewall"
    $pair = [Text.Encoding]::ASCII.GetBytes($Cfg["OPNSENSE_KEY"] + ":" + $Cfg["OPNSENSE_SECRET"])
    $h = @{ Authorization = "Basic " + [Convert]::ToBase64String($pair) }
    $wan = $Cfg["OPNSENSE_WAN"]

    $before = Invoke-Api "POST" "$base/d_nat/search_rule" $h '{"current":1,"rowCount":-1}'
    if ($before.Status -ne 200) { Say "FALHA" "ler regras: HTTP $($before.Status)"; return }
    $leftover = @($before.Json.rows | Where-Object { $_.descr -eq $TestDescription })
    if ($leftover.Count -gt 0) { Say "FALHA" "ja existe regra '$TestDescription' (sobra de teste anterior): apague pela tela do OPNsense e rode de novo"; return }
    $taken = @($before.Json.rows | Where-Object { $_.'destination.port' -eq "$Port" })
    if ($taken.Count -gt 0) { Say "FALHA" "a porta $Port ja e usada por outra regra: escolha outra com -Porta"; return }

    $rule = @{ rule = [ordered]@{
        disabled = "1"; interface = $wan; protocol = "udp"; ipprotocol = "inet"
        destination = @{ network = "wanip"; port = "$Port" }
        target = $Ip; "local-port" = "$Port"; descr = $TestDescription
        # Igual as regras de jogo que ja existem: "pass" libera o trafego no filtro tambem.
        # Sem isso o redirect existiria, mas o WAN barraria o pacote.
        pass = "pass"
    } } | ConvertTo-Json -Depth 5 -Compress

    $uuid = $null
    try {
        $r = Invoke-Api "POST" "$base/d_nat/add_rule" $h $rule
        if ($r.Status -ne 200 -or -not $r.Json.uuid) {
            Say "FALHA" "add_rule: HTTP $($r.Status) - $(Short $r.Texto)"
            return
        }
        $uuid = [string]$r.Json.uuid
        Say "OK" "add_rule criou a regra desativada (resultado: $($r.Json.result))"

        $found = Get-TestRule $base $h $uuid
        if ($null -ne $found) {
            Say "INFO" "regra lida de volta: descr='$($found.descr)' interface=$($found.interface) alvo=$($found.target) porta=$($found.'destination.port') pass='$($found.pass)' assoc='$($found.'associated-rule-id')'"
        }

        $ap = Invoke-Api "POST" "$base/filter/apply" $h '{}'
        if ($ap.Status -eq 200) { Say "OK" "filter/apply aceito ($(Short $ap.Texto))" }
        else { Say "FALHA" "filter/apply: HTTP $($ap.Status) - $(Short $ap.Texto)" }
    } finally {
        if ($uuid) { Remove-TestRule $base $h $uuid }
    }
}

# A leitura e pelo search_rule (campos planos), nao pelo get_rule: o get_rule devolve listas
# com nome de campo vazio e o ConvertFrom-Json do PowerShell 5.1 nao as le.
function Get-TestRule([string]$Base, [hashtable]$H, [string]$Uuid) {
    $r = Invoke-Api "POST" "$Base/d_nat/search_rule" $H '{"current":1,"rowCount":-1}'
    if ($r.Status -ne 200) { return $null }
    return @($r.Json.rows | Where-Object { $_.uuid -eq $Uuid })[0]
}

function Remove-TestRule([string]$Base, [hashtable]$H, [string]$Uuid) {
    $found = Get-TestRule $Base $H $Uuid
    $isOurs = ($null -ne $found) -and ($found.descr -eq $TestDescription) -and ($found.target -eq $Ip) -and ($found.'destination.port' -eq "$Port")
    if (-not $isOurs) {
        Say "FALHA" "a regra $Uuid NAO bate com a de teste (descricao, alvo e porta): nao vou apagar (apague a mao)"
        return
    }
    $d = Invoke-Api "POST" "$Base/d_nat/del_rule/$Uuid" $H '{}'
    if ($d.Status -ne 200) { Say "FALHA" "del_rule: HTTP $($d.Status) - $(Short $d.Texto). APAGUE A MAO a regra '$TestDescription'"; return }
    $ap = Invoke-Api "POST" "$Base/filter/apply" $H '{}'
    $after = Invoke-Api "POST" "$Base/d_nat/search_rule" $H '{"current":1,"rowCount":-1}'
    $remains = @($after.Json.rows | Where-Object { $_.descr -eq $TestDescription }).Count
    if ($ap.Status -eq 200 -and $remains -eq 0) { Say "OK" "del_rule + apply: regra de teste removida e confirmada ausente" }
    else { Say "FALHA" "limpeza incompleta (apply HTTP $($ap.Status), restam $remains). CONFIRA no OPNsense" }
}

# ============================== Execucao ==============================
try { $cfg = Read-Secrets $EnvFile } catch { Say "FALHA" $_.Exception.Message; exit 1 }

if (-not $OpnsenseOnly) { Test-ProxmoxWrite $cfg }
if (-not $ProxmoxOnly) { Test-OpnsenseWrite $cfg }

Write-Host ""
if ($script:Falhas -gt 0) { Say "FALHA" "$($script:Falhas) problema(s) acima."; exit 1 }
Say "OK" "spike de escrita concluido; nada de teste ficou para tras."
