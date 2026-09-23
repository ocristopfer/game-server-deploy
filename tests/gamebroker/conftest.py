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
from fake_http import KEY_OPN, SECRET_OPN, TOKEN_PVE, FakeOpnsenseHttp, FakePve, FakeServer

from gamebroker.integrations.http_client import Client
from gamebroker.persistence.db import Db
from gamebroker.runtime.fakes import FakeInstaller, FakeOpnsense, FakeProxmox, FakeNetwork
from gamebroker.runtime.opnsense import Opnsense
from gamebroker.runtime.proxmox import ConfigProxmox, Proxmox
from gamebroker.services.allocator import ips_in_range
from gamebroker.services.catalog import Catalog
from gamebroker.services.instance_service import Config, Service

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
START_ARGS="-port={PORT} -queryport={QUERY_PORT}"
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


class Clock:
    def __init__(self) -> None:
        self._agora = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._agora

    def advance(self, minutos: int) -> None:
        self._agora += timedelta(minutes=minutos)


@pytest.fixture
def game_data() -> dict:
    """Um jogo dinamico valido. Cada teste recebe uma copia nova para estragar a vontade."""
    return {
        "key": "meujogo", "name": "Meu Jogo", "app_id": 123456,
        "ports": ["7777/udp", "27016/udp"], "game_port": 7777, "query_port": 27016,
        "start_script": "Server.sh", "start_args": "-port={PORT} -queryport={QUERY_PORT}",
        "config_path": "/opt/game/Config", "config_files": ["/opt/game/Config/a.ini"],
        "backup_paths": ["/opt/game/Saves"], "player_source": "log",
        "join_re": r"(?P<name>.+?) joined", "leave_re": r"(?P<name>.+?) left",
        "recipes": ["steamclient-sdk64"], "shiftable": True,
    }


@pytest.fixture
def games_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "games"
    folder.mkdir()
    for name, text in (("alfa", ENV_ALFA), ("beta", ENV_BETA), ("delta", ENV_DELTA), ("conta", ENV_CONTA)):
        (folder / f"{name}.env").write_text(text, encoding="utf-8")
    (folder / "_template.env").write_text("GAME_KEY=modelo\n", encoding="utf-8")
    return folder


@pytest.fixture
def catalog(tmp_path: Path, games_dir: Path) -> Catalog:
    return Catalog(games_dir, tmp_path / "dinamico")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def environment(tmp_path: Path, catalog: Catalog, clock: Clock):
    """Servico completo com backends falsos e execucao SINCRONA (a criacao termina dentro
    de `criar`). `ambiente.pendentes` guarda as tarefas quando `adiar` esta ligado."""
    db = Db(str(tmp_path / "broker.db"), clock=lambda: clock().isoformat(timespec="seconds"))
    env = SimpleNamespace(
        db=db, catalog=catalog, clock=clock, adiar=False, pendentes=[],
        proxmox=FakeProxmox(), opnsense=FakeOpnsense(), installer=FakeInstaller(), network=FakeNetwork(),
        config=Config(ctids=range(300, 310), ips=ips_in_range("10.0.0", 30, 40),
                      ports=range(9000, 9020), max_instances=5, max_creations_per_hour=10),
    )

    def run(tarefa):
        if env.adiar:
            env.pendentes.append(tarefa)
        else:
            tarefa()

    def with_config(**campos) -> None:
        env.servico.config = replace(env.config, **campos)

    env.servico = Service(db, catalog, env.proxmox, env.opnsense, env.installer, env.network,
                          env.config, run=run, clock=clock)
    env.with_config = with_config
    return env


# --- servidores HTTP falsos + backends reais apontados para eles ----------------------

@pytest.fixture
def pve():
    """Proxmox falso em 127.0.0.1 e o backend REAL `gamebroker.proxmox.Proxmox` falando com ele."""
    fake = FakePve()
    server = FakeServer(fake.handle)
    waits: list[float] = []
    config = ConfigProxmox(
        node="pve", pool="games", storage="vm-pool", bridge="vmbr1", gateway="192.168.2.1",
        template="vm-pool-data:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst",
        ssh_keys=("ssh-ed25519 AAAAC3Nza-chave-de-teste broker@teste",))
    client = Client(server.url, {"Authorization": f"PVEAPIToken={TOKEN_PVE}"})
    yield SimpleNamespace(fake=fake, server=server, config=config, esperas=waits,
                          backend=Proxmox(client, config, sleep=waits.append))
    server.stop()


@pytest.fixture
def opn():
    """OPNsense falso em 127.0.0.1 e o backend REAL `gamebroker.opnsense.Opnsense`."""
    fake = FakeOpnsenseHttp()
    server = FakeServer(fake.handle)
    basic = base64.b64encode(f"{KEY_OPN}:{SECRET_OPN}".encode()).decode()
    client = Client(server.url, {"Authorization": f"Basic {basic}"})
    yield SimpleNamespace(fake=fake, server=server, backend=Opnsense(client, "wan"))
    server.stop()
