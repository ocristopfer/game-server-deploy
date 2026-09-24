"""Broker de brinquedo para o compose de desenvolvimento (docker compose up).

E o broker de VERDADE (catalogo, alocador, cotas, API, auditoria) com backends falsos: nada
aqui toca Proxmox, OPNsense ou SSH. O instalador so finge demorar, para a tela do painel ter
progresso para mostrar. O estado mora em /tmp de proposito: some junto com o container, e
assim o Proxmox falso (em memoria) e o banco nunca ficam desencontrados.

    python3 -m gamebroker.dev
"""
from __future__ import annotations

import os
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
    """Finge a instalacao: uma etapa a cada `passo` segundos, com log."""

    def __init__(self, step: float):
        self._step = step

    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None]) -> None:
        stages = (
            f"aguardando o SSH de {ip}", "instalando os pacotes base", "baixando o SteamCMD",
            f"baixando {game.name} (app {game.app_id})", "criando o servico systemd",
            "removendo a chave do broker do container",
        )
        for stage in stages:
            time.sleep(self._step)
            log(stage)


def main() -> None:
    token = Path(os.environ["BROKER_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    # `/tmp` como padrao vale porque este modulo e o broker de BRINQUEDO do compose e nao
    # entra no release (ver `SKIPPED_NAMES`). O de producao recebe `BROKER_STATE_DIR` do
    # provisionamento, em /var/lib, com dono e modo proprios.
    state_dir = Path(os.environ.get("BROKER_DEV_ESTADO", "/tmp/broker-dev"))  # noqa: S108
    state_dir.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(Path(os.environ.get("BROKER_GAMES_DIR", "games")), state_dir / "dinamico")
    service = Service(
        Db(str(state_dir / "broker.db")), catalog, FakeCompute(), FakeIngress(),
        SlowInstaller(float(os.environ.get("BROKER_DEV_PASSO", "1.5"))), FakeNetwork(),
        Config(ctid_base=200, ips=ips_in_range("10.77.0", 102, 199)))
    app = create_app(service, token)
    # Ouvir em todas as interfaces so vale aqui: este modulo e o broker de BRINQUEDO do
    # compose de dev (backends falsos) e nao entra no pacote de release — ver
    # `SKIPPED_NAMES` em tools/build-release.py. O de producao sobe por gunicorn com TLS.
    app.run(host="0.0.0.0", port=int(os.environ.get("BROKER_PORT", "8090")), threaded=True)  # noqa: S104  # NOSONAR - so no compose de dev


if __name__ == "__main__":
    main()
