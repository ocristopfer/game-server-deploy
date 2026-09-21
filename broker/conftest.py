"""Cenario compartilhado das suites do broker.

Tudo aqui e falso: Proxmox, OPNsense, SSH e rede sao os backends de `fakes.py`, e o
relogio e uma variavel que o teste avanca. Nenhum teste toca a rede de verdade.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from broker.alocador import ips_da_faixa
from broker.banco import Banco
from broker.catalogo import Catalogo
from broker.conexao import Cliente
from broker.fakes import InstaladorFalso, OpnsenseFalso, ProxmoxFalso, RedeFalsa
from broker.http_falso import KEY_OPN, SECRET_OPN, TOKEN_PVE, OpnsenseHttpFalso, PveFalso, ServidorFalso
from broker.opnsense import Opnsense
from broker.proxmox import ConfigProxmox, Proxmox
from broker.servico import Config, Servico

TOKEN = "t" * 40

ENV_ALFA = """GAME_KEY=alfa
GAME_DISPLAY_NAME="Alfa"
STEAM_APP_ID=1001
START_SCRIPT=alfa.sh
START_ARGS="-port={PORT}"
GAME_PORT=7001
GAME_PORTS="7001/udp 7002/udp"
QUERY_PORT=7002
POST_INSTALL_CMD='
echo "segredo do instalador"
'
"""
ENV_BETA = """GAME_KEY=beta
GAME_DISPLAY_NAME="Beta"
STEAM_APP_ID=1002
GAME_PORT=8001
GAME_PORTS="8001/udp 8002/udp"
QUERY_PORT=8002
PORTS_SHIFTABLE=1
"""
# Usa a mesma porta de query que o alfa: a colisao e entre JOGOS diferentes.
ENV_DELTA = """GAME_KEY=delta
STEAM_APP_ID=1003
GAME_PORT=7100
GAME_PORTS="7100/udp 7002/udp"
"""
ENV_CONTA = """GAME_KEY=conta
STEAM_APP_ID=1004
STEAM_ANONYMOUS=0
GAME_PORT=7200
GAME_PORTS="7200/udp"
"""


class Relogio:
    def __init__(self) -> None:
        self._agora = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._agora

    def avancar(self, minutos: int) -> None:
        self._agora += timedelta(minutes=minutos)


@pytest.fixture
def dados_de_jogo() -> dict:
    """Um jogo dinamico valido. Cada teste recebe uma copia nova para estragar a vontade."""
    return {
        "chave": "meujogo", "nome": "Meu Jogo", "app_id": 123456,
        "portas": ["7777/udp", "27016/udp"], "porta_jogo": 7777, "porta_query": 27016,
        "start_script": "Server.sh", "start_args": "-port={PORT} -queryport={QUERY_PORT}",
        "config_path": "/opt/game/Config", "config_files": ["/opt/game/Config/a.ini"],
        "backup_paths": ["/opt/game/Saves"], "player_source": "log",
        "join_re": r"(?P<name>.+?) joined", "leave_re": r"(?P<name>.+?) left",
        "receitas": ["steamclient-sdk64"], "deslocavel": True,
    }


@pytest.fixture
def pasta_de_jogos(tmp_path: Path) -> Path:
    pasta = tmp_path / "games"
    pasta.mkdir()
    for nome, texto in (("alfa", ENV_ALFA), ("beta", ENV_BETA), ("delta", ENV_DELTA), ("conta", ENV_CONTA)):
        (pasta / f"{nome}.env").write_text(texto, encoding="utf-8")
    (pasta / "_template.env").write_text("GAME_KEY=modelo\n", encoding="utf-8")
    return pasta


@pytest.fixture
def catalogo(tmp_path: Path, pasta_de_jogos: Path) -> Catalogo:
    return Catalogo(pasta_de_jogos, tmp_path / "dinamico")


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def ambiente(tmp_path: Path, catalogo: Catalogo, relogio: Relogio):
    """Servico completo com backends falsos e execucao SINCRONA (a criacao termina dentro
    de `criar`). `ambiente.pendentes` guarda as tarefas quando `adiar` esta ligado."""
    banco = Banco(str(tmp_path / "broker.db"), relogio=lambda: relogio().isoformat(timespec="seconds"))
    amb = SimpleNamespace(
        banco=banco, catalogo=catalogo, relogio=relogio, adiar=False, pendentes=[],
        proxmox=ProxmoxFalso(), opnsense=OpnsenseFalso(), instalador=InstaladorFalso(), rede=RedeFalsa(),
        config=Config(ctids=range(300, 310), ips=ips_da_faixa("10.0.0", 30, 40),
                      max_instancias=5, max_criacoes_por_hora=10),
    )

    def executar(tarefa):
        if amb.adiar:
            amb.pendentes.append(tarefa)
        else:
            tarefa()

    def com_config(**campos) -> None:
        amb.servico.config = replace(amb.config, **campos)

    amb.servico = Servico(banco, catalogo, amb.proxmox, amb.opnsense, amb.instalador, amb.rede,
                          amb.config, executar=executar, relogio=relogio)
    amb.com_config = com_config
    return amb


# --- servidores HTTP falsos + backends reais apontados para eles ----------------------

@pytest.fixture
def pve():
    """Proxmox falso em 127.0.0.1 e o backend REAL `broker.proxmox.Proxmox` falando com ele."""
    falso = PveFalso()
    servidor = ServidorFalso(falso.tratar)
    esperas: list[float] = []
    config = ConfigProxmox(
        node="pve", pool="games", storage="vm-pool", bridge="vmbr1", gateway="192.168.2.1",
        template="vm-pool-data:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst",
        chaves_ssh=("ssh-ed25519 AAAAC3Nza-chave-de-teste broker@teste",))
    cliente = Cliente(servidor.url, {"Authorization": f"PVEAPIToken={TOKEN_PVE}"})
    yield SimpleNamespace(falso=falso, servidor=servidor, config=config, esperas=esperas,
                          backend=Proxmox(cliente, config, dormir=esperas.append))
    servidor.parar()


@pytest.fixture
def opn():
    """OPNsense falso em 127.0.0.1 e o backend REAL `broker.opnsense.Opnsense`."""
    falso = OpnsenseHttpFalso()
    servidor = ServidorFalso(falso.tratar)
    basico = base64.b64encode(f"{KEY_OPN}:{SECRET_OPN}".encode()).decode()
    cliente = Cliente(servidor.url, {"Authorization": f"Basic {basico}"})
    yield SimpleNamespace(falso=falso, servidor=servidor, backend=Opnsense(cliente, "wan"))
    servidor.parar()
