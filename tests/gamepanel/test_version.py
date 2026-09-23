"""Versao do painel: de onde ela sai, o que ela promete e onde aparece."""
from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from gamepanel import app as panel
from gamepanel import version

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools" / "build-release.py"


def test_a_versao_do_repositorio_e_marcada_como_dev():
    """Sem `_build.py` nao ha release: o `+dev` e o que impede confundir os dois.

    "O painel esta na 0.1.0" so quer dizer alguma coisa se a maquina de quem le nao
    responde a mesma frase.
    """
    build = version.Build(version.version_from_repo(version.__file__) + version.DEV_SUFFIX, "", "")
    assert build.is_dev
    assert build.version.startswith(version.version_from_repo(version.__file__))


def test_versao_de_release_nao_e_dev():
    assert not version.Build("0.1.0+abc1234", "abc1234", "2026-01-01T00:00:00Z").is_dev


def test_sem_arquivo_VERSION_a_versao_e_conhecidamente_desconhecida(tmp_path):
    """Nao achar o arquivo nao pode virar excecao: o painel sobe sem versao declarada."""
    orphan = tmp_path / "gamepanel" / "version.py"
    orphan.parent.mkdir()
    orphan.write_text("", encoding="utf-8")
    assert version.version_from_repo(str(orphan)) == version.UNKNOWN


def test_o_VERSION_da_raiz_e_o_que_o_pacote_le():
    assert version.version_from_repo(version.__file__) == (ROOT / "VERSION").read_text().strip()


def test_health_diz_qual_codigo_respondeu(cliente):
    """O deploy pergunta aqui se subiu o que ele acabou de mandar.

    "O servico esta de pe" e compativel com "o systemd reiniciou a versao velha": os
    dois casos dao 200. Quem separa os dois e a versao no corpo.
    """
    body = cliente.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["version"] == version.BUILD.version
    assert set(body) == {"status", "version", "commit", "built_at"}


def test_health_nao_vaza_nada_alem_de_identidade_de_codigo(cliente):
    """Rota sem sessao: caminho, endereco ou nome de usuario aqui seriam publicos."""
    raw = cliente.get("/health").get_data(as_text=True)
    for forbidden in ("/opt", "/var", "admin", "sqlite", "192.168"):
        assert forbidden not in raw


def test_a_versao_aparece_no_rodape_de_toda_tela(chefe):
    html = chefe.get("/").get_data(as_text=True)
    assert version.BUILD.version in html


def test_no_repositorio_a_marca_do_service_worker_e_o_mtime(monkeypatch):
    """Sem release nao ha versao que mude ao salvar um CSS — a marca volta a ser o mtime.

    Se ela ficasse parada no `+dev`, editar o estilo deixaria de invalidar o cache e o
    navegador serviria o arquivo velho ate alguem limpar a mao.
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
    """Hash igual para o mesmo codigo e o que faz o sha256 responder "o CT esta com
    ESTE codigo?" — e nao so "o arquivo chegou inteiro?"."""
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


def test_o_stamp_nunca_e_gravado_na_arvore(tmp_path):
    """`_build.py` so existe dentro do tarball: na arvore ele sujaria o `git status` e,
    pior, faria o painel de desenvolvimento se apresentar como um release."""
    subprocess.run([sys.executable, str(BUILDER), "gamepanel", "--out", str(tmp_path)],
                   cwd=ROOT, check=True, capture_output=True)
    assert not (ROOT / "src" / "gamepanel" / "_build.py").exists()
    assert not (ROOT / "src" / "gamebroker" / "_build.py").exists()
