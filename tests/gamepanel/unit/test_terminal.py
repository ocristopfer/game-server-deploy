"""Interactive terminal session (gamepanel.runtime.terminal): PTY + real process.

There was no dedicated suite for this before Phase 4 (same finding as A2S and
metrics_probe: only exercised indirectly, and only by the `/servers/1/terminal` screen
loading, never by the session itself). `TermSession` receives `ssh_argv` by injection
(just as `SshClient` receives its config through a function) - here it becomes any local
process (`sh -c ...`), which proves buffer/offset/EOF/error without needing any SSH.

POSIX only: PTY does not exist on Windows (see `terminal.HAVE_PTY`), and POSIX is where
the panel terminal really runs (the panel container is Debian).
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


def _argv_of(*cmd: str):
    def ssh_argv(server, extra=()):
        return list(cmd)
    return ssh_argv


def _open_term(cmd: list[str], buffer_bytes: int = 64 * 1024) -> terminal.TermSession:
    return terminal.TermSession(
        _argv_of(*cmd), {"id": 1}, uid=1, username="tester", cols=80, rows=24,
        known_hosts="/tmp/known_hosts_de_teste", buffer_bytes=buffer_bytes,
    )


def _wait_for_death(term: terminal.TermSession, prazo: float = 3.0) -> None:
    end_at = time.monotonic() + prazo
    while term.alive and time.monotonic() < end_at:
        time.sleep(0.05)


def test_le_a_saida_do_processo_e_avanca_o_offset():
    term = _open_term(["sh", "-c", "printf hello"])
    try:
        data, offset, lost = term.read(0, wait=2.0)
        assert data == b"hello"
        assert offset == 5
        assert lost is False
    finally:
        term.close()


def test_offset_ja_lido_nao_volta_na_proxima_leitura():
    term = _open_term(["sh", "-c", "printf abc"])
    try:
        _data, offset, _lost = term.read(0, wait=2.0)
        # Nothing new after what was already read: the long-poll waits and returns empty.
        data2, offset2, lost2 = term.read(offset, wait=0.2)
        assert data2 == b""
        assert offset2 == offset
        assert lost2 is False
    finally:
        term.close()


def test_fim_do_processo_marca_morto_com_o_exit_code():
    term = _open_term(["sh", "-c", "exit 3"])
    try:
        _wait_for_death(term)
        assert term.alive is False
        assert term.exit_code == 3
    finally:
        term.close()


def test_buffer_cheio_descarta_o_mais_antigo_e_avisa_perda():
    # 100 bytes of 'A' followed by 100 of 'B', with a buffer that keeps only 60: whoever
    # asks from offset 0 has to know they lost something, not just receive less data.
    script = "printf 'A%.0s' $(seq 1 100); printf 'B%.0s' $(seq 1 100)"
    term = _open_term(["sh", "-c", script], buffer_bytes=60)
    try:
        _wait_for_death(term)
        data, _, lost = term.read(0, wait=1.0)
        assert lost is True
        assert len(data) <= 60
        assert data.endswith(b"B" * 60) or data.endswith(b"B" * len(data))
    finally:
        term.close()


def test_write_chega_ate_o_processo():
    # 'cat' echoes each line back; the PTY's own echo also lands in the buffer, so the
    # proof is only that the written text appears in the output, not the exact output.
    term = _open_term(["cat"])
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
    term = _open_term(["sleep", "2"])
    try:
        term.resize(120, 40)
        assert term.cols == 120
        assert term.rows == 40
        assert term.alive is True
    finally:
        term.close()


def test_close_mata_o_processo():
    term = _open_term(["sleep", "30"])
    term.close()
    assert term.alive is False
    deadline = time.monotonic() + 3.0
    while term.proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert term.proc.poll() is not None


def test_comando_inexistente_vira_remote_error():
    with pytest.raises(RemoteError):
        _open_term(["/nao/existe/binario-de-teste-xyz"])
