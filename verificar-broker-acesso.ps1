<#
Confere, SO COM LEITURA, se o token do Proxmox e a chave do OPNsense do broker
funcionam e tem as permissoes esperadas. Nao cria, altera nem apaga nada.

Le broker.secrets.env (fora do git) e nunca imprime segredo.
Uso:  .\verificar-broker-acesso.ps1
#>
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "broker.secrets.env")
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ----- Saida -----
$script:Falhas = 0
function Say([string]$Status, [string]$Text) {
    $cores = @{ OK = "Green"; FALHA = "Red"; AVISO = "Yellow"; INFO = "Gray" }
    if ($Status -eq "FALHA") { $script:Falhas++ }
    Write-Host ("[{0,-5}] {1}" -f $Status, $Text) -ForegroundColor $cores[$Status]
}

function Explain-Status([int]$Status) {
    switch ($Status) {
        0 { return "nao conectou (confira URL, porta e rede)" }
        401 { return "credencial recusada" }
        403 { return "credencial valida, mas SEM permissao para isso" }
        404 { return "endpoint ou objeto nao existe" }
        default { return "HTTP $Status" }
    }
}

# ----- Segredos -----
function Read-Secrets([string]$Path) {
    if (-not (Test-Path $Path)) {
        throw "Nao achei $Path. Copie broker.secrets.env.example para broker.secrets.env e preencha."
    }
    $cfg = @{}
    foreach ($line in Get-Content $Path) {
        $t = $line.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -lt 1) { continue }
        $valor = $t.Substring($i + 1).Trim()
        # So corta comentario quando ha espaco antes do '#': um segredo pode conter '#'.
        $c = $valor.IndexOf(" #")
        if ($c -ge 0) { $valor = $valor.Substring(0, $c).Trim() }
        $cfg[$t.Substring(0, $i).Trim()] = $valor.Trim('"').Trim("'")
    }
    return $cfg
}

function Test-Preenchido([hashtable]$Cfg, [string[]]$Chaves) {
    foreach ($k in $Chaves) {
        $v = $Cfg[$k]
        if ([string]::IsNullOrEmpty($v) -or $v -match "COLE_|IP_DO_") {
            Say "FALHA" "$k nao foi preenchido em $EnvFile"
            return $false
        }
    }
    return $true
}

# ----- TLS -----
# Proxmox e OPNsense usam certificado autoassinado. Aqui (so leitura, so este teste) o
# certificado e aceito, mas a impressao digital SHA-256 e guardada e mostrada no fim: e
# ela que o broker vai FIXAR em producao, em vez de confiar em qualquer certificado.
# Precisa ser classe C#: um scriptblock do PowerShell chamado pelo .NET em outra thread
# falha com "There is no Runspace available".
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
function Invoke-Api([string]$Method, [string]$Url, [hashtable]$Headers, [string]$Body = "") {
    $p = @{ Method = $Method; Uri = $Url; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 15 }
    if ($Body -ne "") { $p.Body = $Body; $p.ContentType = "application/json" }
    try {
        $r = Invoke-WebRequest @p
    } catch {
        $resp = $_.Exception.Response
        if ($null -ne $resp) { return @{ Status = [int]$resp.StatusCode; Json = $null } }
        return @{ Status = 0; Json = $null }
    }
    $json = $null
    try { $json = $r.Content | ConvertFrom-Json } catch { $json = $null }
    return @{ Status = [int]$r.StatusCode; Json = $json }
}

function Get-Privs($Perms, [string]$Path) {
    $p = $Perms.PSObject.Properties[$Path]
    if ($null -eq $p) { return @() }
    return @($p.Value.PSObject.Properties | ForEach-Object { $_.Name })
}

# ----- Proxmox -----
function Test-Proxmox([hashtable]$Cfg) {
    Write-Host "`n== Proxmox ==" -ForegroundColor Cyan
    if (-not (Test-Preenchido $Cfg @("PROXMOX_URL", "PROXMOX_TOKEN"))) { return }
    $url = $Cfg["PROXMOX_URL"].TrimEnd("/")
    $h = @{ Authorization = "PVEAPIToken=" + $Cfg["PROXMOX_TOKEN"] }
    $pool = $Cfg["PROXMOX_POOL"]
    $storages = @($Cfg["PROXMOX_STORAGE"], $Cfg["PROXMOX_TEMPLATE_STORAGE"]) | Select-Object -Unique

    $r = Invoke-Api "GET" "$url/api2/json/version" $h
    if ($r.Status -ne 200) { Say "FALHA" "GET /version: $(Explain-Status $r.Status)"; return }
    Say "OK" "token aceito - Proxmox VE $($r.Json.data.version)"

    $r = Invoke-Api "GET" "$url/api2/json/access/permissions" $h
    if ($r.Status -ne 200) { Say "FALHA" "GET /access/permissions: $(Explain-Status $r.Status)"; return }
    $perms = $r.Json.data
    Test-ProxmoxPermissoes $perms $pool $storages

    $node = $Cfg["PROXMOX_NODE"]
    if ([string]::IsNullOrEmpty($node)) {
        $n = Invoke-Api "GET" "$url/api2/json/nodes" $h
        if ($n.Status -eq 200 -and @($n.Json.data).Count -gt 0) {
            $node = @($n.Json.data)[0].node
            Say "INFO" "PROXMOX_NODE vazio: usando '$node'"
        } else {
            Say "AVISO" "nao consegui descobrir o no; preencha PROXMOX_NODE (o token pode nao ver /nodes)"
        }
    }

    $r = Invoke-Api "GET" "$url/api2/json/pools/$pool" $h
    if ($r.Status -eq 200) { Say "OK" "pool '$pool' existe ($(@($r.Json.data.members).Count) membros)" }
    else { Say "FALHA" "pool '$pool': $(Explain-Status $r.Status)" }

    if ($node) {
        $tpl = $Cfg["PROXMOX_TEMPLATE_STORAGE"]
        $r = Invoke-Api "GET" "$url/api2/json/nodes/$node/storage/$tpl/content?content=vztmpl" $h
        if ($r.Status -eq 200) { Say "OK" "storage '$tpl' legivel ($(@($r.Json.data).Count) templates de CT)" }
        else { Say "FALHA" "storage '$tpl': $(Explain-Status $r.Status)" }
    }
}

function Test-ProxmoxPermissoes($Perms, [string]$Pool, [string[]]$Storages) {
    $exigidos = [ordered]@{ "/pool/$Pool" = @("VM.Allocate", "VM.Audit", "VM.PowerMgmt", "VM.Config.CPU",
            "VM.Config.Memory", "VM.Config.Disk", "VM.Config.Network", "VM.Config.Options") }
    foreach ($s in $Storages) { $exigidos["/storage/$s"] = @("Datastore.AllocateSpace", "Datastore.Audit") }
    $exigidos["/sdn/zones/localnetwork"] = @("SDN.Use")

    foreach ($caminho in $exigidos.Keys) {
        $tem = Get-Privs $Perms $caminho
        $falta = @($exigidos[$caminho] | Where-Object { $tem -notcontains $_ })
        if ($falta.Count -eq 0) { Say "OK" "permissoes completas em $caminho" }
        else { Say "FALHA" "faltam em ${caminho}: $($falta -join ', ')" }
    }

    # Minimo privilegio tambem e nao ter a MAIS: acusa poder de alterar fora do pool.
    $perigosos = @("VM.Allocate", "Sys.Modify", "Permissions.Modify", "User.Modify", "Realm.AllocateUser")
    foreach ($prop in $Perms.PSObject.Properties) {
        if ($exigidos.Contains($prop.Name)) { continue }
        $excesso = @(Get-Privs $Perms $prop.Name | Where-Object { $perigosos -contains $_ })
        if ($excesso.Count -gt 0) { Say "AVISO" "token tem $($excesso -join ', ') em '$($prop.Name)' (mais do que o pool)" }
    }
}

# ----- OPNsense -----
function Test-Opnsense([hashtable]$Cfg) {
    Write-Host "`n== OPNsense ==" -ForegroundColor Cyan
    if (-not (Test-Preenchido $Cfg @("OPNSENSE_URL", "OPNSENSE_KEY", "OPNSENSE_SECRET"))) { return }
    $url = $Cfg["OPNSENSE_URL"].TrimEnd("/")
    $par = [Text.Encoding]::ASCII.GetBytes($Cfg["OPNSENSE_KEY"] + ":" + $Cfg["OPNSENSE_SECRET"])
    $h = @{ Authorization = "Basic " + [Convert]::ToBase64String($par) }

    # search_rule e so consulta. A escrita (add/del/apply) fica para o proximo teste.
    $r = Invoke-Api "POST" "$url/api/firewall/d_nat/search_rule" $h '{"current":1,"rowCount":-1}'
    if ($r.Status -ne 200) { Say "FALHA" "d_nat/search_rule: $(Explain-Status $r.Status)"; return }
    $linhas = @($r.Json.rows)
    Say "OK" "chave aceita e d_nat legivel ($($linhas.Count) regras de redirect)"
    $nossas = @($linhas | Where-Object { $_.descr -like "gamepanel:*" })
    Say "INFO" "regras do broker (descricao 'gamepanel:...'): $($nossas.Count)"
    if ($linhas.Count -gt 0) {
        $campos = ($linhas[0].PSObject.Properties | ForEach-Object { $_.Name }) -join ", "
        Say "INFO" "campos de uma regra: $campos"
    }
}

# ----- Execucao -----
try {
    $cfg = Read-Secrets $EnvFile
} catch {
    Say "FALHA" $_.Exception.Message
    exit 1
}
Test-Proxmox $cfg
Test-Opnsense $cfg

if ([GuardaCert]::Impressoes.Count -gt 0) {
    Write-Host "`n== Impressao digital SHA-256 dos certificados (o broker vai fixar esta) ==" -ForegroundColor Cyan
    foreach ($hostName in [GuardaCert]::Impressoes.Keys) { Say "INFO" "$hostName  $([GuardaCert]::Impressoes[$hostName])" }
}

Write-Host ""
if ($script:Falhas -gt 0) { Say "FALHA" "$($script:Falhas) problema(s) acima."; exit 1 }
Say "OK" "acesso conferido (somente leitura)."
