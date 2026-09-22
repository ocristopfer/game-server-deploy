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

from gamebroker.app import criar_app
from gamebroker.persistence.db import Banco
from gamebroker.runtime.fakes import OpnsenseFalso, ProxmoxFalso, RedeFalsa
from gamebroker.services.allocator import AllocatedPort, ips_da_faixa
from gamebroker.services.catalog import Catalog, Game
from gamebroker.services.instance_service import Config, Servico


class InstaladorLento:
    """Finge a instalacao: uma etapa a cada `passo` segundos, com log."""

    def __init__(self, passo: float):
        self._passo = passo

    def instalar(self, ip: str, jogo: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None]) -> None:
        etapas = (
            f"aguardando o SSH de {ip}", "instalando os pacotes base", "baixando o SteamCMD",
            f"baixando {jogo.name} (app {jogo.app_id})", "criando o servico systemd",
            "removendo a chave do broker do container",
        )
        for etapa in etapas:
            time.sleep(self._passo)
            log(etapa)


def main() -> None:
    token = Path(os.environ["BROKER_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    estado = Path(os.environ.get("BROKER_DEV_ESTADO", "/tmp/broker-dev"))
    estado.mkdir(parents=True, exist_ok=True)
    catalogo = Catalog(Path(os.environ.get("BROKER_GAMES_DIR", "games")), estado / "dinamico")
    servico = Servico(
        Banco(str(estado / "broker.db")), catalogo, ProxmoxFalso(), OpnsenseFalso(),
        InstaladorLento(float(os.environ.get("BROKER_DEV_PASSO", "1.5"))), RedeFalsa(),
        Config(ctid_base=200, ips=ips_da_faixa("10.77.0", 102, 199)))
    app = criar_app(servico, token)
    app.run(host="0.0.0.0", port=int(os.environ.get("BROKER_PORT", "8090")), threaded=True)  # NOSONAR - so no compose de dev


if __name__ == "__main__":
    main()
