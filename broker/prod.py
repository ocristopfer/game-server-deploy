"""Broker de producao: monta o `Servico` com Proxmox, OPNsense e SSH DE VERDADE.

O systemd sobe assim (ver provision-broker-lxc.sh):

    gunicorn --workers 1 --threads 8 --certfile ... --keyfile ... 'broker.prod:criar_app_de_ambiente()'

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

from .api import criar_app
from .backends import Rede
from .banco import Banco
from .catalogo import Catalogo
from .config import ConfigBroker, ErroDeConfig, carregar
from .conexao import Cliente
from .opnsense import Opnsense
from .proxmox import Proxmox
from .rede import RedeReal
from .servico import Config, Servico
from .ssh_install import Executor, InstaladorSsh


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
        Banco(str(cfg.estado / "broker.db")), Catalogo(cfg.pasta_games, cfg.estado / "dinamico"),
        proxmox, opnsense, InstaladorSsh(cfg.ssh, executor), rede or RedeReal(),
        Config(ctids=cfg.ctids, ips=cfg.ips, max_instancias=cfg.max_instancias,
               max_criacoes_por_hora=cfg.max_criacoes_por_hora), **argumentos)


def criar_app_de_config(cfg: ConfigBroker, **kwargs) -> Flask:
    return criar_app(montar_servico(cfg, **kwargs), cfg.token, cfg.ips_permitidos)


def criar_app_de_ambiente(env: Mapping[str, str] | None = None) -> Flask:
    try:
        cfg = carregar(os.environ if env is None else env)
    except ErroDeConfig as erro:
        print(f"[broker] NAO SUBIU: {erro}", file=sys.stderr)
        raise SystemExit(2) from None
    return criar_app_de_config(cfg)
