"""Leitor de metricas (gamepanel.runtime.metrics_probe): CPU, memoria, disco e rede a
partir da saida crua do METRICS_SCRIPT.

Nao existia suite dedicada para isso antes da Fase 4 (mesmo achado do A2S: so
exercitado indiretamente, e boa parte dos testes de alerta troca `server_metrics`
inteiro por um fake, nunca chegando a `parse_metrics`). As linhas abaixo imitam
exatamente o formato que o script remoto imprime.
"""
from __future__ import annotations

import pytest

from gamepanel.runtime import metrics_probe as mp


def _sample(uptime: float, cpu_usec: str, stat: str, net: str, proc_ticks: int) -> str:
    return f"sample|{uptime}|{cpu_usec}|{stat}|{net}|{proc_ticks}"


def _linhas(*partes: str) -> str:
    return "\n".join(partes) + "\n"


def test_duas_amostras_calculam_cpu_pelo_cgroup():
    """cpu.stat existe (cgroup v2): a conta usa usage_usec, nao /proc/stat."""
    raw = _linhas(
        _sample(100.0, "1000000", "0|0", "0|0", 0),  # 1s de CPU usada
        _sample(101.0, "1500000", "0|0", "0|0", 0),  # +0.5s num intervalo de 1s
        "cores|1",
    )
    out = mp.parse_metrics(raw)
    assert out["cpu_pct"] == pytest.approx(50.0)


def test_cpu_cai_no_proc_stat_quando_cgroup_nao_tem_cpu_stat():
    """Sem cpu.stat (containers antigos, cgroup v1 sem o arquivo): usa /proc/stat."""
    raw = _linhas(
        _sample(100.0, "-", "1000|200", "0|0", 0),
        _sample(101.0, "-", "1200|220", "0|0", 0),
        "cores|1",
    )
    out = mp.parse_metrics(raw)
    # total subiu 200, idle subiu 20: 180/200 = 90% ocupado.
    assert out["cpu_pct"] == pytest.approx(90.0)


def test_cpu_pct_e_none_com_uma_amostra_so():
    raw = _linhas(_sample(100.0, "1000000", "0|0", "0|0", 0), "cores|1")
    out = mp.parse_metrics(raw)
    assert out["cpu_pct"] is None


def test_rede_e_a_diferenca_dividida_pelo_tempo():
    raw = _linhas(
        _sample(100.0, "-", "0|0", "1000|2000", 0),
        _sample(102.0, "-", "0|0", "3000|2500", 0),
        "cores|1",
    )
    out = mp.parse_metrics(raw)
    assert out["net_rx"] == pytest.approx(1000.0)  # (3000-1000)/2s
    assert out["net_tx"] == pytest.approx(250.0)   # (2500-2000)/2s


def test_cpu_do_processo_usa_os_ticks_e_o_clk_tck():
    raw = _linhas(
        _sample(100.0, "-", "0|0", "0|0", 100),
        _sample(101.0, "-", "0|0", "0|0", 150),
        "cores|1",
        "tick|100",
        "proc|42|1024",
    )
    out = mp.parse_metrics(raw)
    # 50 ticks a 100 ticks/s = 0.5s de CPU do processo, num intervalo de 1s = 50%.
    assert out["proc"]["cpu_pct"] == pytest.approx(50.0)
    assert out["proc"]["pid"] == 42
    assert out["proc"]["rss"] == 1024 * 1024  # rss vem em kB, sai em bytes


def test_cpu_max_do_cgroup_dita_o_numero_de_cores_fracionario():
    """cpu.max = '150000 100000' -> 1.5 cores, nao o nproc inteiro."""
    raw = _linhas("cores|4", "cpumax|150000 100000")
    out = mp.parse_metrics(raw)
    assert out["cores"] == 1.5


def test_cpu_max_max_nao_sobrescreve_cores():
    raw = _linhas("cores|4", "cpumax|max 100000")
    out = mp.parse_metrics(raw)
    assert out["cores"] == 4


def test_memoria_usa_meminfo_quando_nao_ha_cgroup():
    raw = _linhas("meminfo|MemTotal:|8000000", "meminfo|MemAvailable:|2000000")
    out = mp.parse_metrics(raw)
    assert out["mem"]["total"] == 8000000 * 1024
    assert out["mem"]["used"] == 6000000 * 1024
    assert out["mem"]["pct"] == pytest.approx(75.0)


def test_memoria_do_cgroup_manda_quando_e_menor_que_a_da_maquina():
    """Container com limite de RAM: o cgroup mostra o teto real, nao a RAM do host."""
    raw = _linhas(
        "meminfo|MemTotal:|16000000", "meminfo|MemAvailable:|10000000",
        "cgmem|1000000000|2000000000",
    )
    out = mp.parse_metrics(raw)
    assert out["mem"]["total"] == 2000000000
    assert out["mem"]["used"] == 1000000000


def test_memoria_do_cgroup_sem_limite_maximo_nao_e_usada():
    """cgmem com max=max (sem teto): quem manda continua sendo o /proc/meminfo."""
    raw = _linhas(
        "meminfo|MemTotal:|16000000", "meminfo|MemAvailable:|10000000",
        "cgmem|500000000|max",
    )
    out = mp.parse_metrics(raw)
    assert out["mem"]["total"] == 16000000 * 1024


def test_swap_e_calculado_como_total_menos_livre():
    raw = _linhas("meminfo|SwapTotal:|1000000", "meminfo|SwapFree:|400000")
    out = mp.parse_metrics(raw)
    assert out["swap"]["total"] == 1000000 * 1024
    assert out["swap"]["used"] == 600000 * 1024
    assert out["swap"]["pct"] == pytest.approx(60.0)


def test_disco_ordena_por_ponto_de_montagem():
    raw = _linhas(
        "disk|/opt/game|100000000|50000000",
        "disk|/|200000000|100000000",
    )
    out = mp.parse_metrics(raw)
    montagens = [d["mount"] for d in out["disks"]]
    assert montagens == ["/", "/opt/game"]
    assert out["disks"][0]["pct"] == pytest.approx(50.0)


def test_disco_cheio_nao_estoura_100_por_cento():
    """used > total (medida numa janela de corrida) nao pode virar 105%."""
    raw = _linhas("disk|/|1000|1200")
    out = mp.parse_metrics(raw)
    assert out["disks"][0]["pct"] == 100.0


def test_linha_desconhecida_e_ignorada_sem_quebrar():
    raw = _linhas("algumacoisaquenaoexiste|1|2|3", "cores|2")
    out = mp.parse_metrics(raw)
    assert out["cores"] == 2


def test_linha_curta_demais_para_a_tag_e_ignorada():
    """'disk' precisa de 4 campos; com so 2 a linha e descartada, nao derruba o parser."""
    raw = _linhas("disk|/", "cores|1")
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
    raw = _linhas("load|0.10 0.20 0.15", "boot|123456.7")
    out = mp.parse_metrics(raw)
    assert out["load"] == "0.10 0.20 0.15"
    assert out["uptime"] == pytest.approx(123456.7)
