"""Acompanhar uma operacao do broker ate o fim, e cadastrar o que ela criou.

Criar instancia nao e um comando remoto que responde em segundos: o broker cria o CT,
abre porta no OPNsense e instala o jogo, e isso leva minutos de download. Por isso aqui
nao ha `start_job` comum (que so grava a saida no fim) e sim polling, gravando o log no
job a cada volta — e o que faz a tela mostrar o progresso ao vivo.

A regra que nao pode se perder: se a operacao deu certo mas o cadastro no painel falhar,
o texto do job precisa dizer que **a instancia existe** no Proxmox. Sem isso parece que
nada foi feito, e a proxima tentativa cria uma segunda.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from gamepanel.i18n import Message
from gamepanel.integrations import broker_client
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.services.server_service import HOST_RE, UNIT_RE

LOG_MAX = 200000


class BrokerJobDeps(NamedTuple):
    """O que o acompanhamento precisa do painel.

    Os tres limites entram como valor porque sao lidos uma vez por operacao; os testes
    trocam `BROKER_POLL`/`BROKER_FAILURES_MAX` em `app.py` ANTES de chamar, e o bundle e
    montado na chamada.
    """

    update_job: Callable[..., None]
    close_job: Callable[..., None]
    # Devolve se criou (o acompanhamento nao usa: o que importa e a linha no banco).
    ensure_server: Callable[[Any], Any]
    deploy_server: Callable[..., Any]
    connect: Callable[[], sqlite3.Connection]
    poll: float
    max_failures: int
    timeout: float


def register_server(deps: BrokerJobDeps, r: dict) -> int:
    """Registra no painel a instancia que o broker acabou de criar. Devolve o id do servidor.

    Passa pelo mesmo `ensure_server` do deploy, entao a tela de configuracao ja abre pronta.
    """
    host = str(r["host"])
    service = str(r["service"])
    if not HOST_RE.match(host) or not UNIT_RE.match(service):
        raise ValueError(Message("broker.bad_host_or_service"))
    deps.ensure_server(deps.deploy_server(
        name=str(r["name"])[:80], host=host, service=service,
        game_port=" ".join(str(p) for p in r.get("ports") or []),
        notes=str(r.get("notes", "")),
        config_path=str(r.get("config_path", "")),
        config_files="\n".join(r.get("config_files") or []),
        backup_paths="\n".join(r.get("backup_paths") or []),
        join_re=str(r.get("join_re", "")), leave_re=str(r.get("leave_re", "")),
        log_path=str(r.get("log_path", "")), query_port=int(r.get("query_port") or 0),
        player_source=str(r.get("player_source", "")), broker_id=int(r.get("broker_id") or 0),
    ))
    conn = deps.connect()
    try:
        line = servers_repo.id_by_host(conn, host)
    finally:
        conn.close()
    if line is None:
        raise ValueError(Message("broker.server_not_saved"))
    return int(line["id"])


def finish_operation(deps: BrokerJobDeps, job_id: int, op: dict) -> None:
    log = str(op.get("log", ""))
    if op.get("state") != "ok":
        deps.close_job(job_id, "error", log, exit_code=1)
        return
    try:
        sid = register_server(deps, op.get("result") or {})
    except (KeyError, TypeError, ValueError, sqlite3.Error) as failure:
        # A instancia EXISTE no Proxmox: o texto precisa dizer isso, senao parece que
        # nada foi feito.
        deps.close_job(job_id, "error", f"{log}\nA instancia foi criada, mas nao consegui "
                       f"cadastra-la no painel: {failure}", exit_code=1)
        return
    deps.close_job(job_id, "ok", f"{log}\nServidor cadastrado no painel (id {sid}).",
                   exit_code=0, server_id=sid)


def follow_operation(deps: BrokerJobDeps, job_id: int, op_id: str,
                       sleep: Callable[[float], Any] = time.sleep) -> None:
    """Le a operacao do broker ate ela terminar, gravando o log no job a cada volta."""
    limit = time.monotonic() + deps.timeout
    failures = 0
    log = ""
    while time.monotonic() < limit:
        try:
            op = broker_client.operation(op_id)
        except broker_client.BrokerError as failure:
            failures += 1
            if failures >= deps.max_failures:
                deps.close_job(job_id, "error", f"{log}\nPerdi o contato com o broker: {failure}")
                return
            sleep(deps.poll)
            continue
        failures = 0
        log = str(op.get("log", ""))[-LOG_MAX:]
        deps.update_job(job_id, output=log)
        if op.get("state") != "executando":
            finish_operation(deps, job_id, op)
            return
        sleep(deps.poll)
    deps.close_job(job_id, "error", f"{log}\nTempo esgotado esperando o broker.")
