"""Toy broker for the development compose (docker compose up).

It is the REAL broker (catalog, allocator, quotas, API, audit) with fake backends: nothing
here touches Proxmox, OPNsense or SSH. The installer only pretends to take time, so the panel
screen has progress to show. The state lives in /tmp on purpose: it goes away with the
container, so the fake Proxmox (in memory) and the database never get out of sync.

    python3 -m gamebroker.dev
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from gamebroker.app import create_app
from gamebroker.persistence.db import Db
from gamebroker.runtime.fakes import FakeCompute, FakeIngress, FakeNetwork
from gamebroker.services.allocator import AllocatedPort, ips_in_range
from gamebroker.services.catalog import Catalog, Game
from gamebroker.services.instance_service import Config, Service


class SlowInstaller:
    """Fakes the installation: one step every `passo` seconds, with a log."""

    def __init__(self, step: float):
        self._step = step

    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None], cancel: threading.Event | None = None) -> None:
        stages = (
            f"aguardando o SSH de {ip}", "instalando os pacotes base", "baixando o SteamCMD",
            f"baixando {game.name} (app {game.app_id})", "criando o servico systemd",
            "removendo a chave do broker do container",
        )
        for stage in stages:
            # Cancellable wait: this is what lets the "cancel" button be tested in the dev compose.
            if cancel is not None:
                if cancel.wait(self._step):
                    raise RuntimeError("instalacao cancelada")
            else:
                time.sleep(self._step)
            log(stage)


def main() -> None:
    token = Path(os.environ["BROKER_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    # `/tmp` as the default is fine because this module is the compose's TOY broker and is
    # not part of the release (see `SKIPPED_NAMES`). The production one gets `BROKER_STATE_DIR`
    # from provisioning, under /var/lib, with its own owner and mode.
    state_dir = Path(os.environ.get("BROKER_DEV_ESTADO", "/tmp/broker-dev"))  # noqa: S108
    state_dir.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(Path(os.environ.get("BROKER_GAMES_DIR", "games")), state_dir / "dinamico")
    service = Service(
        Db(str(state_dir / "broker.db")), catalog, FakeCompute(), FakeIngress(),
        SlowInstaller(float(os.environ.get("BROKER_DEV_PASSO", "1.5"))), FakeNetwork(),
        Config(ctid_base=200, ips=ips_in_range("10.77.0", 102, 199)))
    # Requests land in the toy's state dir and nothing reads them: there is no root updater in the
    # compose, so the panel's broker update screen shows "never ran" and its buttons still answer.
    app = create_app(service, token, update_dir=str(state_dir / "update"),
                     update_status=str(state_dir / "update-status.json"))
    # Listening on all interfaces is only acceptable here: this module is the TOY broker of
    # the dev compose (fake backends) and is not part of the release package - see
    # `SKIPPED_NAMES` in tools/build-release.py. The production one runs under gunicorn with TLS.
    app.run(host="0.0.0.0", port=int(os.environ.get("BROKER_PORT", "8090")), threaded=True)  # noqa: S104  # NOSONAR - dev compose only


if __name__ == "__main__":
    main()
