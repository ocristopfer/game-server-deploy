"""Instalador por SSH: leva o jogo para dentro do CT recem-criado e tira a chave do broker.

Fluxo (tudo com `ssh`/`scp` do sistema, nunca por shell):

  1. espera o sshd do CT responder (o template do Debian ja traz sshd);
  2. envia `ct-install.sh`, `ct-fases.sh` e um `install.env` para o CT;
  3. roda `bash ct-install.sh install.env` DENTRO do CT, repassando o log linha a linha;
  4. SEMPRE (deu certo ou nao) apaga o que enviou e **remove a chave do broker** do
     authorized_keys. Se a chave nao sair, a criacao FALHA: um CT novo nao pode nascer com
     acesso permanente do broker.

O `install.env` tem aspas em todo valor (`shlex.quote`): nada do catalogo e concatenado numa
linha de comando ou interpretado como shell pelo `source` do CT. Credencial de conta Steam
nunca entra (`STEAM_ANONYMOUS` e sempre 1: jogos que exigem conta nao sao criaveis por API).

As mesmas fases rodam no deploy manual (lib/ct-fases.sh via provision-game-lxc.sh); o sandbox
`docker/ct-sandbox/comparar.sh` prova que os dois caminhos geram exatamente o mesmo CT.
"""
from __future__ import annotations

import ipaddress
import re
import shlex
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gamebroker.services.allocator import ROLE_GAME, ROLE_QUERY, AllocatedPort, port_from_base, port_with_role
from gamebroker.services.catalog import RECIPES_WINDOWS, Game

DESTINO_REMOTO = "/root/gamepanel-install"
MARCA_DE_SUCESSO = "INSTALACAO CONCLUIDA"
ARQUIVOS_DA_LIB = ("ct-install.sh", "ct-fases.sh")
LINHA_MAX = 400
LOTE_LINHAS = 20
LOTE_SEGUNDOS = 1.5
CAUDA_DE_ERRO = 6
_BLOB_RE = re.compile(r"[A-Za-z0-9+/=]{20,}", re.ASCII)


class InstallError(RuntimeError):
    """A instalacao (ou a limpeza da chave) falhou. A mensagem vai para o log da operacao."""


class Executor(Protocol):
    def rodar(self, argv: Sequence[str], on_linha: Callable[[str], None] | None,
              timeout: float) -> int:
        """Roda `argv` (sem shell), repassa cada linha de saida e devolve o codigo de saida.
        Passou de `timeout` segundos: mata o processo e devolve um codigo negativo."""


class ExecutorReal:
    def rodar(self, argv: Sequence[str], on_linha: Callable[[str], None] | None,
              timeout: float) -> int:
        try:
            proc = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", bufsize=1)
        except OSError as erro:
            raise InstallError(f"nao consegui executar {argv[0]}: {erro.strerror}") from None
        # A leitura de linhas bloqueia; quem impoe o prazo e um timer que mata o processo.
        clock = threading.Timer(timeout, proc.kill)
        clock.start()
        try:
            assert proc.stdout is not None
            for linha in proc.stdout:
                if on_linha is not None:
                    on_linha(linha.rstrip("\r\n"))
            return proc.wait()
        finally:
            clock.cancel()
            if proc.poll() is None:
                proc.kill()


@dataclass(frozen=True)
class ConfigSsh:
    chave_privada: Path
    chave_publica: str          # linha completa da chave do broker, a que foi injetada no CT
    lib_dir: Path             # onde estao ct-install.sh e ct-fases.sh
    usuario: str = "root"
    espera_ssh: float = 180.0
    intervalo: float = 3.0
    timeout_instalacao: float = 7200.0
    timeout_comando: float = 120.0

    def __post_init__(self) -> None:
        partes = self.chave_publica.split()
        if len(partes) < 2 or not _BLOB_RE.fullmatch(partes[1]):
            raise ValueError("chave_publica: esperada uma linha de chave publica OpenSSH")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", self.usuario):
            raise ValueError("usuario invalido")

    @property
    def blob(self) -> str:
        return self.chave_publica.split()[1]


def build_env(jogo: Game, ports: Sequence[AllocatedPort]) -> str:
    """O `install.env` do CT. Cada valor entre aspas: e DADO, nunca comando."""
    runtimes = [r for r in jogo.recipes if r in RECIPES_WINDOWS]
    if len(runtimes) > 1:
        raise InstallError("escolha 'wine' OU 'proton', nao os dois")
    # Porta interna == externa (ver services/allocator.py): o jogo e avisado das portas JA alocadas.
    game_port = port_with_role(ports, ROLE_GAME) or jogo.game_port
    query_port = (port_with_role(ports, ROLE_QUERY) or jogo.query_port) if jogo.query_port else 0
    extra_port = (port_from_base(ports, jogo.extra_port) or jogo.extra_port) if jogo.extra_port else 0
    variaveis = {
        "GAME_KEY": jogo.key, "GAME_DISPLAY_NAME": jogo.name, "STEAM_APP_ID": str(jogo.app_id),
        "STEAM_PLATFORM": jogo.platform, "STEAM_ANONYMOUS": "1",
        "START_SCRIPT": jogo.start_script, "START_ARGS": jogo.start_args,
        "GAME_PORT": str(game_port), "QUERY_PORT": str(query_port), "EXTRA_PORT": str(extra_port),
        "GAME_PORTS": " ".join(str(p) for p in ports),
        "WINDOWS_RUNTIME": runtimes[0] if runtimes else "",
        "RECIPES": " ".join(r for r in jogo.recipes if r not in RECIPES_WINDOWS),
        # Shell so existe no catalogo curado, revisado no git; jogo cadastrado pela API vem vazio.
        "PRE_INSTALL_CMD": jogo.pre_install, "POST_INSTALL_CMD": jogo.post_install,
    }
    return "".join(f"{name}={shlex.quote(valor)}\n" for name, valor in variaveis.items())


class _Lote:
    """Junta linhas para gravar no log em blocos: o SteamCMD despeja milhares e cada gravacao
    e uma transacao no banco."""

    def __init__(self, log: Callable[[str], None], now: Callable[[], float]):
        self._log, self._agora = log, now
        self._linhas: list[str] = []
        self._ultimo = now()
        self.cauda: list[str] = []
        self.concluida = False

    def linha(self, texto: str) -> None:
        texto = texto.strip()[:LINHA_MAX]
        if not texto:
            return
        if MARCA_DE_SUCESSO in texto:
            self.concluida = True
        self.cauda = (self.cauda + [texto])[-CAUDA_DE_ERRO:]
        self._linhas.append(texto)
        if len(self._linhas) >= LOTE_LINHAS or self._agora() - self._ultimo >= LOTE_SEGUNDOS:
            self.descarrega()

    def descarrega(self) -> None:
        if self._linhas:
            self._log("\n".join(self._linhas))
            self._linhas = []
        self._ultimo = self._agora()


class InstaladorSsh:
    def __init__(self, config: ConfigSsh, executor: Executor | None = None,
                 dormir: Callable[[float], None] = time.sleep,
                 now: Callable[[], float] = time.monotonic):
        self._cfg = config
        self._exec = executor or ExecutorReal()
        self._dormir = dormir
        self._agora = now
        faltando = [a for a in ARQUIVOS_DA_LIB if not (config.lib_dir / a).is_file()]
        if faltando:
            raise ValueError(f"faltam em {config.lib_dir}: {', '.join(faltando)}")

    # --- comandos ------------------------------------------------------------------------

    def _opcoes(self) -> list[str]:
        # Chave nova de CT recem-criado: nao ha host key conhecida, e o IP e reaproveitado
        # depois que a instancia e removida (um known_hosts fixo recusaria o CT seguinte).
        return ["-i", str(self._cfg.chave_privada), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10"]

    def _ssh(self, target: str, comando: str) -> list[str]:
        return ["ssh", *self._opcoes(), target, comando]

    def _alvo(self, ip: str) -> str:
        return f"{self._cfg.usuario}@{ip}"

    # --- fluxo ----------------------------------------------------------------------------------

    def install(self, ip: str, jogo: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None]) -> None:
        ip = str(ipaddress.IPv4Address(ip))
        target = self._alvo(ip)
        env = build_env(jogo, ports)
        self._esperar_ssh(target, ip, log)
        falha: Exception | None = None
        try:
            self._enviar(target, env)
            self._install(target, log)
        except Exception as erro:  # noqa: BLE001
            falha = erro
            raise
        finally:
            self._limpar(target, log, falha)

    def _esperar_ssh(self, target: str, ip: str, log: Callable[[str], None]) -> None:
        log(f"aguardando o SSH de {ip}")
        limit = self._agora() + self._cfg.espera_ssh
        while True:
            if self._exec.rodar(self._ssh(target, "true"), None, 20) == 0:
                return
            if self._agora() >= limit:
                raise InstallError(f"o SSH de {ip} nao respondeu em {int(self._cfg.espera_ssh)} s")
            self._dormir(self._cfg.intervalo)

    def _enviar(self, target: str, env: str) -> None:
        pasta = shlex.quote(DESTINO_REMOTO)
        self._comando(self._ssh(target, f"install -d -m 700 {pasta}"), "criar a pasta no CT")
        with tempfile.TemporaryDirectory(prefix="broker-install-") as tmp:
            arquivo_env = Path(tmp) / "install.env"
            arquivo_env.write_text(env, encoding="utf-8", newline="\n")
            fontes = [str(self._cfg.lib_dir / a) for a in ARQUIVOS_DA_LIB] + [str(arquivo_env)]
            self._comando(["scp", *self._opcoes(), *fontes, f"{target}:{DESTINO_REMOTO}/"],
                          "enviar o instalador ao CT")

    def _comando(self, argv: Sequence[str], acao: str) -> None:
        codigo = self._exec.rodar(argv, None, self._cfg.timeout_comando)
        if codigo != 0:
            raise InstallError(f"falhou ao {acao} (codigo {codigo})")

    def _install(self, target: str, log: Callable[[str], None]) -> None:
        lote = _Lote(log, self._agora)
        comando = f"cd {shlex.quote(DESTINO_REMOTO)} && bash ct-install.sh install.env"
        codigo = self._exec.rodar(self._ssh(target, comando), lote.linha, self._cfg.timeout_instalacao)
        lote.descarrega()
        if codigo != 0:
            resumo = " | ".join(lote.cauda)
            raise InstallError(f"a instalacao falhou (codigo {codigo}): {resumo}")
        if not lote.concluida:
            raise InstallError("o instalador terminou sem confirmar a conclusao")

    def _limpar(self, target: str, log: Callable[[str], None], falha: Exception | None) -> None:
        """Apaga o que foi enviado e tira a chave do broker. Roda SEMPRE."""
        blob = self._cfg.blob
        arquivo = "/root/.ssh/authorized_keys"
        comando = (f"rm -rf {shlex.quote(DESTINO_REMOTO)}; "
                   f"grep -vF -- {shlex.quote(blob)} {arquivo} > {arquivo}.tmp; "
                   f"cat {arquivo}.tmp > {arquivo}; rm -f {arquivo}.tmp; "
                   f"! grep -qF -- {shlex.quote(blob)} {arquivo}")
        codigo = self._exec.rodar(self._ssh(target, comando), None, self._cfg.timeout_comando)
        if codigo == 0:
            log("chave do broker removida do container")
            return
        mensagem = f"nao consegui remover a chave do broker do container (codigo {codigo})"
        if falha is None:
            raise InstallError(mensagem)
        # Ja ha um erro mais importante a reportar; a limpeza falha so e registrada.
        log(f"AVISO: {mensagem}")
