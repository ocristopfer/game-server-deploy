"""Ouvir o log do jogo ao vivo, para a contagem por log nao ficar lenta.

Contagem por log era o unico caso sem jeito de ficar rapida: cada conferida e uma ida de
SSH que arrasta o log inteiro, entao perguntar de 15 em 15 segundos custaria megabytes
por minuto para achar duas linhas. A saida e parar de perguntar: uma conexao SSH longa
com `journalctl -f` deixa o painel OUVINDO, e a linha chega no segundo em que sai.

O ponto do desenho: o stream e um GATILHO, nao uma segunda contagem. Ele so diz "algo
aconteceu" e manda refazer a conta pelo caminho de sempre. Reproduzir aqui a maquina de
estados do log seria um segundo lugar para errar — e pior, um que divergiria em silencio
do numero que a tela mostra.
"""
from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any, NamedTuple

from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.log_probe import (
    LOG_FOLLOW_SCRIPT,
    LOG_LINE_MAX,
    compile_pattern,
    valid_log_path,
)
from gamepanel.runtime.ssh import ServerLike, quote_command

EVENTOS_DE_JOGADOR = frozenset({"jogador-entrou", "jogador-saiu"})
ESPERA_AO_ENCERRAR = 5


class LogStreamDeps(NamedTuple):
    """O que uma conexao de log precisa do resto do painel.

    A thread vive FORA do contexto do request, entao nada aqui pode vir do `g` do
    Flask: a conexao de banco e aberta por `connect` e fechada na mesma volta.
    """

    ssh_argv: Callable[..., list[str]]
    # O MESMO dicionario do monitor: os dois anotam no estado do mesmo servidor.
    monitor_state: dict[int, dict]
    invalidate_players: Callable[[int], None]
    connect: Callable[[], sqlite3.Connection]
    webhook_config: Callable[[Any], dict]
    players_lock: Callable[[int], threading.Lock]
    players_alert: Callable[..., None]
    logger: logging.Logger
    debounce: float
    retry: float


def player_line(line: str, enter: re.Pattern[str] | None,
                     leave: re.Pattern[str] | None) -> bool:
    """Esta linha do log e uma entrada ou saida de jogador?"""
    curta = line[:LOG_LINE_MAX]
    if enter and enter.search(curta):
        return True
    return bool(leave and leave.search(curta))


def stream_signature(server: ServerLike,
                         stored_value: Callable[[ServerLike, str], str]) -> tuple:
    """O que, mudando, obriga a refazer a conexao (regex nova, log em outro lugar...)."""
    return (
        server["host"], int(server["ssh_port"] or 22), server["ssh_user"],
        server["service"], stored_value(server, "log_path"),
        stored_value(server, "join_re"), stored_value(server, "leave_re"),
    )


def wanted_streams(servers: Iterable[ServerLike], cfg: dict, enabled: bool,
                      player_source: Callable[[ServerLike], str],
                      stored_value: Callable[[ServerLike, str], str]) -> dict[int, tuple]:
    """Quais servidores merecem uma conexao de log aberta, e com que assinatura."""
    if not (enabled and cfg["events"] & EVENTOS_DE_JOGADOR):
        return {}
    # So quem conta por log: A2S e HTTP ja respondem de graca na volta curta, e abrir uma
    # conexao permanente para eles seria pagar por nada.
    return {int(s["id"]): stream_signature(s, stored_value) for s in servers
            if player_source(s) == "log" and stored_value(s, "join_re")}


class LogStream:
    """Uma conexao SSH longa ouvindo o log de UM servidor."""

    def __init__(self, deps: LogStreamDeps, server: ServerLike, signature: tuple) -> None:
        self.deps = deps
        # Row nao atravessa thread (ela pertence a conexao do request): copia.
        self.data = dict(server)
        self.sid = int(server["id"])
        self.signature = signature
        self.proc: subprocess.Popen | None = None
        self._stop_signal = threading.Event()
        self.last_fire = 0.0
        self.error = ""
        # Erro de configuracao (regex que nao compila, caminho de log invalido) nao se
        # resolve tentando de novo. Sem esta marca o supervisor recriaria a thread a cada
        # volta, para ela morrer igual — um laco que so enche o log de erro.
        self.gave_up = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop_signal.set()
        proc = self.proc
        if proc and proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.terminate()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def _run(self) -> None:
        while not self._stop_signal.is_set():
            try:
                self._follow()
            # A thread nao morre por um tropeco.
            except Exception as exc:
                self.error = str(exc)
                self.deps.logger.exception("o acompanhamento de log de '%s' caiu",
                                           self.data.get("name"))
            # Servidor desligado nao pode virar um laco de SSH por segundo.
            if self._stop_signal.wait(self.deps.retry):
                return

    def _give_up(self, motivo: str) -> None:
        self.error = motivo
        self.gave_up = True
        self._stop_signal.set()

    def _follow(self) -> None:
        # Cadastro torto para aqui: nao adianta reconectar contra um regex que nao compila.
        try:
            enter = compile_pattern(self.data.get("join_re"), "pattern.join")
            leave = compile_pattern(self.data.get("leave_re"), "pattern.leave")
            alvo = valid_log_path(self.data.get("log_path") or "")
        except (QueryError, ValueError) as exc:
            return self._give_up(str(exc))
        if not enter:
            return self._give_up("sem padrao de entrada, nao ha o que ouvir")
        # Sem multiplexar: esta conexao fica de pe por horas, e a mestre compartilhada
        # existe justamente para as chamadas curtas do monitor.
        argv = [
            *self.deps.ssh_argv(
                self.data, connect_timeout=10,
                extra=("-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3"),
            ),
            quote_command("bash", "-lc", LOG_FOLLOW_SCRIPT, "gp", self.data["service"], alvo),
        ]
        self.proc = subprocess.Popen(  # noqa: S603  # NOSONAR - argv vem do SshClient
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", bufsize=1,
        )
        # Guardado numa variavel local: `self.proc.stdout` e Optional (Popen sem PIPE
        # nao tem saida), e e daqui que sai o laco que fica horas lendo.
        output = self.proc.stdout
        if output is None:
            return self._give_up("nao consegui abrir a saida do ssh")
        self.error = ""
        try:
            for line in output:
                if self._stop_signal.is_set():
                    break
                if player_line(line, enter, leave):
                    self._check()
        finally:
            self.stop_proc()
        return None

    def stop_proc(self) -> None:
        proc, self.proc = self.proc, None
        if not proc:
            return
        for fluxo in (proc.stdout, proc.stderr):
            if fluxo:
                with contextlib.suppress(OSError):
                    fluxo.close()
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.terminate()
        try:
            proc.wait(timeout=ESPERA_AO_ENCERRAR)  # sem isto sobra zumbi a cada reconexao
        except subprocess.TimeoutExpired:
            proc.kill()

    def _check(self) -> None:
        """A linha chegou: refaz a contagem pelo caminho normal e avisa se mudou."""
        agora = time.monotonic()
        if agora - self.last_fire < self.deps.debounce:
            return                     # um grupo entrando junto e UMA conferida
        self.last_fire = agora
        anterior = self.deps.monitor_state.get(self.sid)
        if anterior is None:
            return                     # sem linha de base ainda: a volta do monitor faz
        # O cache guarda o numero de ANTES da linha que acabou de chegar.
        self.deps.invalidate_players(self.sid)
        conn = self.deps.connect()     # esta thread vive fora do contexto do request
        try:
            cfg = self.deps.webhook_config(conn)
            with self.deps.players_lock(self.sid):
                self.deps.players_alert(conn, self.data,
                                              anterior.get("service", ""), anterior, cfg)
        finally:
            conn.close()


class Supervisor:
    """O registro das conexoes abertas: liga, desliga e ressuscita.

    `criar` vem de fora (e nao e `LogStream` direto) porque o teste do supervisor troca
    a classe por um dublê que so anota abrir/fechar — sem SSH nenhum.
    """

    def __init__(self, criar: Callable[[ServerLike, tuple], Any]) -> None:
        self._criar = criar
        self.abertos: dict[int, Any] = {}
        self._lock = threading.Lock()

    def alive_ids(self) -> int:
        """Quantas conexoes estao mesmo ouvindo agora (para a tela nao mentir)."""
        with self._lock:
            return sum(1 for s in self.abertos.values() if s.alive())

    def sync(self, servers: Sequence[ServerLike],
                   desejados: dict[int, tuple]) -> int:
        """Deixa o que esta aberto igual ao `desejados`. Devolve quantos ficaram."""
        por_id = {int(s["id"]): s for s in servers}

        with self._lock:
            atuais = list(self.abertos.items())
        for sid, stream in atuais:
            # Sai quem deixou de ser desejado e quem mudou de configuracao (regex nova,
            # log em outro caminho). Thread morta tambem sai, para o passo abaixo
            # levantar de novo — menos quando ela desistiu por cadastro invalido, que
            # recriar nao conserta: essa fica de lapide ate alguem arrumar o cadastro e
            # a assinatura mudar.
            trocou = sid not in desejados or desejados[sid] != stream.signature
            if trocou or (not stream.alive() and not stream.gave_up):
                stream.stop()
                with self._lock:
                    self.abertos.pop(sid, None)

        for sid, signature in desejados.items():
            with self._lock:
                if sid in self.abertos:
                    continue
                novo = self._criar(por_id[sid], signature)
                self.abertos[sid] = novo
            novo.start()

        with self._lock:
            return len(self.abertos)
