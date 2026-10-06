"""The broker's updater entry point and its health probe (`gamebroker/updater.py`, `healthcheck.py`).

The core shared with the panel is tested in tests/gamepanel/unit/test_updater.py, which also
checks that the two copies are identical.
"""
from __future__ import annotations

import pytest

from gamebroker import healthcheck, updater

GOOD = ["run", "--repo", "dono/repo", "--mode", "auto", "--port", "8443"]


def test_argumentos_da_unidade():
    assert updater.parse_args(GOOD) == ("dono/repo", "auto", 8443)
    # Order does not matter, the values do.
    assert updater.parse_args(["run", "--port", "1", "--mode", "off", "--repo", "a/b"]) == ("a/b", "off", 1)


@pytest.mark.parametrize("args", [
    [],
    ["check", *GOOD[1:]],
    GOOD[:-2],
    ["run", "--repo", "dono/repo;rm -rf /", "--mode", "auto", "--port", "8443"],
    ["run", "--repo", "dono/repo", "--mode", "sempre", "--port", "8443"],
    ["run", "--repo", "dono/repo", "--mode", "auto", "--port", "0"],
    ["run", "--repo", "dono/repo", "--mode", "auto", "--port", "99999"],
    ["run", "--repo", "dono/repo", "--mode", "auto", "--extra", "1"],
])
def test_argumento_ruim_e_recusado(args):
    assert updater.parse_args(args) is None
    assert updater.main(args) == 2


def test_alvo_do_broker():
    assert updater.BROKER.package == "gamebroker"
    assert updater.BROKER.service == "gamebroker.service"
    assert updater.BROKER.installer == "/usr/local/lib/gamebroker/install-release.sh"


def test_sonda_sem_token_ou_certificado_falha_sem_vazar_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(healthcheck, "TOKEN_FILE", str(tmp_path / "nao-existe"))
    assert "cannot read" in healthcheck.check(8443)


@pytest.mark.parametrize("args", [[], ["--port"], ["--port", "abc"], ["--port", "0"], ["--porta", "1"]])
def test_sonda_com_argumento_ruim(args):
    assert healthcheck.main(args) == 2
