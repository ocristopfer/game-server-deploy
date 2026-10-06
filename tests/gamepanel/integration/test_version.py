"""Panel version: where it comes from, what it promises and where it shows up."""
from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from gamepanel import app as panel
from gamepanel import version

ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / "tools" / "build-release.py"


def test_a_versao_do_repositorio_e_marcada_como_dev():
    """Without `_build.py` there is no release: the `+dev` is what prevents mixing the two up.

    "The panel is on 0.1.0" only means something if the reader's own machine does not
    answer with the same sentence.
    """
    build = version.Build(version.version_from_repo(version.__file__) + version.DEV_SUFFIX, "", "")
    assert build.is_dev
    assert build.version.startswith(version.version_from_repo(version.__file__))


def test_versao_de_release_nao_e_dev():
    assert not version.Build("0.1.0+abc1234", "abc1234", "2026-01-01T00:00:00Z").is_dev


def test_sem_arquivo_VERSION_a_versao_e_conhecidamente_desconhecida(tmp_path):
    """Not finding the file must not become an exception: the panel starts with no declared version."""
    orphan = tmp_path / "gamepanel" / "version.py"
    orphan.parent.mkdir()
    orphan.write_text("", encoding="utf-8")
    assert version.version_from_repo(str(orphan)) == version.UNKNOWN


def test_o_VERSION_da_raiz_e_o_que_o_pacote_le():
    assert version.version_from_repo(version.__file__) == (ROOT / "VERSION").read_text().strip()


def test_health_diz_qual_codigo_respondeu(client):
    """The deploy asks here whether what it just sent is what came up.

    "The service is up" is compatible with "systemd restarted the old version": both cases
    give 200. What tells them apart is the version in the body.
    """
    body = client.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["version"] == version.BUILD.version
    assert set(body) == {"status", "version", "commit", "built_at"}


def test_health_nao_vaza_nada_alem_de_identidade_de_codigo(client):
    """A route without a session: a path, address or username here would be public."""
    raw = client.get("/health").get_data(as_text=True)
    for forbidden in ("/opt", "/var", "admin", "sqlite", "192.168"):
        assert forbidden not in raw


def test_a_versao_aparece_no_rodape_de_toda_tela(admin):
    html = admin.get("/").get_data(as_text=True)
    assert version.BUILD.version in html


def test_no_repositorio_a_marca_do_service_worker_e_o_mtime(monkeypatch):
    """Without a release no version changes when a CSS is saved - the mark falls back to the mtime.

    If it stayed stuck on `+dev`, editing the styles would stop invalidating the cache and the
    browser would serve the old file until someone cleared it by hand.
    """
    monkeypatch.setattr(version, "BUILD", version.Build("0.1.0+dev", "", ""))
    with panel.app.test_request_context():
        _urls, mark = panel._shell_files()
    assert mark.isdigit()


def test_num_release_a_marca_do_service_worker_e_a_versao(monkeypatch):
    monkeypatch.setattr(version, "BUILD", version.Build("0.1.0+abc1234", "abc1234", "x"))
    with panel.app.test_request_context():
        _urls, mark = panel._shell_files()
    assert mark == "0.1.0+abc1234"


@pytest.mark.parametrize("package", ["gamepanel", "gamebroker"])
def test_o_empacotador_gera_o_mesmo_arquivo_duas_vezes(tmp_path, package):
    """The same hash for the same code is what makes the sha256 answer "is the CT running
    THIS code?" - and not just "did the file arrive whole?"."""
    archives = []
    for _ in range(2):
        subprocess.run([sys.executable, str(BUILDER), package, "--out", str(tmp_path)],
                       cwd=ROOT, check=True, capture_output=True)
        target = next(tmp_path.glob(f"{package}-*.tar.gz"))
        archives.append(target.read_bytes())
    assert archives[0] == archives[1]


def test_o_pacote_carrega_o_stamp_e_nenhum_bytecode(tmp_path):
    subprocess.run([sys.executable, str(BUILDER), "gamepanel", "--out", str(tmp_path)],
                   cwd=ROOT, check=True, capture_output=True)
    target = next(tmp_path.glob("gamepanel-*.tar.gz"))
    with tarfile.open(target) as tar:
        names = tar.getnames()
        stamp = tar.extractfile("gamepanel/_build.py").read().decode("utf-8")
    assert "gamepanel/app.py" in names
    assert "gamepanel/templates/base.html" in names
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    assert "VERSION = " in stamp


def test_o_pacote_do_painel_nao_leva_lib_nem_games(tmp_path):
    subprocess.run([sys.executable, str(BUILDER), "gamepanel", "--out", str(tmp_path)],
                   cwd=ROOT, check=True, capture_output=True)
    with tarfile.open(next(tmp_path.glob("gamepanel-*.tar.gz"))) as tar:
        assert {n.split("/", 1)[0] for n in tar.getnames()} == {"gamepanel"}


def test_o_pacote_do_broker_leva_lib_e_games_junto_do_codigo(tmp_path):
    """The broker runs the install scripts and reads the catalog at runtime: in the release
    folder they switch versions (and roll back) together with the code."""
    subprocess.run([sys.executable, str(BUILDER), "gamebroker", "--out", str(tmp_path)],
                   cwd=ROOT, check=True, capture_output=True)
    with tarfile.open(next(tmp_path.glob("gamebroker-*.tar.gz"))) as tar:
        names = set(tar.getnames())
    assert {n.split("/", 1)[0] for n in names} == {"gamebroker", "lib", "games"}
    assert {f"lib/{p.name}" for p in (ROOT / "lib").glob("*.sh")} <= names
    assert {f"games/{p.name}" for p in (ROOT / "games").glob("*.env")} <= names
    assert "gamebroker/healthcheck.py" in names
    assert "gamebroker/updater.py" in names


def test_o_stamp_nunca_e_gravado_na_arvore(tmp_path):
    """`_build.py` only exists inside the tarball: in the tree it would dirty `git status`
    and, worse, make the development panel present itself as a release."""
    subprocess.run([sys.executable, str(BUILDER), "gamepanel", "--out", str(tmp_path)],
                   cwd=ROOT, check=True, capture_output=True)
    assert not (ROOT / "src" / "gamepanel" / "_build.py").exists()
    assert not (ROOT / "src" / "gamebroker" / "_build.py").exists()
