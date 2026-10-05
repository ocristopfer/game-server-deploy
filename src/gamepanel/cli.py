"""Panel command line: start the server, create a user, unlock 2FA and
register a server from the deploy.

It lives outside `app.py` but is still reachable by the usual path: the bottom of
`app.py` calls `main()` from here. That matters because the emergency exit for the second
factor is written in the README and in CLAUDE.md as

    python3 /opt/gamepanel/app.py --reset-2fa USER

and whoever needs it is, by definition, locked out of the panel: not the time to
find out the command was renamed. `python3 -m gamepanel.cli` does the same.

The registration functions (`ensure_admin_user`, `ensure_server`) did NOT come along: they
are also called from inside the panel and from `docker/panel/entrypoint.sh`, so they
stay in `app.py` and arrive here as parameters.
"""
from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from gamepanel import config
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.persistence.repositories import users as users_repo

# The command line does not take line breaks comfortably: the lists (config
# files, backup paths) come comma-separated and become one per line.
LIST_SEPARATOR = ","


class CliDeps(NamedTuple):
    """The panel, as the command line needs it."""

    init_db: Callable[[], None]
    connect: Callable[[], sqlite3.Connection]
    ensure_admin_user: Callable[..., None]
    ensure_server: Callable[[Any], Any]
    deploy_server: Callable[..., Any]
    start_scheduler: Callable[[], None]
    resume_broker_jobs: Callable[[], Any]
    app: Any
    roles: Sequence[str]


def by_comma(raw: str) -> str:
    return "\n".join(p.strip() for p in raw.split(LIST_SEPARATOR) if p.strip())


def build_parser(roles: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Painel de servidores de jogos")
    parser.add_argument("--create-user", metavar="USUARIO")
    # Emergency exit: the only admin lost the phone AND the recovery codes.
    parser.add_argument("--reset-2fa", metavar="USUARIO",
                        help="desliga o segundo fator de um usuario (roda no CT do painel)")
    parser.add_argument("--password", metavar="SENHA")
    parser.add_argument("--role", default="", choices=("", *roles),
                        help="papel do usuario (padrao: admin ao criar; manter ao redefinir)")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104  # NOSONAR - the panel serves the LAN
    parser.add_argument("--port", type=int, default=config.load().port)
    # Used by the deploy (deploy-docker.ps1) to leave the server already registered.
    # Used by deploy/game/migrate-ct.sh after a container got the `gamepanel` user: switches
    # ONLY the login user of the server at --server-host/--ssh-port, nothing else.
    parser.add_argument("--set-ssh-user", metavar="USUARIO")
    parser.add_argument("--register-server", metavar="NOME")
    parser.add_argument("--server-host", default="")
    parser.add_argument("--service", default="")
    parser.add_argument("--ssh-port", type=int, default=22)
    # No default here on purpose: unset means "new server = gamepanel, existing server keeps
    # its user" (see `DeployServer.ssh_user`). A default would overwrite a legacy server's
    # root on every redeploy.
    parser.add_argument("--ssh-user", default="")
    parser.add_argument("--game-port", default="")
    parser.add_argument("--query-port", type=int, default=0)
    parser.add_argument("--config-path", default="")
    parser.add_argument("--config-files", default="")
    parser.add_argument("--backup-paths", default="")
    parser.add_argument("--join-re", default="")
    parser.add_argument("--leave-re", default="")
    parser.add_argument("--log-path", default="")
    parser.add_argument("--player-source", default="")
    parser.add_argument("--max-players", type=int, default=0)
    parser.add_argument("--notes", default="")
    return parser


def reset_2fa(deps: CliDeps, user: str) -> None:
    """Turn off a user's second factor. Raises SystemExit if the user does not exist."""
    deps.init_db()
    conn = deps.connect()
    with conn:
        target = users_repo.id_by_username(conn, user)
        if not target:
            raise SystemExit(f"usuario '{user}' nao existe")
        users_repo.disable_two_factor(conn, target["id"])
    print(f"Segundo fator de '{user}' desligado.")


def set_ssh_user(deps: CliDeps, opts: argparse.Namespace) -> None:
    """Switch the SSH login user of one registered server, found by its address."""
    if not opts.server_host:
        raise SystemExit("--set-ssh-user exige --server-host")
    deps.init_db()
    conn = deps.connect()
    with conn:
        row = servers_repo.by_address(conn, opts.server_host, opts.ssh_port)
        if row is None:
            raise SystemExit(f"nenhum servidor cadastrado em {opts.server_host}:{opts.ssh_port}")
        servers_repo.set_ssh_user(conn, row["id"], opts.set_ssh_user)
    print(f"servidor '{row['name']}' ({opts.server_host}) agora entra como {opts.set_ssh_user}")


def register_server(deps: CliDeps, opts: argparse.Namespace) -> None:
    if not opts.server_host or not opts.service:
        raise SystemExit("--register-server exige --server-host e --service")
    created_at = deps.ensure_server(deps.deploy_server(
        name=opts.register_server,
        host=opts.server_host,
        service=opts.service,
        ssh_port=opts.ssh_port,
        ssh_user=opts.ssh_user,
        game_port=opts.game_port,
        notes=opts.notes,
        config_path=opts.config_path,
        config_files=by_comma(opts.config_files),
        backup_paths=by_comma(opts.backup_paths),
        join_re=opts.join_re,
        leave_re=opts.leave_re,
        log_path=opts.log_path,
        query_port=opts.query_port,
        player_source=opts.player_source,
        max_players=opts.max_players,
    ))
    print(f"servidor '{opts.register_server}' {'cadastrado' if created_at else 'atualizado'}"
          f" ({opts.server_host})")


def main(deps: CliDeps, argv: Sequence[str] | None = None) -> None:
    opts = build_parser(deps.roles).parse_args(argv)

    if opts.reset_2fa:
        reset_2fa(deps, opts.reset_2fa)
    elif opts.create_user:
        if not opts.password:
            raise SystemExit("--create-user exige --password")
        deps.ensure_admin_user(opts.create_user, opts.password, opts.role)
    elif opts.set_ssh_user:
        set_ssh_user(deps, opts)
    elif opts.register_server:
        register_server(deps, opts)
    else:
        # Only the real server starts the clock: from the command line (registering a
        # user, registering a server) it must not start touching the containers.
        deps.start_scheduler()
        deps.resume_broker_jobs()
        deps.app.run(host=opts.host, port=opts.port)


def panel_deps() -> CliDeps:
    """Build the dependencies from the panel.

    The import lives in here, not at the top: `app.py` imports THIS module, and the
    reverse at file level would close the loop. When run via `-m gamepanel.cli`,
    this module is already complete when the line below executes.
    """
    from gamepanel import app as painel

    return CliDeps(
        init_db=painel.init_db, connect=painel._connect,
        ensure_admin_user=painel.ensure_admin_user, ensure_server=painel.ensure_server,
        deploy_server=painel.DeployServer,
        start_scheduler=painel.start_scheduler,
        resume_broker_jobs=painel.resume_broker_jobs,
        app=painel.app, roles=painel.ROLES,
    )


if __name__ == "__main__":
    main(panel_deps())
