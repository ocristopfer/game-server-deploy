"""Shared setup for the broker suites.

Everything here is fake: Proxmox, OPNsense, SSH and network are the backends from `fakes.py`,
and the clock is a variable the test advances. No test touches the real network.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fake_http import KEY_OPN, SECRET_OPN, TOKEN_PVE, FakeIngressHttp, FakePve, FakeServer

from gamebroker.integrations.http_client import Client
from gamebroker.persistence.db import Db
from gamebroker.runtime.fakes import FakeCompute, FakeIngress, FakeInstaller, FakeNetwork
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
# Uses the same query port as alfa: the collision is between DIFFERENT games.
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
        self._now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, minutes: int) -> None:
        self._now += timedelta(minutes=minutes)


@pytest.fixture
def game_data() -> dict:
    """A valid dynamic game. Each test gets a fresh copy to break as it likes."""
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
    """Full service with fake backends and SYNCHRONOUS execution (creation finishes inside
    `criar`). `ambiente.pendentes` holds the tasks when `adiar` is on."""
    db = Db(str(tmp_path / "broker.db"), clock=lambda: clock().isoformat(timespec="seconds"))
    env = SimpleNamespace(
        db=db, catalog=catalog, clock=clock, defer=False, pending=[],
        compute=FakeCompute(), ingress=FakeIngress(), installer=FakeInstaller(), network=FakeNetwork(),
        config=Config(ctids=range(300, 310), ips=ips_in_range("10.0.0", 30, 40),
                      ports=range(9000, 9020), max_instances=5, max_creations_per_hour=10),
    )

    def run(task):
        if env.defer:
            env.pending.append(task)
        else:
            task()

    def with_config(**fields) -> None:
        env.servico.config = replace(env.config, **fields)

    env.servico = Service(db, catalog, env.compute, env.ingress, env.installer, env.network,
                          env.config, run=run, clock=clock)
    env.with_config = with_config
    return env


# --- fake HTTP servers + real backends pointed at them --------------------------------

@pytest.fixture
def pve():
    """Fake Proxmox on 127.0.0.1 and the REAL `gamebroker.proxmox.Proxmox` backend talking to it."""
    fake = FakePve()
    server = FakeServer(fake.handle)
    waits: list[float] = []
    config = ConfigProxmox(
        node="pve", pool="games", storage="local-lvm", bridge="vmbr0", gateway="10.20.1.1",
        template="local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst",
        ssh_keys=("ssh-ed25519 AAAAC3Nza-chave-de-teste broker@teste",))
    client = Client(server.url, {"Authorization": f"PVEAPIToken={TOKEN_PVE}"})
    yield SimpleNamespace(fake=fake, server=server, config=config, waits=waits,
                          backend=Proxmox(client, config, sleep=waits.append))
    server.stop()


@pytest.fixture
def opn():
    """Fake OPNsense on 127.0.0.1 and the REAL `gamebroker.opnsense.Opnsense` backend."""
    fake = FakeIngressHttp()
    server = FakeServer(fake.handle)
    basic = base64.b64encode(f"{KEY_OPN}:{SECRET_OPN}".encode()).decode()
    client = Client(server.url, {"Authorization": f"Basic {basic}"})
    yield SimpleNamespace(fake=fake, server=server, backend=Opnsense(client, "wan"))
    server.stop()
