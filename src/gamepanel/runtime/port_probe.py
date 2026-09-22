"""Descobre como contar jogadores: o jogo abre os sockets dele dentro do container, e em
vez de chutar a porta de consulta, o painel pergunta ao proprio container quais portas
estao escutando, QUEM as abriu, e testa uma a uma. UDP vira consulta A2S; TCP vira
sondagem HTTP (e onde moram as APIs de administracao).
"""
from __future__ import annotations

import re
import shlex
import threading
from collections.abc import Callable
from typing import Any

from gamepanel.runtime.a2s import QueryError, query_players
from gamepanel.runtime.ssh import RemoteError, ServerLike

# Tudo sai de /proc: 'ss', 'netstat' e 'lsof' nao vem instalados em todo container.
# O caminho e o mesmo que o `ss -p` faz: /proc/net/* da porta + inode do socket, e os
# descritores abertos de cada processo (/proc/PID/fd) dizem de quem e aquele inode.
# Saber o dono e o que separa a porta do jogo do ruido (sshd, DNS do Docker, um HTTP
# qualquer numa porta alta).
LISTEN_PORTS_SCRIPT = r"""
set -u

# inode do socket -> pid. Como o painel entra como root, enxerga todos os processos.
donos() {
  for dir in /proc/[0-9]*; do
    [ -d "$dir/fd" ] || continue
    ls -l "$dir/fd" 2>/dev/null | awk -v pid="${dir#/proc/}" '
      match($0, /socket:\[[0-9]+\]/) {
        print substr($0, RSTART + 8, RLENGTH - 9), pid
      }'
  done
}

# Coluna 2 = endereco local (IP:PORTA em hex), 4 = estado, 10 = inode. Em TCP so
# interessa 0A (LISTEN); em UDP o socket ligado ja e a porta aberta.
sockets() {
  arquivo=$1 proto=$2 estado=$3
  [ -r "$arquivo" ] || return 0
  awk -v p="$proto" -v e="$estado" \
    'NR > 1 && (e == "" || $4 == e) { split($2, a, ":"); print p, a[2], $10 }' "$arquivo"
}

mapa=$(donos)
{
  sockets /proc/net/udp  udp ""
  sockets /proc/net/udp6 udp ""
  sockets /proc/net/tcp  tcp 0A
  sockets /proc/net/tcp6 tcp 0A
} | sort -u | while read -r proto hex inode; do
  porta=$(printf '%d' "0x$hex" 2>/dev/null) || continue
  pid=$(printf '%s\n' "$mapa" | awk -v i="$inode" '$1 == i { print $2; exit }')
  nome='?'
  if [ -n "$pid" ] && [ -r "/proc/$pid/comm" ]; then
    nome=$(cat "/proc/$pid/comm" 2>/dev/null) || nome='?'
  fi
  printf '%s %s %s %s\n' "$proto" "$porta" "${pid:-0}" "${nome:-?}"
done
"""

# Portas de consulta que a maioria dos jogos Steam usa quando nao ha nada declarado.
QUERY_PORT_GUESSES = (27015, 27016, 27005)
# Portas de API de administracao mais comuns: 8212 (REST do Palworld), 7777 (HTTPS do
# Satisfactory), 8080 (padrao de quem escreve um painelzinho proprio).
API_PORT_GUESSES = (8212, 7777, 8080)
# O sshd e o proprio painel entrando no container: sondar essa porta so gera ruido.
IGNORED_PORTS = (22,)

# Processos que sempre abrem porta num container e nunca sao o jogo: marca-los deixa a
# lista legivel sem esconder nada de quem esta procurando.
INFRA_PROCESSES = frozenset({
    "sshd", "sshd-session", "systemd", "systemd-resolve", "systemd-resolved", "dockerd",
    "containerd", "dnsmasq", "cron", "rsyslogd", "chronyd", "ntpd",
})

MAX_TCP_PORT = 65535
_PARSED_LINE_FIELDS = 4

SshOutput = Callable[[ServerLike, str, int], str]


def _remote_script(script: str, *args: str) -> str:
    return " ".join(shlex.quote(p) for p in ("bash", "-lc", script, "gp", *args))


def _ports_from_text(text: str) -> list[int]:
    """Tira numeros de porta do campo livre 'Portas do jogo' (ex.: '8211/udp 27015/udp')."""
    return [int(n) for n in re.findall(r"\d{2,5}", text or "") if 1 <= int(n) <= MAX_TCP_PORT]


def _without_repeats(ports: list[int]) -> list[int]:
    out: list[int] = []
    for port in ports:
        if 1 <= port <= MAX_TCP_PORT and port not in out and port not in IGNORED_PORTS:
            out.append(port)
    return out


def _read_open_ports(raw: str, listening: dict[str, list[int]], owners: dict[tuple[str, int], dict]) -> None:
    """Preenche `listening` e `owners` com o que o LISTEN_PORTS_SCRIPT devolveu.

    Cada linha e "<proto> <porta> <pid> <nome do processo>". Linha que nao tiver essa
    forma e ignorada sem reclamar: o script le /proc a unha, e um container estranho
    pode devolver algo que nao casa - deixar de listar uma porta e melhor do que
    derrubar o assistente inteiro.
    """
    for line in raw.splitlines():
        fields = line.split(None, 3)
        if len(fields) != _PARSED_LINE_FIELDS or fields[0] not in listening or not fields[1].isdigit():
            continue
        proto, port, pid, name = fields[0], int(fields[1]), fields[2], fields[3]
        listening[proto].append(port)
        # Mesma porta em IPv4 e IPv6: fica a primeira que soube dizer o dono.
        if owners.get((proto, port), {}).get("proc", "?") == "?":
            owners[(proto, port)] = {
                "pid": int(pid) if pid.isdigit() else 0,
                "proc": name.strip() or "?",
                "infra": name.strip() in INFRA_PROCESSES,
            }


def candidate_ports(
    ssh_output: SshOutput, server: ServerLike, game_port_field: str,
) -> tuple[list[int], list[int], dict[tuple[str, int], dict], str]:
    """Portas a testar (UDP, TCP), quem abriu cada uma, e o aviso se a leitura falhou.

    A lista vem do container (portas realmente abertas, com o processo dono) e so entao
    recebe as portas declaradas no cadastro e os chutes conhecidos, como rede de seguranca
    para quando o servidor esta parado — nessa hora nao ha socket nenhum para detectar.
    """
    listening: dict[str, list[int]] = {"udp": [], "tcp": []}
    owners: dict[tuple[str, int], dict] = {}
    warning = ""
    try:
        raw = ssh_output(server, _remote_script(LISTEN_PORTS_SCRIPT), 60)
        _read_open_ports(raw, listening, owners)
    except (RemoteError, ValueError) as exc:
        warning = f"nao consegui listar as portas abertas do container: {exc}"

    def priority(proto: str, port: int) -> int:
        """Porta com processo dono de verdade primeiro; infra por ultimo.

        No meio ficam as sem dono: existe socket, mas nenhum processo DESTE container o
        abriu (o resolvedor DNS do Docker, por exemplo, que vive fora do namespace).
        """
        owner = owners.get((proto, port))
        if owner is None or owner["proc"] == "?":
            return 1
        return 2 if owner["infra"] else 0

    def useful_first(proto: str) -> list[int]:
        return sorted(listening[proto], key=lambda p: (priority(proto, p), p))

    declared = _ports_from_text(game_port_field)
    udp = _without_repeats(useful_first("udp") + declared + list(QUERY_PORT_GUESSES))
    tcp = _without_repeats(useful_first("tcp") + declared + list(API_PORT_GUESSES))
    return udp, tcp, owners, warning


def _with_owner(items: list[dict], owners: dict[tuple[str, int], dict], proto: str) -> list[dict]:
    """Anexa o processo dono a cada porta sondada, para a tela poder mostrar.

    Tres estados diferentes, e a tela precisa saber qual e qual:
    'detectada'  - o socket existe e o processo dono foi identificado;
    'sem-dono'   - o socket existe, mas nenhum processo deste container o abriu;
    'nao-vista'  - a porta nem estava aberta (veio do cadastro ou da lista de chutes).
    """
    for item in items:
        owner = owners.get((proto, item["port"]))
        if owner is None:
            item.update({"origem": "nao-vista", "proc": "", "pid": 0, "infra": False})
        elif owner["proc"] == "?":
            item.update({"origem": "sem-dono", "proc": "", "pid": 0, "infra": False})
        else:
            item.update({"origem": "detectada", "proc": owner["proc"],
                         "pid": owner["pid"], "infra": owner["infra"]})
    return items


# Sondagem HTTP das portas TCP. Roda dentro do container (uma unica ida de SSH para
# todas as portas) porque API de administracao costuma escutar so em 127.0.0.1 — de
# fora do container ela pareceria fechada.
#
# Duas etapas por porta: primeiro um GET em "/" so para saber se ali fala HTTP; so
# quem responde alguma coisa leva os caminhos conhecidos. Assim uma porta que nao e
# HTTP custa uma tentativa, nao seis.
HTTP_PROBE_PORTS_MAX = 12
HTTP_PROBE_SCRIPT = r"""
set -u
tmo=$1
shift
caminhos='/v1/api/info /v1/api/metrics /v1/api/players /api/v1 /status /api/info'

sonda=""
if command -v curl >/dev/null 2>&1; then
  pega() { curl -sS -k -m "$tmo" -o /dev/null -w '%{http_code} %{content_type}' "$1" 2>/dev/null || echo "000 -"; }
elif command -v python3 >/dev/null 2>&1; then
  sonda=$(mktemp 2>/dev/null) || sonda=/tmp/gamepanel-sonda.py
  cat >"$sonda" <<'PY'
import sys
import urllib.error
import urllib.request

url, tmo = sys.argv[1], float(sys.argv[2])
try:
    if url.startswith("https"):
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx = None
    resp = urllib.request.urlopen(url, timeout=tmo, context=ctx)
    print(resp.getcode(), resp.headers.get("Content-Type", "-") or "-")
except urllib.error.HTTPError as exc:
    print(exc.code, exc.headers.get("Content-Type", "-") or "-")
except Exception:
    print("000 -")
PY
  pega() { python3 "$sonda" "$1" "$tmo" 2>/dev/null || echo "000 -"; }
else
  echo "o container nao tem curl nem python3 para sondar as portas" >&2
  exit 127
fi

for porta in "$@"; do
  esquema=http
  raiz=$(pega "http://127.0.0.1:${porta}/")
  case "$raiz" in
    000*)
      # Nada em HTTP: pode ser uma API que so aceita TLS (o Satisfactory e assim).
      raiz=$(pega "https://127.0.0.1:${porta}/")
      esquema=https
      ;;
  esac
  printf '%s|%s|/|%s\n' "$porta" "$esquema" "$raiz"
  case "$raiz" in
    000*) continue ;;
  esac
  for caminho in $caminhos; do
    printf '%s|%s|%s|%s\n' "$porta" "$esquema" "$caminho" \
      "$(pega "${esquema}://127.0.0.1:${porta}${caminho}")"
  done
done

[ -n "$sonda" ] && rm -f "$sonda"
exit 0
"""

# Status que indicam "achei alguma coisa": 200 e resposta, 401/403 e "existe API aqui,
# ela so quer senha". Qualquer outra coisa e um servidor HTTP que nao conhece a rota.
USEFUL_STATUSES = (200, 401, 403)


def probe_http_ports(
    ssh_output: SshOutput, server: ServerLike, ports: list[int], probe_timeout: float = 2.0,
) -> tuple[list[dict], list[int], str]:
    """Sonda as portas TCP com HTTP. Devolve (o que respondeu, portas mudas, aviso)."""
    ports = ports[:HTTP_PROBE_PORTS_MAX]
    if not ports:
        return [], [], ""
    # Pior caso: 2 tentativas na raiz + 6 caminhos, por porta.
    limit = int(probe_timeout * 8 * len(ports)) + 20
    try:
        raw = ssh_output(
            server,
            _remote_script(HTTP_PROBE_SCRIPT, f"{probe_timeout:g}", *(str(p) for p in ports)),
            limit,
        )
    except RemoteError as exc:
        return [], ports, f"nao consegui sondar as portas TCP: {exc}"

    found: list[dict] = []
    answered: set[int] = set()
    for line in raw.splitlines():
        fields = line.split("|")
        if len(fields) != _PARSED_LINE_FIELDS or not fields[0].isdigit():
            continue
        port, scheme, path, result = fields
        status, _, content_type = result.strip().partition(" ")
        if not status.isdigit() or int(status) == 0:
            continue
        answered.add(int(port))
        found.append({
            "port": int(port),
            "scheme": scheme,
            "path": path,
            "status": int(status),
            "content_type": (content_type or "-").split(";")[0].strip(),
            "url": f"{scheme}://127.0.0.1:{port}{path}",
        })

    found = _summarize_generic(found)
    # JSON primeiro, depois quem pediu senha (401/403 = "existe API aqui").
    found.sort(key=lambda a: (
        0 if "json" in a["content_type"] else 1,
        0 if a["status"] in USEFUL_STATUSES else 1,
        a["port"], a["path"],
    ))
    silent = [p for p in ports if p not in answered]
    return found, silent, ""


def _summarize_generic(found: list[dict]) -> list[dict]:
    """Porta que respondeu 404 em tudo vira UMA linha, nao sete.

    Um processo qualquer subindo um HTTP numa porta alta (o cliente da Steam faz isso)
    enche a tela de linhas inuteis e some com o achado de verdade. Aqui ele fica como
    uma nota so, marcada para a tela nao oferecer "usar esta URL".
    """
    by_port: dict[int, list[dict]] = {}
    for item in found:
        by_port.setdefault(item["port"], []).append(item)

    out: list[dict] = []
    for items in by_port.values():
        if any(i["status"] in USEFUL_STATUSES for i in items):
            out.extend(i for i in items if i["status"] in USEFUL_STATUSES)
            continue
        root = next((i for i in items if i["path"] == "/"), items[0])
        out.append({**root, "generico": True})
    return out


def probe_ports(host: str, ports: list[int], query_timeout: float = 3.0) -> list[dict]:
    """Dispara um A2S_INFO em cada porta candidata, todas ao mesmo tempo."""
    results: dict[int, dict] = {}
    lock = threading.Lock()

    def test(port: int) -> None:
        item: dict[str, Any] = {"port": port, "ok": False, "players": None, "max_players": None,
                                 "server_name": "", "error": ""}
        try:
            info = query_players(host, port, timeout=query_timeout)
            item.update({
                "ok": True, "players": info["players"], "max_players": info["max_players"],
                "server_name": info["server_name"],
            })
        except QueryError as exc:
            item["error"] = str(exc)
        with lock:
            results[port] = item

    threads = [threading.Thread(target=test, args=(p,), daemon=True) for p in ports]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=query_timeout * 2 + 2)
    return [results.get(p, {"port": p, "ok": False, "error": "tempo esgotado"}) for p in ports]
