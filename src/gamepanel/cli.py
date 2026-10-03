"""Linha de comando do painel: subir o servidor, criar usuario, destravar o 2FA e
cadastrar servidor pelo deploy.

Mora fora de `app.py` mas continua acessivel pelo caminho de sempre: o rodape de
`app.py` chama o `main()` daqui. Isso importa porque a saida de emergencia do segundo
fator esta escrita no README e no CLAUDE.md como

    python3 /opt/gamepanel/app.py --reset-2fa USUARIO

e quem precisa dela esta, por definicao, trancado do lado de fora do painel — nao e
hora de descobrir que o comando mudou de nome. `python3 -m gamepanel.cli` faz o mesmo.

As funcoes de cadastro (`ensure_admin_user`, `ensure_server`) NAO vieram junto: elas
tambem sao chamadas de dentro do painel e do `docker/panel/entrypoint.sh`, entao
continuam em `app.py` e chegam aqui por parametro.
"""
from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from gamepanel import config
from gamepanel.persistence.repositories import users as users_repo

# A linha de comando nao aceita quebra de linha com conforto: as listas (arquivos de
# config, caminhos de backup) vem separadas por virgula e viram uma por linha.
LIST_SEPARATOR = ","


class CliDeps(NamedTuple):
    """O painel, como a linha de comando precisa dele."""

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
    # Saida de emergencia: o unico admin perdeu o celular E os codigos de recuperacao.
    parser.add_argument("--reset-2fa", metavar="USUARIO",
                        help="desliga o segundo fator de um usuario (roda no CT do painel)")
    parser.add_argument("--password", metavar="SENHA")
    parser.add_argument("--role", default="", choices=("", *roles),
                        help="papel do usuario (padrao: admin ao criar; manter ao redefinir)")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104  # NOSONAR - o painel serve a LAN
    parser.add_argument("--port", type=int, default=config.load().port)
    # Usado pelo deploy (deploy-docker.ps1) para deixar o servidor ja cadastrado.
    parser.add_argument("--register-server", metavar="NOME")
    parser.add_argument("--server-host", default="")
    parser.add_argument("--service", default="")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--ssh-user", default="root")
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
    """Desliga o segundo fator de um usuario. Levanta SystemExit se ele nao existe."""
    deps.init_db()
    conn = deps.connect()
    with conn:
        target = users_repo.id_by_username(conn, user)
        if not target:
            raise SystemExit(f"usuario '{user}' nao existe")
        users_repo.disable_two_factor(conn, target["id"])
    print(f"Segundo fator de '{user}' desligado.")


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
    elif opts.register_server:
        register_server(deps, opts)
    else:
        # So o servidor de verdade sobe o relogio: pela linha de comando (cadastrar
        # usuario, cadastrar servidor) ele nao pode comecar a mexer nos containers.
        deps.start_scheduler()
        deps.resume_broker_jobs()
        deps.app.run(host=opts.host, port=opts.port)


def panel_deps() -> CliDeps:
    """Monta as dependencias a partir do painel.

    O import mora aqui dentro, e nao no topo: `app.py` importa ESTE modulo, e o
    contrario no nivel do arquivo fecharia o circulo. Rodando por `-m gamepanel.cli`,
    este modulo ja esta inteiro quando a linha abaixo executa.
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
