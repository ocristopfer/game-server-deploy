"""Theme (light/dark) and language via the header buttons, including before login."""
from __future__ import annotations

from gamepanel import app as panel
from gamepanel.persistence.repositories import users as users_repo


def _csrf(cli):
    cli.get("/login")
    with cli.session_transaction() as sess:
        return sess.get("csrf", "")


def test_a_tela_de_login_ja_traz_os_dois_botoes(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'action="/preferences/theme"' in html
    assert 'action="/preferences/language"' in html


def test_sem_escolha_o_tema_segue_o_aparelho(client):
    html = client.get("/login").get_data(as_text=True)
    assert "data-theme=" not in html
    assert 'content="dark light"' in html


def test_escolher_o_tema_claro_grava_cookie_e_volta_para_a_pagina(client):
    token = _csrf(client)
    resp = client.post("/preferences/theme", data={"csrf": token, "theme": "light", "next": "/login?x=1"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login?x=1")
    assert "theme=light" in resp.headers["Set-Cookie"]
    html = client.get("/login").get_data(as_text=True)
    assert 'data-theme="light"' in html
    # The button now offers the OTHER theme.
    assert 'name="theme" value="dark"' in html


def test_tema_desconhecido_nao_vira_cookie(client):
    token = _csrf(client)
    resp = client.post("/preferences/theme", data={"csrf": token, "theme": "roxo"})
    assert "Set-Cookie" not in resp.headers or "theme=" not in resp.headers["Set-Cookie"]


def test_o_next_de_fora_do_painel_e_ignorado(client):
    token = _csrf(client)
    for evil in ("//evil.example", "/\\evil.example", "https://evil.example/"):
        resp = client.post("/preferences/theme", data={"csrf": token, "theme": "dark", "next": evil})
        assert "evil" not in resp.headers["Location"], evil


def test_sem_csrf_nao_troca_nada(client):
    resp = client.post("/preferences/theme", data={"theme": "light"})
    assert resp.status_code == 400


def test_o_idioma_antes_do_login_vem_do_cookie(client):
    token = _csrf(client)
    client.post("/preferences/language", data={"csrf": token, "lang": "en", "next": "/login"},
                headers={"Accept-Language": "pt-BR"})
    html = client.get("/login", headers={"Accept-Language": "pt-BR"}).get_data(as_text=True)
    assert '<html lang="en' in html
    # The button offers switching back to Portuguese.
    assert 'name="lang" value="pt"' in html


def test_logado_o_idioma_tambem_vai_para_a_conta(admin, post):
    post(admin, "/preferences/language", {"lang": "en", "next": "/"})
    with panel.app.app_context():
        row = users_repo.by_username(panel.db(), "chefe")
    assert row["lang"] == "en"
