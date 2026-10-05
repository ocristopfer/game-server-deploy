"""The Config screen speaks the language of whoever is looking - game fields included.

The panel's own text was already translated, but the labels of each game's fields, their help
and option texts, the section names and the validation errors lived as Portuguese sentences in
`games/` and came out in Portuguese on the English screen: 200, whole HTML, nothing in any log.
This test opens the screen in both languages against a fake Palworld file.
"""
from __future__ import annotations

import pytest

from gamepanel import app as panel

PALWORLD = (
    "[/Script/Pal.PalGameWorldSettings]\n"
    'OptionSettings=(ExpRate=1.000000,DeathPenalty=All,ServerName="Teste",ServerPlayerMaxNum=8)\n'
)
DRAGONWILDS = "ServerName=Teste\nloose=1\n[Section]\nOwnerId=abc\n"
FILES = {"/opt/game/PalWorldSettings.ini": PALWORLD, "/opt/game/DedicatedServer.ini": DRAGONWILDS}


@pytest.fixture
def config_server(database, monkeypatch) -> int:
    monkeypatch.setattr(panel, "ALLOW_FILES", True)

    def fake_read(_server, path):
        text = FILES[path]
        return {"name": path.rsplit("/", 1)[-1], "text": text, "binary": False, "truncated": False,
                "size": len(text), "crlf": False, "owner": "steam", "mtime": "2026-01-01 00:00"}

    monkeypatch.setattr(panel, "read_file", fake_read)
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path, config_files,"
            " created_at) VALUES ('pal', 'nao-existe-de-proposito.invalid', 22, 'root', 'jogo.service',"
            " '/opt/game', ?, ?)", ("\n".join(FILES), panel.now_iso()))
    return database.execute("SELECT id FROM servers WHERE name = 'pal'").fetchone()["id"]


def _page(cli, sid: int, path: str) -> str:
    resp = cli.get(f"/servers/{sid}/config?file={path}")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_em_portugues_os_rotulos_do_jogo_saem_como_antes(admin, config_server):
    html = _page(admin, config_server, "/opt/game/PalWorldSettings.ini")
    assert "Ganho de XP" in html
    assert "Penalidade de morte" in html
    assert "Tudo (inclui Pals)" in html
    assert "Nome do servidor" in html
    assert "game.palworld." not in html, "chave crua na tela: falta no catalogo"


def test_em_ingles_os_rotulos_do_jogo_saem_em_ingles(admin, config_server, post):
    post(admin, "/account/language", {"lang": "en"})
    html = _page(admin, config_server, "/opt/game/PalWorldSettings.ini")
    for text in ("EXP rate", "Death penalty", "Everything (Pals included)", "Server name",
                 "Multiplies all experience gained.", "Max players"):
        assert text in html, text
    for text in ("Ganho de XP", "Penalidade de morte", "Nome do servidor", "Vagas"):
        assert text not in html, text
    assert "game.palworld." not in html


def test_em_ingles_o_bloco_sem_nome_tambem_e_traduzido(admin, config_server, post):
    post(admin, "/account/language", {"lang": "en"})
    html = _page(admin, config_server, "/opt/game/DedicatedServer.ini")
    assert "(no section)" in html
    assert "(sem seção)" not in html
    assert "Owner ID" in html
    # A real section name is not a catalog key and passes through `_()` unchanged.
    assert "[Section]" in html


def test_erro_de_validacao_sai_no_idioma_de_quem_salva(admin, config_server, post):
    post(admin, "/account/language", {"lang": "en"})
    resp = post(admin, f"/servers/{config_server}/config/save", {
        "path": "/opt/game/PalWorldSettings.ini", "n": "1",
        "key.0": "ExpRate", "val.0": "999", "orig.0": "1", "id.0": "x", "sec.0": "",
    })
    assert resp.status_code == 302
    html = admin.get(resp.headers["Location"]).get_data(as_text=True)
    assert "EXP rate: maximum 20 x" in html
    assert "maximo" not in html
