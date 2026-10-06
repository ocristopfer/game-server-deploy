"""The automatic updater (`updater.py`): what it decides, what it trusts, what it writes.

The network is a fake opener serving a GitHub-shaped release; the installer is a fake `run`.
What runs for real is the decision, the sha256 check and the files between panel and root.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess

import pytest

from gamepanel import updater

ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]

TARBALL = b"conteudo do pacote"
NAME = "gamepanel-0.2.0+abc1234.tar.gz"
REPO = "dono/repo"


API_ASSETS = "https://api.github.com/repos/dono/repo/releases/assets/"


def _release(tag="v0.2.0", name=NAME, **extra) -> dict:
    data = {
        "tag_name": tag, "html_url": f"https://github.com/dono/repo/releases/tag/{tag}",
        "draft": False, "prerelease": False,
        "assets": [
            {"name": name, "url": API_ASSETS + "1"},
            {"name": f"{name}.sha256", "url": API_ASSETS + "2"},
            {"name": "gamebroker-0.2.0+abc1234.tar.gz", "url": API_ASSETS + "3"},
        ],
    }
    data.update(extra)
    return data


class FakeGitHub:
    def __init__(self, release: dict, tarball: bytes = TARBALL, sha: str = "") -> None:
        self.release = release
        self.tarball = tarball
        self.sha = sha or hashlib.sha256(tarball).hexdigest()
        self.urls: list[str] = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.urls.append(url)
        if url.endswith("/releases/latest"):
            body = json.dumps(self.release).encode()
        else:
            # An asset only comes as bytes when asked for them; without the header the API
            # answers the asset's JSON description instead.
            assert request.get_header("Accept") == "application/octet-stream"
            body = f"{self.sha}  {NAME}\n".encode() if url.endswith("/2") else self.tarball
        return io.BytesIO(body)


class FakeRun:
    def __init__(self, code: int = 0, output: str = "==> live: 0.2.0+abc1234\n") -> None:
        self.code, self.output, self.calls = code, output, []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert os.path.isfile(args[3])
        return subprocess.CompletedProcess(args, self.code, self.output, "")


HEALTH = "wget -q -O /dev/null http://127.0.0.1:8080/health"


@pytest.fixture
def dirs(tmp_path):
    installer = tmp_path / "install-release.sh"
    installer.write_text("#!/bin/bash\n")
    target = updater.PANEL._replace(installer=str(installer), health=HEALTH)
    return {"update_dir": str(tmp_path / "update"), "status_path": str(tmp_path / "st" / "status.json"),
            "target": target}


def _round(dirs, github, run, *, mode="auto", current="0.1.0+old", request=""):
    if request:
        updater.leave_request(dirs["update_dir"], request)
    deps = updater.Deps(github, run, lambda: "2026-10-06T03:00:00+0000")
    return updater.run_round(repo=REPO, default_mode=mode, current_version=current, deps=deps, **dirs)


@pytest.mark.parametrize(("text", "expected"), [
    ("0.2.0", (0, 2, 0)), ("v1.10.3", (1, 10, 3)), ("0.1.0+abc1234", (0, 1, 0)),
    ("0.1.0+abc1234.dirty", (0, 1, 0)), ("0.1.0+dev", (0, 1, 0)), ("lixo", None), ("1.2", None),
])
def test_versao(text, expected):
    assert updater.parse_version(text) == expected


def test_versao_compara_como_numero_e_nao_como_texto():
    assert updater.parse_version("0.10.0") > updater.parse_version("0.9.9")


def test_escolhe_o_pacote_do_painel_e_o_sha():
    release = updater.pick_release(_release(), "gamepanel")
    assert release.tarball_name == NAME
    assert release.sha_url == API_ASSETS + "2"


@pytest.mark.parametrize("data", [
    _release(prerelease=True),
    _release(draft=True),
    _release(tag="ultima"),
    _release(name="gamepanel-0.2.0+abc1234.dirty.tar.gz"),
    {"tag_name": "v0.2.0", "assets": [{"name": NAME, "url": API_ASSETS + "1"}]},
    [],
])
def test_release_que_nao_serve_e_recusada(data):
    with pytest.raises(updater.UpdateError):
        updater.pick_release(data, "gamepanel")


@pytest.mark.parametrize(("mode", "request_", "current", "latest", "expected"), [
    ("auto", "", (0, 1, 0), (0, 2, 0), "install"),
    ("auto", "", (0, 2, 0), (0, 2, 0), "none"),
    ("auto", "install", (0, 3, 0), (0, 2, 0), "none"),   # never downgrades
    ("auto", "", (1, 4, 0), (2, 0, 0), "none"),          # a new major is only announced
    ("auto", "install", (1, 4, 0), (2, 0, 0), "install"),
    ("auto", "check", (0, 1, 0), (0, 2, 0), "none"),
    ("notify", "", (0, 1, 0), (0, 2, 0), "none"),
    ("notify", "install", (0, 1, 0), (0, 2, 0), "install"),
    ("off", "install", (0, 1, 0), (0, 2, 0), "install"),
])
def test_decisao(mode, request_, current, latest, expected):
    assert updater.decide(mode, request_, current, latest) == expected


def test_sha_do_arquivo_no_formato_do_sha256sum():
    sha = "a" * 64
    assert updater.sha_from_file(f"{sha}  {NAME}\n", NAME) == sha
    assert updater.sha_from_file(sha, NAME) == sha
    with pytest.raises(updater.UpdateError):
        updater.sha_from_file(f"{sha}  outro.tar.gz", NAME)


def test_modo_automatico_instala_a_versao_nova(dirs):
    github, run = FakeGitHub(_release()), FakeRun()
    status = _round(dirs, github, run)
    assert status["result"] == "installed"
    assert status["current"] == "0.2.0+abc1234"
    [args] = run.calls
    assert args[:3] == ["bash", dirs["target"].installer, "gamepanel"]
    assert args[4] == hashlib.sha256(TARBALL).hexdigest()
    assert args[5:8] == ["/opt/gamepanel", "gamepanel.service", HEALTH]
    assert updater.read_status(dirs["status_path"])["installed_at"]


def test_sha_que_nao_confere_nao_chega_ao_instalador(dirs):
    github, run = FakeGitHub(_release(), sha="b" * 64), FakeRun()
    status = _round(dirs, github, run)
    assert status["result"] == "error"
    assert "sha256" in status["message"]
    assert run.calls == []


def test_instalador_que_falhou_vira_erro_com_a_saida(dirs):
    status = _round(dirs, FakeGitHub(_release()), FakeRun(1, "did NOT come up - rolling back"))
    assert status["result"] == "error"
    assert "rolling back" in status["message"]


def test_modo_avisar_so_anuncia(dirs):
    run = FakeRun()
    status = _round(dirs, FakeGitHub(_release()), run, mode="notify")
    assert (status["result"], status["available"], status["latest"]) == ("available", True, "0.2.0")
    assert run.calls == []


def test_em_dia(dirs):
    status = _round(dirs, FakeGitHub(_release()), FakeRun(), current="0.2.0+abc1234")
    assert (status["result"], status["available"]) == ("up_to_date", False)


def test_modo_desligado_nao_vai_a_rede(dirs):
    github = FakeGitHub(_release())
    status = _round(dirs, github, FakeRun(), mode="off")
    assert status["result"] == "off"
    assert github.urls == []


def test_pedido_da_tela_instala_mesmo_no_modo_avisar_e_e_consumido(dirs):
    run = FakeRun()
    status = _round(dirs, FakeGitHub(_release()), run, mode="notify", request="install")
    assert status["result"] == "installed"
    assert not os.path.exists(os.path.join(dirs["update_dir"], updater.REQUEST_FILE))


def test_modo_escolhido_na_tela_vence_o_do_deploy(dirs):
    updater.save_mode(dirs["update_dir"], "notify")
    run = FakeRun()
    status = _round(dirs, FakeGitHub(_release()), run, mode="auto")
    assert status["mode"] == "notify"
    assert run.calls == []


def test_url_fora_do_github_e_recusada(dirs):
    release = _release()
    release["assets"][0]["url"] = "https://exemplo.com/" + NAME
    run = FakeRun()
    status = _round(dirs, FakeGitHub(release), run)
    assert status["result"] == "error"
    assert run.calls == []


def test_sem_instalador_explica_o_que_fazer(dirs):
    dirs["target"] = dirs["target"]._replace(installer="/nao/existe/install-release.sh")
    status = _round(dirs, FakeGitHub(_release()), FakeRun())
    assert status["result"] == "error"
    assert "-Full" in status["message"]


def test_pedido_ou_modo_desconhecido_e_ignorado(tmp_path):
    folder = str(tmp_path)
    (tmp_path / updater.REQUEST_FILE).write_text("rm -rf /\n")
    (tmp_path / updater.MODE_FILE).write_text("tudo\n")
    assert updater.take_request(folder) == ""
    assert updater.read_mode(folder, "notify") == "notify"
    with pytest.raises(ValueError):
        updater.leave_request(folder, "rm")


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW") or os.name != "posix", reason="POSIX apenas")
def test_root_nao_segue_link_plantado_no_lugar_do_pedido(tmp_path):
    secret = tmp_path / "segredo"
    secret.write_text("install\n")
    (tmp_path / updater.MODE_FILE).symlink_to(secret)
    (tmp_path / updater.REQUEST_FILE).symlink_to(secret)
    assert updater.read_mode(str(tmp_path), "off") == "off"
    assert updater.take_request(str(tmp_path)) == ""
    # unlink removes the link, never what it points to.
    assert secret.exists()


def test_status_ausente_ou_quebrado_e_none(tmp_path):
    assert updater.read_status(str(tmp_path / "nada.json")) is None
    (tmp_path / "ruim.json").write_text("{meio")
    assert updater.read_status(str(tmp_path / "ruim.json")) is None


def test_main_recusa_argumento_desconhecido():
    assert updater.main(["instalar"]) == 2


def _core(path) -> str:
    text = path.read_text(encoding="utf-8")
    begin, end = "# >>> shared updater core", "# <<< shared updater core"
    assert text.count(begin) == 1 and text.count(end) == 1, path
    return text[text.index(begin):text.index(end)]


def test_o_nucleo_do_atualizador_e_o_mesmo_no_painel_e_no_broker():
    """The broker's CT has no `gamepanel` to import it from, so the core is copied; a fix made in
    one copy only would leave the other updating with the old bug."""
    assert _core(ROOT / "src/gamepanel/updater.py") == _core(ROOT / "src/gamebroker/updater.py")


def test_o_broker_escolhe_o_pacote_dele_na_release():
    from gamebroker import updater as broker_updater
    data = _release()
    data["assets"].append({"name": "gamebroker-0.2.0+abc1234.tar.gz.sha256", "url": API_ASSETS + "4"})
    release = broker_updater.pick_release(data, broker_updater.BROKER.package)
    assert (release.tarball_name, release.sha_url) == ("gamebroker-0.2.0+abc1234.tar.gz", API_ASSETS + "4")


def test_o_painel_sabe_rodar_o_proprio_atualizador_com_a_config():
    assert updater.main(["run", "extra"]) == 2
