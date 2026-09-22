"""Conta jogadores lendo o log do jogo por SSH, para quem nao publica A2S nem API HTTP
(o RuneScape Dragonwilds, por exemplo). O painel reproduz os eventos de entrada/saida
desde o ultimo start do servico e ve quem sobrou.
"""
from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from typing import Any

from gamepanel.i18n import Mensagem
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.ssh import ServerLike

LOG_SCAN_MAX = 20000
RE_MAX_LEN = 300
# Palavras que costumam aparecer na linha de entrada/saida — usadas so pelo assistente
# que ajuda a descobrir o padrao do jogo.
LOG_HINT_WORDS = (
    "join", "joined", "left", "leave", "connect", "disconnect", "login", "logout",
    "player", "jogador", "entrou", "saiu",
)
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")
# Linha gigante (stack trace) nao pode custar caro no regex.
LOG_LINE_MAX = 500

# Caminho do arquivo de log. O '*' e permitido (o DayZ abre um .ADM por sessao), mas
# nada que o shell do container interprete como outra coisa: sem espaco, aspas, $, ; ou &.
LOG_PATH_RE = re.compile(r"^/[A-Za-z0-9._*?/-]{1,200}$")

# Le do start do servico para ca: eventos de execucoes anteriores contariam jogador
# que ja foi embora ha muito tempo.
# $3 = caminho do arquivo de log (pode ter *). Vazio cai no journalctl do servico.
# Acompanha o log e vai cuspindo linha nova enquanto o SSH estiver de pe. `-n 0`/`tail -n
# 0` de proposito: o passado nao interessa aqui: quem sabe dizer quem esta online agora e
# a contagem normal, e este script so avisa que ACONTECEU alguma coisa. Assim o painel nao
# precisa reproduzir a maquina de estados do log em dois lugares diferentes.
LOG_FOLLOW_SCRIPT = r"""
set -u
unit=$1
alvo=${2:-}

if [ -n "$alvo" ]; then
  # Sem aspas para o shell expandir o '*' — o LOG_PATH_RE do painel e quem garante que
  # nao ha espaco, aspas, $ ou ';' aqui dentro.
  arq=$(ls -1t $alvo 2>/dev/null | head -n 1)
  [ -n "$arq" ] || { echo "nenhum arquivo de log casa com $alvo" >&2; exit 3; }
  # -F (e nao -f) para sobreviver a rotacao do arquivo.
  exec tail -n 0 -F -- "$arq"
fi

exec journalctl -u "$unit" -n 0 -f -o short-iso --no-pager
"""

LOG_PLAYERS_SCRIPT = r"""
set -u
unit=$1
max=$2
alvo=${3:-}

if [ -n "$alvo" ]; then
  # $alvo vai SEM aspas de proposito, para o shell do container expandir o '*'. Quem
  # garante que isso e seguro e o LOG_PATH_RE do painel, que so deixa passar caminho
  # absoluto com letras, numeros, . _ - / * ? — nada de espaco, aspas, $ ou ;.
  arq=$(ls -1t $alvo 2>/dev/null | head -n 1)
  [ -n "$arq" ] || { echo "nenhum arquivo de log casa com $alvo" >&2; exit 3; }
  [ -r "$arq" ] || { echo "sem permissao de leitura em $arq" >&2; exit 4; }
  tail -n "$max" -- "$arq"
  exit 0
fi

inicio=$(systemctl show -p ActiveEnterTimestamp --value "$unit" 2>/dev/null || true)
if [ -n "$inicio" ]; then
  journalctl -u "$unit" --since "$inicio" --no-pager -o short-iso 2>/dev/null | tail -n "$max"
else
  journalctl -u "$unit" --no-pager -o short-iso -n "$max" 2>/dev/null
fi
"""


def compile_pattern(raw: str | None, label: str) -> re.Pattern[str] | None:
    """Compila um padrao vindo da tela; devolve None quando esta vazio."""
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) > RE_MAX_LEN:
        raise QueryError(Mensagem("pattern.too_long", rotulo=Mensagem(label),
                                      n=RE_MAX_LEN))
    try:
        return re.compile(text)
    except re.error as exc:
        raise QueryError(Mensagem("pattern.invalid", rotulo=Mensagem(label),
                                      motivo=exc)) from exc


def _log_timestamp(line: str) -> str:
    m = TS_RE.match(line)
    return f"{m.group(1)} {m.group(2)}" if m else ""


def _events_by_name(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """Os dois padroes capturam (?P<name>...): da para dizer QUEM esta online."""
    online: dict[str, str] = {}
    for line in lines:
        short = line[:LOG_LINE_MAX]
        entered = enter.search(short)
        if entered:
            name = (entered.groupdict().get("name") or "").strip()
            if name:
                online[name] = _log_timestamp(line)
            continue
        left = leave.search(short) if leave else None
        if left:
            online.pop((left.groupdict().get("name") or "").strip(), None)
    return {
        "players": len(online),
        "list": [{"name": n, "since": t, "score": 0, "seconds": 0} for n, t in online.items()],
    }


def _events_by_count(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """Sem nome na saida (varios servidores Unreal so avisam que alguem saiu):
    sobra somar as entradas e subtrair as saidas."""
    total = 0
    for line in lines:
        short = line[:LOG_LINE_MAX]
        if enter.search(short):
            total += 1
        elif leave and leave.search(short):
            total = max(0, total - 1)
    return {"players": total, "list": []}


def _events_half_named(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """Entrada com nome, saida sem — o caso do Satisfactory.

    O log diz que alguem saiu, mas nao diz quem. A CONTAGEM continua sendo a mesma de
    antes (entradas menos saidas, exata); a lista passa a mostrar os ultimos a entrar,
    tantos quantos a conta disser. E um palpite, e a tela avisa que e — mas jogar os
    nomes fora, que era o que o painel fazia, nao ajudava ninguem.
    """
    total = 0
    order: list[tuple[str, str]] = []
    for line in lines:
        short = line[:LOG_LINE_MAX]
        entered = enter.search(short)
        if entered:
            total += 1
            name = (entered.groupdict().get("name") or "").strip()
            if name:
                # Reconexao volta para o fim da fila em vez de duplicar.
                order = [p for p in order if p[0] != name]
                order.append((name, _log_timestamp(line)))
            continue
        if leave and leave.search(short):
            total = max(0, total - 1)
            if order:
                order.pop(0)  # sai quem esta ha mais tempo: o chute menos ruim
    approximate_list = order[-total:] if total else []
    return {
        "players": total,
        "list": [{"name": n, "since": t, "score": 0, "seconds": 0} for n, t in approximate_list],
        "aproximado": True,
    }


def apply_log_events(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """Reproduz os eventos do log em ordem e devolve quem ficou.

    Tres casos, do melhor para o pior: nome nos dois lados (sabe-se quem esta online),
    nome so na entrada (sabe-se quantos, e quem provavelmente), nome em lugar nenhum
    (so a contagem).
    """
    if not enter.groupindex.get("name"):
        return _events_by_count(lines, enter, leave)
    if not leave or leave.groupindex.get("name"):
        return _events_by_name(lines, enter, leave)
    return _events_half_named(lines, enter, leave)


def log_path_valido(raw: str | None) -> str:
    """Confere o caminho do log antes de ele entrar num comando remoto."""
    path = (raw or "").strip()
    if not path:
        return ""
    if not LOG_PATH_RE.match(path) or ".." in path:
        raise ValueError(
            "caminho de log invalido - use um caminho absoluto, sem espacos"
            " (o '*' e permitido, ex.: /opt/game/profiles/*.ADM)"
        )
    return path


SshOutput = Callable[[ServerLike, str, int], str]


def read_log_lines(
    ssh_output: SshOutput, server: ServerLike, service: str, log_path: str, limit: int = LOG_SCAN_MAX,
) -> list[str]:
    """Linhas do log: de um arquivo, quando o servidor tem um; senao do journalctl.

    O limite e parametro porque os dois usos pedem tamanhos bem diferentes: a contagem de
    jogadores precisa do historico inteiro da subida (quem entrou e nao saiu), e a
    varredura de erro so quer o rabo do log, de minuto em minuto.
    """
    try:
        target = log_path_valido(log_path)
    except ValueError as exc:
        raise QueryError(str(exc)) from exc
    remote_cmd = " ".join(shlex.quote(p) for p in (
        "bash", "-lc", LOG_PLAYERS_SCRIPT, "gp", service, str(limit), target,
    ))
    raw = ssh_output(server, remote_cmd, 60)
    return raw.splitlines()
