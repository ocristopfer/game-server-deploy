"""Sessao de terminal interativo (gamepanel.runtime.terminal): PTY + processo real.

Nao existia suite dedicada para isso antes da Fase 4 (mesmo achado do A2S e do
metrics_probe: so exercitado indiretamente, e so pela tela `/servers/1/terminal`
carregando, nunca pela sessao em si). `TermSession` recebe o `ssh_argv` por injecao
(assim como `SshClient` recebe a config por funcao) - aqui ele vira um processo local
qualquer (`sh -c ...`), o que prova o buffer/offset/EOF/erro sem precisar de SSH nenhum.

So roda em POSIX: PTY nao existe no Windows (ver `terminal.HAVE_PTY`), e e onde o
terminal do painel roda de verdade (o container do painel e Debian).
"""
from __future__ import annotations

import os
import time

import pytest

from gamepanel.runtime.ssh import RemoteError

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="PTY e POSIX puro; o terminal so roda no container")

if os.name == "posix":
    from gamepanel.runtime import terminal


def _argv_de(*cmd: str):
    def ssh_argv(server, extra=()):
        return list(cmd)
    return ssh_argv


def _abrir(cmd: list[str], buffer_bytes: int = 64 * 1024) -> terminal.TermSession:
    return terminal.TermSession(
        _argv_de(*cmd), {"id": 1}, uid=1, username="tester", cols=80, rows=24,
        known_hosts="/tmp/known_hosts_de_teste", buffer_bytes=buffer_bytes,
    )


def _espera_morrer(term: terminal.TermSession, prazo: float = 3.0) -> None:
    fim = time.monotonic() + prazo
    while term.alive and time.monotonic() < fim:
        time.sleep(0.05)


def test_le_a_saida_do_processo_e_avanca_o_offset():
    term = _abrir(["sh", "-c", "printf hello"])
    try:
        data, offset, lost = term.read(0, wait=2.0)
        assert data == b"hello"
        assert offset == 5
        assert lost is False
    finally:
        term.close()


def test_offset_ja_lido_nao_volta_na_proxima_leitura():
    term = _abrir(["sh", "-c", "printf abc"])
    try:
        _data, offset, _lost = term.read(0, wait=2.0)
        # Sem novidade depois do que ja foi lido: o long-poll espera e devolve vazio.
        data2, offset2, lost2 = term.read(offset, wait=0.2)
        assert data2 == b""
        assert offset2 == offset
        assert lost2 is False
    finally:
        term.close()


def test_fim_do_processo_marca_morto_com_o_exit_code():
    term = _abrir(["sh", "-c", "exit 3"])
    try:
        _espera_morrer(term)
        assert term.alive is False
        assert term.exit_code == 3
    finally:
        term.close()


def test_buffer_cheio_descarta_o_mais_antigo_e_avisa_perda():
    # 100 bytes de 'A' seguidos de 100 de 'B', com um buffer que so guarda 60: quem
    # pedir desde o offset 0 tem de saber que perdeu coisa, nao so receber menos dado.
    script = "printf 'A%.0s' $(seq 1 100); printf 'B%.0s' $(seq 1 100)"
    term = _abrir(["sh", "-c", script], buffer_bytes=60)
    try:
        _espera_morrer(term)
        data, _, lost = term.read(0, wait=1.0)
        assert lost is True
        assert len(data) <= 60
        assert data.endswith(b"B" * 60) or data.endswith(b"B" * len(data))
    finally:
        term.close()


def test_write_chega_ate_o_processo():
    # 'cat' devolve cada linha; o eco do proprio PTY tambem aparece no buffer, entao a
    # prova e so que o texto escrito aparece na saida, nao a saida exata.
    term = _abrir(["cat"])
    try:
        term.write(b"ping\n")
        deadline = time.monotonic() + 2.0
        seen = b""
        while b"ping" not in seen and time.monotonic() < deadline:
            chunk, _, _ = term.read(len(seen), wait=0.5)
            seen += chunk
        assert b"ping" in seen
    finally:
        term.close()


def test_resize_nao_derruba_a_sessao():
    term = _abrir(["sleep", "2"])
    try:
        term.resize(120, 40)
        assert term.cols == 120
        assert term.rows == 40
        assert term.alive is True
    finally:
        term.close()


def test_close_mata_o_processo():
    term = _abrir(["sleep", "30"])
    term.close()
    assert term.alive is False
    deadline = time.monotonic() + 3.0
    while term.proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert term.proc.poll() is not None


def test_comando_inexistente_vira_remote_error():
    with pytest.raises(RemoteError):
        _abrir(["/nao/existe/binario-de-teste-xyz"])
