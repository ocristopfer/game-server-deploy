"""When an alert is worth sending: the rules behind each of the panel's alerts.

What is NOT here: the delivery (`integrations.webhook_client`), and the alert log and the
reading of the alert settings from the database (`notify`, `_record_alert`, `webhook_config`
and friends stay in `app.py` until the repository layer exists; see the order in section 4
of docs/architecture-proposal.md). Only the decision lives here: given this state, this
reading and what was seen last time, does an alert go out or not?

The thread running through almost every rule below is the same: **alert on the change,
not on the state**. A disk at 95% is still at 95% a minute later, and one alert per
minute until someone fixes it is how you teach a team to ignore the channel. That is why
almost all of them write to `previous` (that server's memory) besides alerting.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from gamepanel.i18n import Message
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.log_probe import compile_pattern
from gamepanel.runtime.ssh import RemoteError, ServerLike

# (conn, event, title, detail) -> did it reach anyone?
Notifica = Callable[..., bool]
# (conn, server_id) -> did the panel act on this server a moment ago?
RecentJob = Callable[..., bool]

# A source that answers an actual probe can go SILENT; counting from the log asks the
# game nothing, so there is nothing that can hang.
ANSWERING_SOURCES = ("a2s", "http")

DETALHE_MAX = 300


class AlertDeps(NamedTuple):
    """The rest of the panel, as the rules need to see it.

    A bundle rather than loose parameters because there are thirteen pieces and they
    travel together; per function, it is the difference between five arguments and one.
    All of them are injected for the usual reason: `app.py` imports this module, and
    several of these names are swapped for fakes in the tests (`server_players`,
    `server_metrics`, `notify`).
    """

    notify: Notifica
    recent_job: RecentJob
    player_source: Callable[[ServerLike], str]
    server_players: Callable[..., dict]
    server_metrics: Callable[..., dict]
    read_log_lines: Callable[..., list[str]]
    stored_value: Callable[[ServerLike, str], str]
    human_size: Callable[..., str]
    # The SAME dict as in `app.py`: the monitor, the log stream and the resource alerts
    # write to the state of the same server.
    monitor_state: dict[int, dict]
    logger: logging.Logger
    mute_rounds: int
    log_err_lines: int
    log_err_cooldown: float


def _target(server: ServerLike) -> str:
    return f"{server['ssh_user']}@{server['host']}"


# ------------------------------------------------------- contact and service

def state_alert(deps: AlertDeps, conn: Any, server: ServerLike, state: dict,
                     previous: dict) -> None:
    """Contact with the container and the state of the service.

    Does NOT receive the alert settings: whether an event goes out is decided by
    `notify`, which reads them on its own. A parameter nobody uses is noise in the
    signature and a lie to the reader ("oh, so this looks at the config").
    """
    sid, name = int(server["id"]), server["name"]
    target = _target(server)

    if state["reachable"] != previous["reachable"]:
        if state["reachable"]:
            deps.notify(conn, "acessivel", Message("alert.contact_back", name=name), target)
        else:
            deps.notify(conn, "inacessivel", Message("alert.lost_contact", name=name),
                          f"{target}\n{state.get('error') or Message('alert.no_detail')}")
        return  # without contact there is no honest way to talk about the service

    if not state["reachable"]:
        return
    if state["service"] == previous["service"]:
        return
    if state["service"] == "active":
        deps.notify(conn, "voltou", Message("alert.server_back", name=name), target)
        return
    if previous["service"] != "active":
        return

    # 'failed' is systemd saying the game broke (exited with an error, hit the restart
    # limit, was killed by the OOM killer). It skips the quiet window: if someone asked for
    # a restart and the result was 'failed', that is exactly what the person needs to know.
    if state["service"] == "failed":
        deps.notify(conn, "quebrou", Message("alert.game_failed", name=name),
                      f"{target}\n"
                      + Message("alert.service_is_failed", service=server["service"])
                      + (f" (Result={state['result']})" if state.get("result") else ""))
    elif not deps.recent_job(conn, sid):
        deps.notify(conn, "caiu", Message("alert.server_stopped", name=name),
                      f"{target}\n" + Message("alert.service_is",
                                              service=server["service"],
                                              state=state["service"]))


def restart_alert(deps: AlertDeps, conn: Any, server: ServerLike, state: dict,
                      previous: dict) -> None:
    """Crash loop: systemd bringing the game back to life over and over.

    This is the hole the down alert does not cover. With `Restart=always` the game can die
    every 20 seconds and `ActiveState` still answers 'active' almost all the time: the
    outage never 'happens' as far as the panel can see, and the channel stays silent while
    nobody can play. What gives it away is NRestarts, which only goes up.
    """
    sid, name = int(server["id"]), server["name"]
    now_ts = int(state.get("restarts") or 0)
    before = int(previous.get("restarts") or 0)

    # The counter resets when someone restarts the unit by hand (and on a daemon reload).
    # That is not a loop: just a new baseline.
    if now_ts < before:
        previous["restarts"] = now_ts
        previous["loop_avisado"] = False
        return
    if now_ts == before:
        # A whole round with no new restart: the loop is over, and the next one may
        # alert again.
        previous["loop_avisado"] = False
        return

    how_many = now_ts - before
    previous["restarts"] = now_ts
    # While the counter keeps climbing round after round, the alert goes out ONCE.
    # Repeating it every minute would be the very spam the on-change rule exists to avoid.
    if previous.get("loop_avisado") or deps.recent_job(conn, sid):
        return
    previous["loop_avisado"] = True
    deps.notify(
        conn, "reiniciando", Message("alert.restart_loop", name=name),
        f"{_target(server)}\n"
        + Message("alert.systemd_restarted", service=server["service"],
                   times=how_many)
        + Message("alert.restarts_total", n=now_ts),
    )


def mute_alert(deps: AlertDeps, conn: Any, server: ServerLike, state: dict,
                    previous: dict) -> None:
    """Service up, game mute: it no longer answers the game's own query.

    This is the most deceptive case. The process is still alive, systemd is still happy,
    the dashboard is still green, and nobody can get in.
    """
    sid, name = int(server["id"]), server["name"]
    if deps.player_source(server) not in ANSWERING_SOURCES:
        return

    # A game that has just started is still loading the map and does not answer: counting
    # those rounds would turn every cold start into an alert. The same goes for the quiet
    # window after an action through the panel.
    if state["service"] != "active" or deps.recent_job(conn, sid):
        previous["mudo"] = 0
        return

    data = deps.server_players(server)
    if not data.get("configured"):
        return

    if not data.get("error"):
        previous["mudo"] = 0
        if previous.get("mudo_avisado"):
            previous["mudo_avisado"] = False
            deps.notify(conn, "respondeu", Message("alert.game_answering", name=name),
                          Message("alert.players_online_rough",
                                   n=data.get("players")))
        return

    previous["mudo"] = int(previous.get("mudo") or 0) + 1
    if previous["mudo"] < deps.mute_rounds or previous.get("mudo_avisado"):
        return
    previous["mudo_avisado"] = True
    deps.notify(
        conn, "travou", Message("alert.game_mute", name=name),
        f"{_target(server)}\n"
        + Message("alert.service_up_game_mute", service=server["service"])
        + Message("alert.mute_rounds", n=previous["mudo"])
        + f"\n{data['error']}",
    )


# ----------------------------------------------------------- error in the log

def log_alert(deps: AlertDeps, conn: Any, server: ServerLike, previous: dict) -> None:
    """Looks for the server's error expression in the tail of the game log.

    It is the only alert that depends on configuration: every game screams in its own way,
    so the expression comes from the server's record. Without one, not even the SSH trip
    happens.
    """
    default = deps.stored_value(server, "error_re")
    if not default:
        return
    name = server["name"]
    try:
        regex = compile_pattern(default, "pattern.error")
    except QueryError as exc:
        deps.logger.warning("expressao de erro de '%s' invalida: %s", name, exc)
        return
    if regex is None:
        return  # whitespace-only pattern: nothing to look for
    try:
        lines_of = deps.read_log_lines(server, deps.log_err_lines)
    except (RemoteError, QueryError) as exc:
        # An unreadable log is not an error OF THE GAME. If the server is gone, the
        # 'inacessivel' alert reports it; inventing a log alert here would say the same
        # thing twice, under the wrong name.
        deps.logger.info("nao consegui ler o log de '%s' para procurar erro: %s", name, exc)
        return

    found = [line.strip() for line in lines_of if regex.search(line)]
    if not found:
        # The line left the tail of the log: if the error comes back, it is a new error and
        # alerts again.
        previous["ultimo_erro"] = ""
        return

    last_one = found[-1][:DETALHE_MAX]
    # Same line as last round: a game that repeats the error every second would produce
    # one alert per minute until someone turned off the webhook.
    if last_one == previous.get("ultimo_erro"):
        return
    # Safety catch for an expression that is too broad (a `.` matches everything): even
    # with lines that always differ, the channel gets no more than one of these per window.
    now_ts = time.monotonic()
    last_sent = float(previous.get("erro_em") or 0)
    if last_sent and now_ts - last_sent < deps.log_err_cooldown:
        previous["ultimo_erro"] = last_one
        return
    previous["ultimo_erro"] = last_one
    previous["erro_em"] = now_ts
    how_many = f" ({len(found)} linhas casaram)" if len(found) > 1 else ""
    deps.notify(conn, "erro-no-log", Message("alert.log_error", name=name),
                  f"{_target(server)}{how_many}\n{last_one}")


# -------------------------------------------------------------- resources

def disk_alert(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    data = deps.server_metrics(server)
    if data.get("error"):
        return
    worst = max((d for d in data.get("disks", []) if d.get("pct") is not None),
               key=lambda d: d["pct"], default=None)
    if not worst:
        return
    full = worst["pct"] >= cfg["disk"]
    mark = deps.monitor_state.setdefault(sid, {})
    # Alerts only on the CHANGE: a disk at 95% is still at 95% the next round, and nobody
    # deserves the same alert every minute until it is fixed.
    if full and not mark.get("disco_cheio"):
        deps.notify(conn, "disco-cheio",
                      Message("alert.disk_almost_full", name=server["name"]),
                      Message("alert.disk_detail", mount=worst["mount"],
                               pct=worst["pct"],
                               used=deps.human_size(worst["used"]),
                               total=deps.human_size(worst["total"])))
    mark["disco_cheio"] = full


def memory_alert(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    data = deps.server_metrics(server)
    if data.get("error"):
        return
    mem = data.get("mem")
    if not mem or mem.get("pct") is None:
        return
    full = mem["pct"] >= cfg["memory"]
    mark = deps.monitor_state.setdefault(sid, {})
    # Alerts only on the change
    if full and not mark.get("memoria_alta"):
        deps.notify(
            conn, "memoria-alta",
            Message("alert.memory_almost_full", name=server["name"]),
            Message("alert.memory_detail", pct=mem["pct"],
                     used=deps.human_size(mem["used"]),
                     total=deps.human_size(mem["total"])))
    mark["memoria_alta"] = full


def cpu_alert(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    data = deps.server_metrics(server)
    if data.get("error"):
        return
    cpu = data.get("cpu_pct")
    if cpu is None:
        return
    tall = cpu >= cfg["cpu"]
    mark = deps.monitor_state.setdefault(sid, {})
    # Alerts only on the change
    if tall and not mark.get("cpu_alta"):
        cores = data.get("cores", 1)
        proc = data.get("proc", {})
        proc_cpu = proc.get("cpu_pct")
        detail = str(Message("alert.cpu_detail_one" if cores == 1
                               else "alert.cpu_detail_many", pct=cpu, cores=cores))
        if proc_cpu is not None:
            detail += str(Message("alert.cpu_game_part", pct=proc_cpu))
        deps.notify(conn, "cpu-alta",
                      Message("alert.cpu_high", name=server["name"]), detail)
    mark["cpu_alta"] = tall


# ------------------------------------------------------------- players

def players_alert(deps: AlertDeps, conn: Any, server: ServerLike, service: str,
                        previous: dict, cfg: dict) -> None:
    """Alerts when players join or leave the server.

    Compares the current player list with the one from the previous check. If the game
    gives names (through the log with (?P<name>...), the HTTP API or A2S), it names who
    joined or left. If the game only returns the count, it reports the change in number.

    Takes the `service` (a string) instead of the whole state on purpose: the monitor's
    fast round does not query systemd, and passes in the last known state. Asking for the
    dict would force paying for an SSH trip just to fill in a field that is already known.
    """
    sid, name = int(server["id"]), server["name"]
    if not deps.player_source(server):
        return

    # If the service is not active or there was a recent job (restart, update), reset
    # the state so no false disconnect alerts fire.
    if service != "active" or deps.recent_job(conn, sid):
        previous["jogadores_nomes"] = None
        previous["jogadores_count"] = None
        return

    data = deps.server_players(server)
    if not data.get("configured") or data.get("error"):
        return

    current_names, current_count = players_reading(data)

    # First look at this server: just set the baseline
    if previous.get("jogadores_nomes") is None and previous.get("jogadores_count") is None:
        previous["jogadores_nomes"] = current_names
        previous["jogadores_count"] = current_count
        return

    previous_names = previous.get("jogadores_nomes") or set()
    previous_count = int(previous.get("jogadores_count") or 0)

    if current_names or previous_names:
        # The game gives names (exact or approximate): the alert says who it was.
        _warn_by_name(deps, conn, name, cfg, current_names, previous_names, current_count)
    else:
        # Only the count: the alert reports the change.
        _warn_by_count(deps, conn, name, cfg, current_count, previous_count)

    previous["jogadores_nomes"] = current_names
    previous["jogadores_count"] = current_count


def players_reading(data: dict) -> tuple[set, int]:
    """Normalizes the query answer into (names, count).

    A game that only returns a number comes with an empty list; a game that only returns
    names comes without a count. Both cases leave here in the same shape, and that is what
    lets the rest of the function avoid repeating `or 0` and `or []` on every line.
    """
    listing = data.get("list") or []
    names = {p["name"].strip() for p in listing if p.get("name") and p["name"].strip()}
    count = data.get("players")
    if count is None and names:
        count = len(names)
    return names, max(0, int(count or 0))


def online_text(count: int) -> str:
    """"3 players online", "1 player online", "no players online".

    It used to exist in four places on this screen, with a subtle difference between them:
    one of the four did not handle zero and could say "0 players online". One place only.
    """
    if count == 0:
        return Message("alert.nobody_online")
    return Message("alert.players_online_one" if count == 1
                    else "alert.players_online_many", n=count)


def _warn_by_name(deps: AlertDeps, conn: Any, name: str, cfg: dict, current_names: set,
                    previous_names: set, count: int) -> None:
    """One alert per person who joined or left."""
    detail = online_text(count)
    if "jogador-entrou" in cfg["events"]:
        for player in sorted(current_names - previous_names):
            deps.notify(conn, "jogador-entrou",
                          Message("alert.player_joined", name=name,
                                   player=player), detail)
    if "jogador-saiu" in cfg["events"]:
        for player in sorted(previous_names - current_names):
            deps.notify(conn, "jogador-saiu",
                          Message("alert.player_left", name=name,
                                   player=player), detail)


def _warn_by_count(deps: AlertDeps, conn: Any, name: str, cfg: dict, current: int,
                        previous: int) -> None:
    """One alert per change, for a game that does not publish names."""
    if current == previous:
        return
    detail = online_text(current)
    if current > previous and "jogador-entrou" in cfg["events"]:
        diff = current - previous
        deps.notify(conn, "jogador-entrou",
                      Message("alert.joined_one" if diff == 1 else "alert.joined_many",
                               name=name, n=diff), detail)
    elif current < previous and "jogador-saiu" in cfg["events"]:
        diff = previous - current
        deps.notify(conn, "jogador-saiu",
                      Message("alert.left_one" if diff == 1 else "alert.left_many",
                               name=name, n=diff), detail)
