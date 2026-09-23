"""Le CPU, memoria, disco e rede do container a partir da saida do METRICS_SCRIPT
(rodado por SSH por quem chama - este modulo so sabe interpretar o texto que volta).

Duas amostras espacadas dentro do proprio container: CPU e rede so fazem sentido como
variacao no tempo, e medir com uma unica ida de SSH sai mais barato do que guardar a
amostra anterior aqui e torcer para o intervalo entre telas ser regular.
"""
from __future__ import annotations

from typing import Any

METRICS_SCRIPT = r"""
set -u
CG=/sys/fs/cgroup
unit=$1
dir=$2

cpu_usec() {
  if [ -r "$CG/cpu.stat" ]; then
    awk '/^usage_usec/ { print $2; exit }' "$CG/cpu.stat"
  else
    echo -
  fi
}
# Cada numero sai no seu proprio campo (separador '|'): dois valores num campo so
# fariam o painel ler o total da CPU como texto e zerar a conta.
proc_stat() { awk '/^cpu /{ t=0; for (i=2; i<=NF; i++) t+=$i; printf "%d|%d", t, $5+$6; exit }' /proc/stat; }
# Soma todas as interfaces menos a loopback (rx = campo 2, tx = campo 10 apos o ':').
net_bytes() {
  awk 'NR>2 { sub(/:/, " "); if ($1 != "lo") { rx += $2; tx += $10 } }
       END { printf "%d|%d", rx+0, tx+0 }' /proc/net/dev
}
pid_ticks() {
  if [ "$1" -gt 0 ] && [ -r "/proc/$1/stat" ]; then
    awk '{ print $14 + $15 }' "/proc/$1/stat"
  else
    echo 0
  fi
}

pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
case "$pid" in ''|*[!0-9]*) pid=0 ;; esac

amostra() {
  printf 'sample|%s|%s|%s|%s|%s\n' \
    "$(awk '{ print $1; exit }' /proc/uptime)" \
    "$(cpu_usec)" "$(proc_stat)" "$(net_bytes)" "$(pid_ticks "$pid")"
}

amostra
sleep 0.5
amostra

printf 'cores|%s\n' "$(nproc 2>/dev/null || echo 1)"
# cpu.max = "<quota> <periodo>" (ou "max"): e o teto real quando o container tem
# limite de CPU (cpulimit no Proxmox), que o nproc sozinho nao mostra.
[ -r "$CG/cpu.max" ] && printf 'cpumax|%s\n' "$(cat "$CG/cpu.max")"
printf 'tick|%s\n' "$(getconf CLK_TCK 2>/dev/null || echo 100)"
printf 'load|%s\n' "$(cut -d' ' -f1-3 /proc/loadavg)"
printf 'boot|%s\n' "$(awk '{ print $1; exit }' /proc/uptime)"
awk '/^MemTotal:|^MemAvailable:|^SwapTotal:|^SwapFree:/ { printf "meminfo|%s|%s\n", $1, $2 }' /proc/meminfo
# Em container o cgroup e mais honesto que o /proc/meminfo quando nao ha lxcfs.
[ -r "$CG/memory.current" ] && printf 'cgmem|%s|%s\n' \
  "$(cat "$CG/memory.current")" "$(cat "$CG/memory.max" 2>/dev/null || echo max)"
df -P -B1 / "$dir" 2>/dev/null | awk 'NR>1 { printf "disk|%s|%s|%s\n", $6, $2, $3 }'
printf 'proc|%s|%s\n' "$pid" \
  "$(awk '/^VmRSS:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || echo 0)"
"""


def _num(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(max(0.0, min(100.0, part * 100.0 / whole)), 1)


# Uma funcao por linha que o script remoto emite. A chave e a etiqueta da linha e o
# numero e quantos campos ela precisa ter para valer (linha curta e descartada).
def _tag_sample(data: dict[str, Any], parts: list[str]) -> None:
    # uptime | cpu_usec | stat_total | stat_idle | rx | tx | ticks do processo
    data["samples"].append(parts[1:])


def _tag_cores(data: dict[str, Any], parts: list[str]) -> None:
    data["cores"] = max(1.0, _num(parts[1], 1))


def _tag_cpumax(data: dict[str, Any], parts: list[str]) -> None:
    quota, _, period = parts[1].strip().partition(" ")
    if quota != "max" and _num(period) > 0:
        data["cores"] = max(0.1, _num(quota) / _num(period))


def _tag_tick(data: dict[str, Any], parts: list[str]) -> None:
    data["clk_tck"] = max(1.0, _num(parts[1], 100))


def _tag_load(data: dict[str, Any], parts: list[str]) -> None:
    data["load"] = parts[1]


def _tag_boot(data: dict[str, Any], parts: list[str]) -> None:
    data["uptime"] = _num(parts[1])


def _tag_meminfo(data: dict[str, Any], parts: list[str]) -> None:
    data["meminfo"][parts[1].rstrip(":")] = _num(parts[2]) * 1024  # vem em kB


def _tag_cgmem(data: dict[str, Any], parts: list[str]) -> None:
    data["cg_current"] = _num(parts[1])
    data["cg_max"] = None if parts[2].strip() == "max" else _num(parts[2])


def _tag_disk(data: dict[str, Any], parts: list[str]) -> None:
    data["disks"][parts[1]] = {
        "mount": parts[1], "total": _num(parts[2]), "used": _num(parts[3]),
        "pct": _pct(_num(parts[3]), _num(parts[2])),
    }


def _tag_proc(data: dict[str, Any], parts: list[str]) -> None:
    data["pid"] = int(_num(parts[1]))
    data["rss_kb"] = _num(parts[2])


_MIN_SAMPLE_FIELDS = 8
_SAMPLES_FOR_RATE = 2
METRIC_TAGS: dict[str, tuple[int, Any]] = {
    "sample": (_MIN_SAMPLE_FIELDS, _tag_sample),
    "cores": (2, _tag_cores),
    "cpumax": (2, _tag_cpumax),
    "tick": (2, _tag_tick),
    "load": (2, _tag_load),
    "boot": (2, _tag_boot),
    "meminfo": (3, _tag_meminfo),
    "cgmem": (3, _tag_cgmem),
    "disk": (4, _tag_disk),
    "proc": (3, _tag_proc),
}


def _collect_metrics(raw: str) -> dict[str, Any]:
    """Primeira passada: cada linha do script vira uma entrada crua, sem contas."""
    data: dict[str, Any] = {
        "samples": [], "meminfo": {}, "disks": {},
        "cores": 1.0, "clk_tck": 100.0, "load": "", "uptime": 0.0,
        "cg_current": None, "cg_max": None, "pid": 0, "rss_kb": 0.0,
    }
    for line in raw.splitlines():
        parts = line.split("|")
        minimum, handle = METRIC_TAGS.get(parts[0], (0, None))
        if handle and len(parts) >= minimum:
            handle(data, parts)
    return data


def _rates_from_samples(data: dict[str, Any]) -> dict[str, Any]:
    """CPU e rede saem da diferenca entre as duas amostras."""
    out: dict[str, Any] = {"cpu_pct": None, "net_rx": None, "net_tx": None, "proc_cpu_pct": None}
    samples = data["samples"]
    if len(samples) < _SAMPLES_FOR_RATE:
        return out

    a, b = samples[0], samples[-1]
    dt = _num(b[0]) - _num(a[0])
    if dt <= 0:
        return out

    cores = data["cores"]
    # cpu.stat do cgroup mede o container; /proc/stat so acerta com lxcfs no meio.
    if a[1] != "-" and b[1] != "-":
        out["cpu_pct"] = _pct((_num(b[1]) - _num(a[1])) / 1e6, dt * cores)
    else:
        total = _num(b[2]) - _num(a[2])
        out["cpu_pct"] = _pct(total - (_num(b[3]) - _num(a[3])), total)

    out["net_rx"] = max(0.0, (_num(b[4]) - _num(a[4])) / dt)
    out["net_tx"] = max(0.0, (_num(b[5]) - _num(a[5])) / dt)
    if data["pid"]:
        used = (_num(b[6]) - _num(a[6])) / data["clk_tck"]
        out["proc_cpu_pct"] = _pct(used, dt * cores)
    return out


def _memory_from(data: dict[str, Any]) -> dict[str, Any]:
    total = data["meminfo"].get("MemTotal", 0.0)
    used = max(0.0, total - data["meminfo"].get("MemAvailable", 0.0))
    current, ceiling = data["cg_current"], data["cg_max"]
    # Limite do cgroup manda quando existe e e menor que a RAM da maquina: e o teto real
    # do container, e o /proc/meminfo sem lxcfs mostraria a memoria do host inteiro.
    if current is not None and ceiling and (not total or ceiling < total):
        total, used = ceiling, current
    elif current is not None and not total:
        total, used = current, current
    return {"total": total, "used": used, "pct": _pct(used, total)}


def parse_metrics(raw: str) -> dict[str, Any]:
    """Transforma a saida do METRICS_SCRIPT em numeros prontos para a tela."""
    data = _collect_metrics(raw)
    rates = _rates_from_samples(data)
    cores = data["cores"]
    meminfo = data["meminfo"]

    out: dict[str, Any] = {
        # Pode ser fracionario quando o container tem limite de CPU (ex.: 1.5 nucleos).
        "cores": int(cores) if cores == int(cores) else round(cores, 1),
        "load": data["load"], "uptime": data["uptime"],
        "disks": sorted(data["disks"].values(), key=lambda d: d["mount"]),
        "cpu_pct": rates["cpu_pct"],
        "net_rx": rates["net_rx"], "net_tx": rates["net_tx"],
        "proc": {
            "pid": data["pid"],
            "rss": data["rss_kb"] * 1024,
            "cpu_pct": rates["proc_cpu_pct"],
        },
        "mem": _memory_from(data),
    }

    swap_total = meminfo.get("SwapTotal", 0.0)
    swap_used = max(0.0, swap_total - meminfo.get("SwapFree", 0.0))
    out["swap"] = {"total": swap_total, "used": swap_used, "pct": _pct(swap_used, swap_total)}
    return out
