"""Production broker: builds the `Servico` with REAL Proxmox, OPNsense and SSH.

systemd starts it like this (see provision-broker-lxc.sh):

    gunicorn --workers 1 --threads 8 --certfile ... --keyfile ... 'gamebroker.prod:criar_app_de_ambiente()'

ONE worker on purpose: the lock that prevents two creations from picking the same IP lives in
the process memory (the database has UNIQUE as a second defense, but the user experience is
better without depending on it). Bad configuration brings down the START with the list of
problems, never a request.
"""
from __future__ import annotations

import base64
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

from flask import Flask

from gamebroker.app import create_app
from gamebroker.config import ConfigBroker, ConfigError, load
from gamebroker.integrations.http_client import Client
from gamebroker.persistence.db import Db
from gamebroker.runtime.base import Network
from gamebroker.runtime.network import RealNetwork
from gamebroker.runtime.opnsense import Opnsense
from gamebroker.runtime.proxmox import Proxmox
from gamebroker.runtime.ssh_installer import Executor, SshInstaller
from gamebroker.services.catalog import Catalog
from gamebroker.services.instance_service import Config, Service


def build_service(cfg: ConfigBroker, executor: Executor | None = None, network: Network | None = None,
                   run: Callable[[Callable[[], None]], None] | None = None) -> Service:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    proxmox = Proxmox(Client(cfg.proxmox_url, {"Authorization": f"PVEAPIToken={cfg.proxmox_token}"},
                              cfg.proxmox_fingerprint), cfg.proxmox)
    basic = base64.b64encode(f"{cfg.opnsense_key}:{cfg.opnsense_secret}".encode()).decode()
    opnsense = Opnsense(Client(cfg.opnsense_url, {"Authorization": f"Basic {basic}"},
                                cfg.opnsense_fingerprint), cfg.opnsense_wan)
    # `dict[str, Any]`: the dict exists to become `**` in a constructor whose parameters have
    # different types. Without the annotation the checker narrows it to the type of `run` and
    # flags all the others - see the same pattern, with the same reason, in `config.py`.
    extra: dict[str, Any] = {} if run is None else {"run": run}
    return Service(
        Db(str(cfg.state_dir / "broker.db")),
        Catalog(cfg.games_dir, cfg.state_dir / "dinamico", steam_account=cfg.ssh.steam is not None),
        proxmox, opnsense, SshInstaller(cfg.ssh, executor), network or RealNetwork(),
        Config(ctids=cfg.ctids, ctid_base=cfg.ctid_base, ips=cfg.ips, ports=cfg.ports,
               max_instances=cfg.max_instances, max_creations_per_hour=cfg.max_creations_per_hour),
        **extra)


def create_app_from_config(cfg: ConfigBroker, **kwargs) -> Flask:
    return create_app(build_service(cfg, **kwargs), cfg.token, cfg.allowed_ips)


def create_app_from_env(env: Mapping[str, str] | None = None) -> Flask:
    try:
        cfg = load(os.environ if env is None else env)
    except ConfigError as error:
        print(f"[broker] NAO SUBIU: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    return create_app_from_config(cfg)
