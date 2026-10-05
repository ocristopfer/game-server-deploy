"""Metrics reader (gamepanel.runtime.metrics_probe): CPU, memory, disk and network from
the raw output of METRICS_SCRIPT.

There was no dedicated suite for this before Phase 4 (same finding as A2S: only
exercised indirectly, and many of the alert tests swap the whole `server_metrics` for a
fake, never reaching `parse_metrics`). The lines below mimic exactly the format the
remote script prints.
"""
from __future__ import annotations

import pytest

from gamepanel.runtime import metrics_probe as mp


def _sample(uptime: float, cpu_usec: str, stat: str, net: str, proc_ticks: int) -> str:
    return f"sample|{uptime}|{cpu_usec}|{stat}|{net}|{proc_ticks}"


def _lines(*partes: str) -> str:
    return "\n".join(partes) + "\n"


def test_duas_amostras_calculam_cpu_pelo_cgroup():
    """cpu.stat exists (cgroup v2): the math uses usage_usec, not /proc/stat."""
    raw = _lines(
        _sample(100.0, "1000000", "0|0", "0|0", 0),  # 1s of CPU used
        _sample(101.0, "1500000", "0|0", "0|0", 0),  # +0.5s in a 1s interval
        "cores|1",
    )
    out = mp.parse_metrics(raw)
    assert out["cpu_pct"] == pytest.approx(50.0)


def test_cpu_cai_no_proc_stat_quando_cgroup_nao_tem_cpu_stat():
    """No cpu.stat (old containers, cgroup v1 without the file): uses /proc/stat."""
    raw = _lines(
        _sample(100.0, "-", "1000|200", "0|0", 0),
        _sample(101.0, "-", "1200|220", "0|0", 0),
        "cores|1",
    )
    out = mp.parse_metrics(raw)
    # total went up 200, idle went up 20: 180/200 = 90% busy.
    assert out["cpu_pct"] == pytest.approx(90.0)


def test_cpu_pct_e_none_com_uma_amostra_so():
    raw = _lines(_sample(100.0, "1000000", "0|0", "0|0", 0), "cores|1")
    out = mp.parse_metrics(raw)
    assert out["cpu_pct"] is None


def test_rede_e_a_diferenca_dividida_pelo_tempo():
    raw = _lines(
        _sample(100.0, "-", "0|0", "1000|2000", 0),
        _sample(102.0, "-", "0|0", "3000|2500", 0),
        "cores|1",
    )
    out = mp.parse_metrics(raw)
    assert out["net_rx"] == pytest.approx(1000.0)  # (3000-1000)/2s
    assert out["net_tx"] == pytest.approx(250.0)   # (2500-2000)/2s


def test_cpu_do_processo_usa_os_ticks_e_o_clk_tck():
    raw = _lines(
        _sample(100.0, "-", "0|0", "0|0", 100),
        _sample(101.0, "-", "0|0", "0|0", 150),
        "cores|1",
        "tick|100",
        "proc|42|1024",
    )
    out = mp.parse_metrics(raw)
    # 50 ticks at 100 ticks/s = 0.5s of process CPU, in a 1s interval = 50%.
    assert out["proc"]["cpu_pct"] == pytest.approx(50.0)
    assert out["proc"]["pid"] == 42
    assert out["proc"]["rss"] == 1024 * 1024  # rss comes in kB, goes out in bytes


def test_cpu_max_do_cgroup_dita_o_numero_de_cores_fracionario():
    """cpu.max = '150000 100000' -> 1.5 cores, not the whole nproc."""
    raw = _lines("cores|4", "cpumax|150000 100000")
    out = mp.parse_metrics(raw)
    assert out["cores"] == 1.5


def test_cpu_max_max_nao_sobrescreve_cores():
    raw = _lines("cores|4", "cpumax|max 100000")
    out = mp.parse_metrics(raw)
    assert out["cores"] == 4


def test_memoria_usa_meminfo_quando_nao_ha_cgroup():
    raw = _lines("meminfo|MemTotal:|8000000", "meminfo|MemAvailable:|2000000")
    out = mp.parse_metrics(raw)
    assert out["mem"]["total"] == 8000000 * 1024
    assert out["mem"]["used"] == 6000000 * 1024
    assert out["mem"]["pct"] == pytest.approx(75.0)


def test_memoria_do_cgroup_manda_quando_e_menor_que_a_da_maquina():
    """A container with a RAM limit: the cgroup shows the real ceiling, not the host's RAM."""
    raw = _lines(
        "meminfo|MemTotal:|16000000", "meminfo|MemAvailable:|10000000",
        "cgmem|1000000000|2000000000",
    )
    out = mp.parse_metrics(raw)
    assert out["mem"]["total"] == 2000000000
    assert out["mem"]["used"] == 1000000000


def test_memoria_do_cgroup_sem_limite_maximo_nao_e_usada():
    """cgmem with max=max (no ceiling): /proc/meminfo is still what counts."""
    raw = _lines(
        "meminfo|MemTotal:|16000000", "meminfo|MemAvailable:|10000000",
        "cgmem|500000000|max",
    )
    out = mp.parse_metrics(raw)
    assert out["mem"]["total"] == 16000000 * 1024


def test_swap_e_calculado_como_total_menos_livre():
    raw = _lines("meminfo|SwapTotal:|1000000", "meminfo|SwapFree:|400000")
    out = mp.parse_metrics(raw)
    assert out["swap"]["total"] == 1000000 * 1024
    assert out["swap"]["used"] == 600000 * 1024
    assert out["swap"]["pct"] == pytest.approx(60.0)


def test_disco_ordena_por_ponto_de_montagem():
    raw = _lines(
        "disk|/opt/game|100000000|50000000",
        "disk|/|200000000|100000000",
    )
    out = mp.parse_metrics(raw)
    builds = [d["mount"] for d in out["disks"]]
    assert builds == ["/", "/opt/game"]
    assert out["disks"][0]["pct"] == pytest.approx(50.0)


def test_disco_cheio_nao_estoura_100_por_cento():
    """used > total (measured in a race window) must not become 105%."""
    raw = _lines("disk|/|1000|1200")
    out = mp.parse_metrics(raw)
    assert out["disks"][0]["pct"] == 100.0


def test_linha_desconhecida_e_ignorada_sem_quebrar():
    raw = _lines("algumacoisaquenaoexiste|1|2|3", "cores|2")
    out = mp.parse_metrics(raw)
    assert out["cores"] == 2


def test_linha_curta_demais_para_a_tag_e_ignorada():
    """'disk' needs 4 fields; with only 2 the line is discarded, it does not bring the parser down."""
    raw = _lines("disk|/", "cores|1")
    out = mp.parse_metrics(raw)
    assert out["disks"] == []
    assert out["cores"] == 1


def test_saida_vazia_devolve_os_valores_padrao_sem_erro():
    out = mp.parse_metrics("")
    assert out["cores"] == 1
    assert out["cpu_pct"] is None
    assert out["disks"] == []
    assert out["mem"]["pct"] is None


def test_carga_e_uptime_saem_como_vieram():
    raw = _lines("load|0.10 0.20 0.15", "boot|123456.7")
    out = mp.parse_metrics(raw)
    assert out["load"] == "0.10 0.20 0.15"
    assert out["uptime"] == pytest.approx(123456.7)
