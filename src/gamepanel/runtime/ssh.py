"""Camada de transporte SSH: fala com o container de jogo (LXC ou Docker) rodando o
`ssh` do sistema, nunca uma biblioteca Python de SSH - o container do painel so tem
`openssh-client` do apt, sem pip.

Root nos containers de jogo passa por aqui. `SshClient.run` e o unico caminho: recebe
o comando ja montado (com `shlex.quote` de quem chamou), nunca um argumento cru vindo
de formulario.
"""
from __future__ import annotations

import os
import shlex
import sqlite3
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# Um servidor cadastrado, como esta camada precisa enxerga-lo: ou a linha do SQLite, ou
# uma copia dela em dict (usada pelas tarefas longas, que nao podem levar uma conexao de
# outra thread). As duas respondem a `server["host"]`, que e tudo o que importa aqui.
ServerLike = sqlite3.Row | Mapping[str, Any]


class RemoteError(RuntimeError):
    pass


def quote_command(*parts: str) -> str:
    return " ".join(shlex.quote(p) for p in parts)


@dataclass(frozen=True)
class SshConfig:
    """O que o cliente precisa saber para falar com QUALQUER container de jogo."""

    key: str
    known_hosts: str
    control_dir: str
    control_persist: str
    quick_timeout: int = 20


class SshClient:
    """Uma instancia por painel (a chave e a mesma para todo container de jogo).

    Recebe a config por FUNCAO, nao por valor: os testes trocam `SSH_CONTROL_DIR` etc.
    via `monkeypatch.setattr(panel, "SSH_CONTROL_DIR", ...)` a qualquer momento, e cada
    chamada aqui precisa enxergar o valor mais recente - uma config capturada uma vez
    no import deixaria essa troca de teste sem efeito nenhum (silenciosamente).
    """

    def __init__(self, config: Callable[[], SshConfig]) -> None:
        self._config_provider = config

    @property
    def _config(self) -> SshConfig:
        return self._config_provider()

    def _mux_argv(self) -> list[str]:
        """Opcoes que fazem varias chamadas dividirem UMA conexao TCP.

        Sem isto cada leitura do monitor paga TCP + troca de chaves + autenticacao + um
        processo novo — uns 100ms na LAN para depois rodar um `systemctl show` de 5ms. Com a
        conexao mestre de pe, a segunda chamada em diante custa quase nada.

        %C e o hash de (host, porta, usuario): nome curto e unico por destino, que importa
        porque socket de unix tem limite baixo de caminho.
        """
        try:
            os.makedirs(self._config.control_dir, mode=0o700, exist_ok=True)
        except OSError:
            # Sem onde por o socket, seguir sem reaproveitar e melhor do que nao falar SSH.
            return []
        return ["-o", "ControlMaster=auto",
                "-o", f"ControlPath={os.path.join(self._config.control_dir, '%C')}",
                "-o", f"ControlPersist={self._config.control_persist}"]

    def argv(self, server: ServerLike, connect_timeout: int = 10,
              extra: tuple[str, ...] = (), multiplex: bool = False) -> list[str]:
        """Argumentos comuns do cliente ssh (usados pelos comandos e pelo terminal).

        `multiplex` so para as chamadas CURTAS e frequentes do monitor. Fica desligado por
        padrao porque as outras tres nao querem dividir conexao: o terminal segura a sessao
        por horas, e subir/baixar arquivo de varios GB entupiria o TCP compartilhado e
        travaria toda leitura do monitor atras da transferencia.
        """
        return [
            "ssh",
            "-i", self._config.key,
            "-p", str(server["ssh_port"]),
            "-o", "BatchMode=yes",
            "-o", f"UserKnownHostsFile={self._config.known_hosts}",
            # accept-new: aprende a host key no primeiro acesso, mas alerta se ela mudar.
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ConnectTimeout={connect_timeout}",
            *(self._mux_argv() if multiplex else ()),
            *extra,
            f"{server['ssh_user']}@{server['host']}",
        ]

    def run(
        self,
        server: ServerLike,
        remote_cmd: str,
        timeout: int | None = None,
        stdin_data: bytes | None = None,
        multiplex: bool = True,
    ) -> subprocess.CompletedProcess:
        """Executa um comando no container de jogo via SSH.

        `remote_cmd` ja vem montado com shlex.quote pelos helpers de quem chama; o SSH o
        entrega inteiro para o shell do destino, entao nada aqui pode vir cru de um
        formulario. `stdin_data` alimenta a entrada do comando remoto (usado para gravar
        arquivos).

        `multiplex=False` para o que demora: um update de uma hora seguraria a conexao
        mestre o tempo todo, e qualquer soluco nele derrubaria junto as leituras do
        monitor que estivessem pegando carona.
        """
        timeout = self._config.quick_timeout if timeout is None else timeout
        cmd = [*self.argv(server, connect_timeout=min(timeout, 10), multiplex=multiplex), remote_cmd]
        # Lista de argumentos (nunca shell=True) e `remote_cmd` sempre pre-quotado por
        # shlex.quote de quem chama (ver docstring) - nao e comando cru de formulario.
        try:
            if stdin_data is not None:
                proc = subprocess.run(  # noqa: S603  # NOSONAR
                    cmd, input=stdin_data, capture_output=True, timeout=timeout, check=False
                )
                # Binario na entrada, texto na saida: as mensagens de erro sao sempre texto.
                return subprocess.CompletedProcess(
                    proc.args,
                    proc.returncode,
                    proc.stdout.decode("utf-8", "replace"),
                    proc.stderr.decode("utf-8", "replace"),
                )
            return subprocess.run(  # noqa: S603  # NOSONAR
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            raise RemoteError(f"tempo esgotado ({timeout}s) executando no host {server['host']}") from None
        except OSError as exc:
            raise RemoteError(f"falha ao executar ssh: {exc}") from exc

    def output(self, server: ServerLike, remote_cmd: str, timeout: int | None = None) -> str:
        proc = self.run(server, remote_cmd, timeout=timeout)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RemoteError(detail or f"comando falhou (exit {proc.returncode})")
        return proc.stdout.strip()

    def public_key(self) -> str:
        try:
            with open(f"{self._config.key}.pub", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""
