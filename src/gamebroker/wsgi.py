"""Broker de producao: monta o `Servico` com Proxmox, OPNsense e SSH DE VERDADE.

O systemd sobe assim (ver provision-broker-lxc.sh):

    gunicorn --workers 1 --threads 8 --certfile ... --keyfile ... 'gamebroker.prod:criar_app_de_ambiente()'

UM worker de proposito: a trava que impede duas criacoes escolherem o mesmo IP vive na memoria
do processo (o banco tem UNIQUE como segunda defesa, mas a experiencia do usuario e melhor sem
depender dele). Configuracao ruim derruba o START com a lista de problemas, nunca um pedido.
"""
from __future__ import annotations

import base64
import os
import sys
from collections.abc import Callable, Mapping

from flask import Flask

from gamebroker.app import criar_app
from gamebroker.config import ConfigBroker, ErroDeConfig, carregar
from gamebroker.integrations.http_client import Cliente
from gamebroker.persistence.db import Banco
from gamebroker.runtime.base import Rede
from gamebroker.runtime.network import RedeReal
from gamebroker.runtime.opnsense import Opnsense
from gamebroker.runtime.proxmox import Proxmox
from gamebroker.runtime.ssh_installer import Executor, InstaladorSsh
from gamebroker.services.catalog import Catalog
from gamebroker.services.instance_service import Config, Servico


def montar_servico(cfg: ConfigBroker, executor: Executor | None = None, rede: Rede | None = None,
                   executar: Callable[[Callable[[], None]], None] | None = None) -> Servico:
    cfg.estado.mkdir(parents=True, exist_ok=True)
    proxmox = Proxmox(Cliente(cfg.proxmox_url, {"Authorization": f"PVEAPIToken={cfg.proxmox_token}"},
                              cfg.proxmox_impressao), cfg.proxmox)
    basico = base64.b64encode(f"{cfg.opnsense_key}:{cfg.opnsense_secret}".encode()).decode()
    opnsense = Opnsense(Cliente(cfg.opnsense_url, {"Authorization": f"Basic {basico}"},
                                cfg.opnsense_impressao), cfg.opnsense_wan)
    argumentos = {} if executar is None else {"executar": executar}
    return Servico(
        Banco(str(cfg.estado / "broker.db")), Catalog(cfg.pasta_games, cfg.estado / "dinamico"),
        proxmox, opnsense, InstaladorSsh(cfg.ssh, executor), rede or RedeReal(),
        Config(ctids=cfg.ctids, ctid_base=cfg.ctid_base, ips=cfg.ips, ports=cfg.portas,
               max_instancias=cfg.max_instancias, max_criacoes_por_hora=cfg.max_criacoes_por_hora),
        **argumentos)


def criar_app_de_config(cfg: ConfigBroker, **kwargs) -> Flask:
    return criar_app(montar_servico(cfg, **kwargs), cfg.token, cfg.ips_permitidos)


def criar_app_de_ambiente(env: Mapping[str, str] | None = None) -> Flask:
    try:
        cfg = carregar(os.environ if env is None else env)
    except ErroDeConfig as erro:
        print(f"[broker] NAO SUBIU: {erro}", file=sys.stderr)
        raise SystemExit(2) from None
    return criar_app_de_config(cfg)
