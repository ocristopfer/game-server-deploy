"""Discovers how to count players: the game opens its sockets inside the container, and
instead of guessing the query port, the panel asks the container itself which ports are
listening, WHO opened them, and tests them one by one. UDP becomes an A2S query; TCP
becomes an HTTP probe (that is where admin APIs live).
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Any

from gamepanel.runtime import remote_cmd
from gamepanel.runtime.a2s import QueryError, query_players
from gamepanel.runtime.ssh import RemoteError, ServerLike

# Everything comes from /proc: 'ss', 'netstat' and 'lsof' are not installed in every
# container. The approach is the same as `ss -p`: /proc/net/* gives port + socket inode,
# and each process's open descriptors (/proc/PID/fd) say who owns that inode. Knowing the
# owner is what separates the game's port from the noise (sshd, Docker's DNS, some random
# HTTP on a high port).
LISTEN_PORTS_SCRIPT = r"""
set -u

# socket inode -> pid. Since the panel logs in as root, it sees every process.
donos() {
  for dir in /proc/[0-9]*; do
    [ -d "$dir/fd" ] || continue
    ls -l "$dir/fd" 2>/dev/null | awk -v pid="${dir#/proc/}" '
      match($0, /socket:\[[0-9]+\]/) {
        print substr($0, RSTART + 8, RLENGTH - 9), pid
      }'
  done
}

# Column 2 = local address (IP:PORT in hex), 4 = state, 10 = inode. For TCP only
# 0A (LISTEN) matters; for UDP a bound socket already is the open port.
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

# Query ports most Steam games use when nothing is declared.
QUERY_PORT_GUESSES = (27015, 27016, 27005)
# Most common admin API ports: 8212 (Palworld REST), 7777 (Satisfactory HTTPS), 8080
# (the default for anyone writing their own little panel).
API_PORT_GUESSES = (8212, 7777, 8080)
# sshd is the panel itself getting into the container: probing that port only adds noise.
IGNORED_PORTS = (22,)

# Processes that always open ports in a container and are never the game: flagging them
# keeps the list readable without hiding anything from whoever is searching.
INFRA_PROCESSES = frozenset({
    "sshd", "sshd-session", "systemd", "systemd-resolve", "systemd-resolved", "dockerd",
    "containerd", "dnsmasq", "cron", "rsyslogd", "chronyd", "ntpd",
})

MAX_TCP_PORT = 65535
_PARSED_LINE_FIELDS = 4

SshOutput = Callable[[ServerLike, str, int], str]




def _ports_from_text(text: str) -> list[int]:
    """Extracts port numbers from the free-form 'Game ports' field (e.g. '8211/udp 27015/udp')."""
    return [int(n) for n in re.findall(r"\d{2,5}", text or "") if 1 <= int(n) <= MAX_TCP_PORT]


def _without_repeats(ports: list[int]) -> list[int]:
    out: list[int] = []
    for port in ports:
        if 1 <= port <= MAX_TCP_PORT and port not in out and port not in IGNORED_PORTS:
            out.append(port)
    return out


def _read_open_ports(raw: str, listening: dict[str, list[int]], owners: dict[tuple[str, int], dict]) -> None:
    """Fills `listening` and `owners` with what LISTEN_PORTS_SCRIPT returned.

    Each line is "<proto> <port> <pid> <process name>". A line without that shape is
    silently ignored: the script parses /proc by hand, and an odd container may return
    something that does not match - missing a port in the list is better than bringing
    down the whole wizard.
    """
    for line in raw.splitlines():
        fields = line.split(None, 3)
        if len(fields) != _PARSED_LINE_FIELDS or fields[0] not in listening or not fields[1].isdigit():
            continue
        proto, port, pid, name = fields[0], int(fields[1]), fields[2], fields[3]
        listening[proto].append(port)
        # Same port on IPv4 and IPv6: keep the first one that could tell the owner.
        if owners.get((proto, port), {}).get("proc", "?") == "?":
            owners[(proto, port)] = {
                "pid": int(pid) if pid.isdigit() else 0,
                "proc": name.strip() or "?",
                "infra": name.strip() in INFRA_PROCESSES,
            }


def candidate_ports(
    ssh_output: SshOutput, server: ServerLike, game_port_field: str,
) -> tuple[list[int], list[int], dict[tuple[str, int], dict], str]:
    """Ports to test (UDP, TCP), who opened each one, and the warning if reading failed.

    The list comes from the container (ports actually open, with the owning process) and
    only then gets the ports declared in the server record and the known guesses, as a
    safety net for when the server is stopped - at that point there is no socket to detect.
    """
    listening: dict[str, list[int]] = {"udp": [], "tcp": []}
    owners: dict[tuple[str, int], dict] = {}
    warning = ""
    try:
        # As steam in helper mode: /proc/<pid>/fd of the game is steam's, so the game's own
        # sockets still get their owner; a root-owned one shows up without it, which is the
        # honest answer for a user that cannot look at root's processes.
        raw = ssh_output(server, remote_cmd.as_steam(server, "bash", "-lc", LISTEN_PORTS_SCRIPT, "gp"), 60)
        _read_open_ports(raw, listening, owners)
    except (RemoteError, ValueError) as exc:
        warning = f"nao consegui listar as portas abertas do container: {exc}"

    def priority(proto: str, port: int) -> int:
        """Ports with a real owning process first; infra last.

        In between are the ownerless ones: a socket exists, but no process in THIS
        container opened it (Docker's DNS resolver, for example, which lives outside the
        namespace).
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
    """Attaches the owning process to each probed port, so the screen can show it.

    Three different states, and the screen needs to know which is which:
    'detectada'  - the socket exists and the owning process was identified;
    'sem-dono'   - the socket exists, but no process in this container opened it;
    'nao-vista'  - the port was not even open (it came from the record or the guess list).
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


# HTTP probe of the TCP ports. Runs inside the container (a single SSH round trip for
# all ports) because admin APIs usually listen only on 127.0.0.1 - from outside the
# container they would look closed.
#
# Two stages per port: first a GET on "/" just to learn whether it speaks HTTP; only
# ports that answer something get the known paths. That way a non-HTTP port costs one
# attempt, not six.
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
      # Nothing over HTTP: it may be an API that only accepts TLS (Satisfactory is like that).
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

# Statuses meaning "found something": 200 is a reply, 401/403 is "there is an API here,
# it just wants a password". Anything else is an HTTP server that does not know the route.
USEFUL_STATUSES = (200, 401, 403)


def probe_http_ports(
    ssh_output: SshOutput, server: ServerLike, ports: list[int], probe_timeout: float = 2.0,
) -> tuple[list[dict], list[int], str]:
    """Probes the TCP ports with HTTP. Returns (what answered, silent ports, warning)."""
    ports = ports[:HTTP_PROBE_PORTS_MAX]
    if not ports:
        return [], [], ""
    # Worst case: 2 attempts at the root + 6 paths, per port.
    limit = int(probe_timeout * 8 * len(ports)) + 20
    try:
        raw = ssh_output(
            server,
            # Plain HTTP requests from inside the container: no right needed, in either mode.
            remote_cmd.unprivileged(
                "bash", "-lc", HTTP_PROBE_SCRIPT, "gp", f"{probe_timeout:g}", *(str(p) for p in ports)),
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
    # JSON first, then those that asked for a password (401/403 = "there is an API here").
    found.sort(key=lambda a: (
        0 if "json" in a["content_type"] else 1,
        0 if a["status"] in USEFUL_STATUSES else 1,
        a["port"], a["path"],
    ))
    silent = [p for p in ports if p not in answered]
    return found, silent, ""


def _summarize_generic(found: list[dict]) -> list[dict]:
    """A port that answered 404 to everything becomes ONE line, not seven.

    Some random process running HTTP on a high port (the Steam client does this) fills
    the screen with useless lines and buries the real finding. Here it stays as a single
    note, flagged so the screen does not offer "use this URL".
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
    """Fires an A2S_INFO at each candidate port, all at the same time."""
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
