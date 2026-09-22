"""Mapa da interface (ui.py): quem ve o que na barra larga, e o que acende em cada rota."""
from __future__ import annotations

from gamepanel import navigation as ui


def _chaves(itens):
    return [i.chave for i in itens]


def test_admin_com_broker_ve_tudo_na_barra_larga():
    barra, conta = ui.nav_desktop(admin=True, broker=True)
    assert _chaves(barra) == ["servidores", "instancias", "catalogo", "historico", "alertas", "usuarios"]
    assert _chaves(conta) == ["conta", "ssh"]


def test_sem_broker_a_barra_nao_oferece_link_que_da_403():
    barra, _ = ui.nav_desktop(admin=True, broker=False)
    assert not {"instancias", "catalogo"} & set(_chaves(barra))


def test_operador_so_ve_o_que_pode_abrir():
    barra, conta = ui.nav_desktop(admin=False, broker=True)
    assert _chaves(barra) == ["servidores", "historico"]
    assert _chaves(conta) == ["conta", "ssh"]


def test_toda_chave_da_barra_larga_existe_nas_listas_de_itens():
    """Uma chave digitada errada em NAV_DESKTOP_* explodiria so em runtime, na primeira pagina."""
    for chave in ui.NAV_DESKTOP_BARRA + ui.NAV_DESKTOP_CONTA:
        assert chave in ui._TODOS_OS_ITENS


def test_no_desktop_cada_destino_acende_o_proprio_item():
    assert ui.nav_ativa_desktop_de("instances_list") == "instancias"
    assert ui.nav_ativa_desktop_de("catalog_new") == "catalogo"
    assert ui.nav_ativa_desktop_de("users_list") == "usuarios"
    assert ui.nav_ativa_desktop_de("ssh_key") == "ssh"
    assert ui.nav_ativa_desktop_de("account") == "conta"


def test_no_celular_a_aba_de_cima_continua_acesa():
    """So ha quatro abas embaixo: 'Instancias' acende 'Servidores' e 'Usuarios' acende 'Conta'."""
    assert ui.nav_ativa_de("instances_list") == "servidores"
    assert ui.nav_ativa_de("users_list") == "conta"


def test_tela_de_servidor_acende_servidores_nos_dois():
    assert ui.nav_ativa_desktop_de("server_detail") == "servidores"
    assert ui.nav_ativa_desktop_de("history") == "historico"
    assert ui.nav_ativa_desktop_de("rota_que_nao_existe") == ""


def test_barra_larga_usa_rotulo_curto_quando_ha(chefe, monkeypatch):
    import app as panel
    monkeypatch.setattr(panel, "ALLOW_BROKER", True)
    html = chefe.get("/").get_data(as_text=True)
    inicio = html.index('class="appbar__nav"')
    barra = html[inicio:html.index("</nav>", inicio)]
    assert ">Instancias</a>" in barra
    assert ">Catalogo</a>" in barra
    assert "Instancias de jogo" not in barra
