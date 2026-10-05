"""Interface map (ui.py): who sees what in the wide bar, and what lights up on each route."""
from __future__ import annotations

from gamepanel import navigation as ui


def _keys(itens):
    return [i.key for i in itens]


def test_admin_com_broker_ve_tudo_na_barra_larga():
    slash, account = ui.nav_desktop(admin=True, broker=True)
    assert _keys(slash) == ["servidores", "instancias", "catalogo", "historico", "backups", "alertas",
                            "usuarios"]
    assert _keys(account) == ["conta", "ssh"]


def test_sem_broker_a_barra_nao_oferece_link_que_da_403():
    slash, _ = ui.nav_desktop(admin=True, broker=False)
    assert not {"instancias", "catalogo"} & set(_keys(slash))


def test_operador_so_ve_o_que_pode_abrir():
    slash, account = ui.nav_desktop(admin=False, broker=True)
    assert _keys(slash) == ["servidores", "historico"]
    assert _keys(account) == ["conta", "ssh"]


def test_toda_chave_da_barra_larga_existe_nas_listas_de_itens():
    """A mistyped key in NAV_DESKTOP_* would only blow up at runtime, on the first page."""
    for key in ui.NAV_DESKTOP_BAR + ui.NAV_DESKTOP_ACCOUNT:
        assert key in ui._ALL_ITEMS


def test_no_desktop_cada_destino_acende_o_proprio_item():
    assert ui.active_desktop_nav_for("broker.instances") == "instancias"
    assert ui.active_desktop_nav_for("broker.catalog_new") == "catalogo"
    assert ui.active_desktop_nav_for("users.index") == "usuarios"
    assert ui.active_desktop_nav_for("account.ssh_key") == "ssh"
    assert ui.active_desktop_nav_for("account.index") == "conta"


def test_no_celular_a_aba_de_cima_continua_acesa():
    """There are only four tabs at the bottom: 'Instancias' lights 'Servidores' and 'Usuarios' lights 'Conta'."""
    assert ui.active_nav_for("broker.instances") == "servidores"
    assert ui.active_nav_for("users.index") == "conta"


def test_tela_de_servidor_acende_servidores_nos_dois():
    assert ui.active_desktop_nav_for("servers.detail") == "servidores"
    assert ui.active_desktop_nav_for("history.index") == "historico"
    assert ui.active_desktop_nav_for("rota_que_nao_existe") == ""


def test_barra_larga_usa_rotulo_curto_quando_ha(admin, monkeypatch):
    from gamepanel import app as panel
    monkeypatch.setattr(panel, "ALLOW_BROKER", True)
    html = admin.get("/").get_data(as_text=True)
    start = html.index('class="appbar__nav"')
    slash = html[start:html.index("</nav>", start)]
    assert ">Instâncias</a>" in slash
    assert ">Catálogo</a>" in slash
    assert "Instancias de jogo" not in slash


# --------------------------------------------- the page's DECLARED language

def test_a_pagina_declara_o_idioma_que_ela_esta_falando(admin, post):
    """The `lang=` of `<html>` follows the chosen language instead of being fixed.

    It was `<html lang="pt-BR">` hand-written in `base.html`: with the screen in English
    the page still ANNOUNCED itself as Portuguese. Whoever reads that attribute is not the
    person -- it is the screen reader, which picks voice and pronunciation by it, and the
    browser's automatic translation. No route test catches this: the page answers 200 and
    even the visible text is correct.

    Found in the sweep of the LIVE panel, which is the only place where it showed up.
    """
    assert 'lang="pt-BR"' in admin.get("/").get_data(as_text=True)

    assert post(admin, "/account/language", {"lang": "en"}).status_code in (200, 302)
    english = admin.get("/").get_data(as_text=True)
    assert 'lang="en"' in english
    assert 'lang="pt-BR"' not in english
