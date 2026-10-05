"""Follow a broker operation to the end, and register what it created.

Creating an instance is not a remote command that answers in seconds: the broker creates
the CT, opens a port on OPNsense and installs the game, which takes minutes of download.
That is why there is no plain `start_job` here (it only writes the output at the end) but
polling instead, writing the log to the job on every round - that is what lets the screen
show progress live.

The rule that must not get lost: if the operation succeeded but registering it in the
panel fails, the job text has to say that **the instance exists** in Proxmox. Without it
it looks like nothing was done, and the next attempt creates a second one.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from gamepanel.i18n import Message
from gamepanel.integrations import broker_client
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.runtime import remote_cmd
from gamepanel.services.server_service import HOST_RE, UNIT_RE

LOG_MAX = 200000


class BrokerJobDeps(NamedTuple):
    """What the follow-up needs from the panel.

    The three limits come in as values because they are read once per operation; the tests
    swap `BROKER_POLL`/`BROKER_FAILURES_MAX` in `app.py` BEFORE calling, and the bundle is
    built at call time.
    """

    update_job: Callable[..., None]
    close_job: Callable[..., None]
    # Returns whether it created (the follow-up ignores it: what matters is the DB row).
    ensure_server: Callable[[Any], Any]
    deploy_server: Callable[..., Any]
    connect: Callable[[], sqlite3.Connection]
    forget_host_key: Callable[[str], None]
    poll: float
    max_failures: int
    timeout: float


def register_server(deps: BrokerJobDeps, r: dict) -> int:
    """Register in the panel the instance the broker just created. Returns the server id.

    Goes through the same `ensure_server` as the deploy, so the config screen opens ready.
    """
    host = str(r["host"])
    service = str(r["service"])
    if not HOST_RE.match(host) or not UNIT_RE.match(service):
        raise ValueError(Message("broker.bad_host_or_service"))
    # The broker reuses the IP of a removed instance (the IP encodes the CTID). The SSH key
    # the panel learned there belongs to a CT that no longer exists, and with it in
    # known_hosts the new one would be born with "REMOTE HOST IDENTIFICATION HAS CHANGED" on
    # every call. This is the only point where we KNOW the machine is a different one -
    # anywhere else, a changed key is still an alarm.
    deps.forget_host_key(host)
    deps.ensure_server(deps.deploy_server(
        # The broker installs the `gamepanel` user and locks root at the end of every install:
        # the server it creates is born in helper mode.
        name=str(r["name"])[:80], host=host, service=service, ssh_user=remote_cmd.HELPER_USER,
        game_port=" ".join(str(p) for p in r.get("ports") or []),
        notes=str(r.get("notes", "")),
        config_path=str(r.get("config_path", "")),
        config_files="\n".join(r.get("config_files") or []),
        backup_paths="\n".join(r.get("backup_paths") or []),
        join_re=str(r.get("join_re", "")), leave_re=str(r.get("leave_re", "")),
        log_path=str(r.get("log_path", "")), query_port=int(r.get("query_port") or 0),
        max_players=int(r.get("max_players") or 0),
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
        # The instance EXISTS in Proxmox: the text has to say so, otherwise it looks like
        # nothing was done.
        deps.close_job(job_id, "error", f"{log}\nA instancia foi criada, mas nao consegui "
                       f"cadastra-la no painel: {failure}", exit_code=1)
        return
    deps.close_job(job_id, "ok", f"{log}\nServidor cadastrado no painel (id {sid}).",
                   exit_code=0, server_id=sid)


def follow_operation(deps: BrokerJobDeps, job_id: int, op_id: str,
                       sleep: Callable[[float], Any] = time.sleep) -> None:
    """Read the broker operation until it finishes, writing the log to the job each round."""
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
