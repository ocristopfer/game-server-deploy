"""Gestor de mods: leitura dos server_packages do ETS2, IDs da Workshop e perfil por jogo."""
from __future__ import annotations

import pytest

from gamepanel.games.mods import ets2, profiles, thunderstore, workshop

# Trecho no formato real de um server_packages.sii exportado pelo ETS2 1.61 (o de um servidor
# com o Mapa BR e mods da Workshop).
PACKAGES = """﻿SiiNunit
{
server_packages_info : _nameless.1fe.9af2.f648 {
 version: 1
 dlc_essential_list: 0
 dlc_non_essential_list: 2
 dlc_non_essential_list[0]: 2583912098162477
 dlc_non_essential_list[1]: 5557801920893741
 mod_list: 3
 mod_list[0]: _nameless.1fe.c082.cd88
 mod_list[1]: _nameless.1fe.c082.c808
 mod_list[2]: _nameless.1fe.c082.c908
 map_name: "/map/brbrasil.mbd"
}

server_mod_detail : _nameless.1fe.c082.cd88 {
 package_name: "Mapa_BR_Brasil_6.1_ETS2_1.61.1.0"
 mod_name: " Mapa BR Brasil 6.1"
 mod_id: 12305197553815356583
 workshop_mod: false
 optional_mod: false
}

server_mod_detail : _nameless.1fe.c082.c808 {
 package_name: "mod_workshop_package.00000000C4089C7D"
 mod_name: "Scania L6 Straight pipe "
 mod_id: 3288898685
 workshop_mod: true
 optional_mod: true
}

server_mod_detail : _nameless.1fe.c082.c908 {
 package_name: "mod_workshop_package.00000000DA084B17"
 mod_name: "Moeda Brasileira v1.60"
 workshop_mod: true
 optional_mod: false
}

}
"""


def test_le_mapa_dlcs_e_mods_dos_pacotes():
    pkgs = ets2.parse(PACKAGES)
    assert pkgs.map_name == "/map/brbrasil.mbd"
    assert pkgs.dlc_count == 2
    assert [m.name for m in pkgs.mods] == ["Mapa BR Brasil 6.1", "Scania L6 Straight pipe",
                                           "Moeda Brasileira v1.60"]


def test_mod_manual_nao_vira_link_da_workshop():
    """O mod_id de um mod instalado a mao e assinatura interna: virar link apontaria para
    um item qualquer da Workshop."""
    mapa = ets2.parse(PACKAGES).mods[0]
    assert mapa.workshop_id == 0


def test_id_da_workshop_vem_do_mod_id_ou_do_hexadecimal_do_pacote():
    mods = ets2.parse(PACKAGES).mods
    assert mods[1].workshop_id == 3288898685
    # 0xDA084B17, o hexadecimal do package_name, e o 3657976599 da lista dos jogadores.
    assert mods[2].workshop_id == 3657976599
    assert ets2.parse(PACKAGES).workshop_ids == [3288898685, 3657976599]


def test_opcional_e_marcado():
    assert [m.optional for m in ets2.parse(PACKAGES).mods] == [False, True, False]


def test_arquivo_vazio_ou_estranho_nao_derruba():
    assert ets2.parse("").mods == ()
    assert ets2.parse("isto nao e um sii {{{").mods == ()


def test_lista_colada_do_chat_vira_ids():
    chat = """[14:48]DIM300 [GD], : https://steamcommunity.com/sharedfiles/filedetails/?id=3132251325
[14:48]DIM300 [GD], : https://steamcommunity.com/sharedfiles/filedetails/?id=3288898685
645553604
[14:55] versao 1.61 as 22:10
https://steamcommunity.com/sharedfiles/filedetails/?id=3132251325"""
    assert workshop.parse_ids(chat) == [3132251325, 3288898685, 645553604]


def test_numero_curto_da_conversa_nao_e_id():
    assert workshop.parse_ids("1234\n14:48\n1.61") == []


def test_teto_de_ids():
    many = "\n".join(str(1_000_000 + i) for i in range(workshop.MAX_IDS + 50))
    assert len(workshop.parse_ids(many)) == workshop.MAX_IDS


def test_link_da_workshop():
    assert workshop.url(645553604) == "https://steamcommunity.com/sharedfiles/filedetails/?id=645553604"


def test_perfil_pelo_nome_do_servico():
    assert profiles.profile_for("ets2.service") is profiles.ETS2
    assert profiles.profile_for("euro-truck-simulator-2.service") is profiles.ETS2
    assert profiles.profile_for("palworld.service") is profiles.PALWORLD
    assert profiles.profile_for("valheim.service") is None
    assert profiles.profile_for("") is None


def test_dois_perfis_nao_disputam_o_mesmo_servico():
    services = [s for p in profiles.PROFILES for s in p.services]
    assert len(services) == len(set(services))


def test_ets2_so_aceita_os_dois_pacotes():
    assert profiles.ETS2.accepts("server_packages.sii")
    assert profiles.ETS2.accepts("server_packages.dat")
    assert not profiles.ETS2.accepts("mapa_br.scs")
    assert not profiles.ETS2.accepts("../server_packages.sii")


def test_palworld_aceita_pak_em_qualquer_caixa():
    assert profiles.PALWORLD.accepts("MeuMod_P.pak")
    assert profiles.PALWORLD.accepts("MEUMOD.PAK")
    assert not profiles.PALWORLD.accepts("script.sh")


def test_todo_perfil_diz_para_onde_vai_e_o_que_aceita():
    for p in profiles.PROFILES:
        assert p.folder == "/opt/game" or p.folder.startswith("/opt/game/")
        assert p.kind in (profiles.KIND_PACKAGES, profiles.KIND_FOLDER, profiles.KIND_THUNDERSTORE,
                          profiles.KIND_SHROUDTOPIA, profiles.KIND_GUIDE)
        # Toda tela de mods diz onde procurar: era a pergunta que ficava sem resposta.
        assert p.sources, p.key
        if p.kind == profiles.KIND_GUIDE:
            assert not p.upload_names and not p.extensions, p.key
            continue
        if p.kind == profiles.KIND_THUNDERSTORE:
            # Nada entra por envio: o CT baixa do Thunderstore.
            assert not p.upload_names and not p.extensions, p.key
            assert p.community and all(p.loader) and p.min_memory_mb, p.key
        else:
            assert bool(p.upload_names) != bool(p.extensions), p.key


def test_v_rising_usa_o_thunderstore_com_a_memoria_medida():
    vr = profiles.profile_for("vrising.service")
    assert vr is profiles.VRISING
    assert vr.loader == ("BepInEx", "BepInExPack_V_Rising")
    assert vr.min_memory_mb >= 9500, "medido: 9,4 GB na primeira subida com o BepInEx"
    assert not vr.accepts("plugin.dll")


@pytest.mark.parametrize(("text", "expected"), [
    ("https://thunderstore.io/c/v-rising/p/deca/VampireCommandFramework/", ("deca", "VampireCommandFramework", "")),
    ("https://thunderstore.io/c/v-rising/p/odjit/KindredCommands/versions/", ("odjit", "KindredCommands", "")),
    ("https://thunderstore.io/package/download/deca/VampireCommandFramework/0.11.0/",
     ("deca", "VampireCommandFramework", "0.11.0")),
    ("https://thunderstore.io/c/v-rising/p/deca/VampireCommandFramework/v/0.10.4/",
     ("deca", "VampireCommandFramework", "0.10.4")),
    ("deca/VampireCommandFramework", ("deca", "VampireCommandFramework", "")),
    ("deca-VampireCommandFramework-0.11.0", ("deca", "VampireCommandFramework", "0.11.0")),
    ("  deca-VampireCommandFramework  ", ("deca", "VampireCommandFramework", "")),
])
def test_pacote_colado_de_varios_jeitos(text, expected):
    assert thunderstore.parse_package(text) == expected


@pytest.mark.parametrize("text", ["", "deca", "../x/y", "deca/Vampire Command", "https://evil.example/p/a/b/",
                                  "deca/x;rm -rf", "a/b/c"])
def test_pacote_irreconhecivel_nao_vira_nada(text):
    assert thunderstore.parse_package(text) is None


@pytest.mark.parametrize(("text", "expected"), [
    ("", ""), ("  ", ""), ("1.2.3", "1.2.3"), (" v0.11.0 ", "0.11.0"),
    ("1.2", None), ("1.2.3.4", None), ("latest", None), ("1.2.3/../x", None), ("1.2.3;rm", None),
])
def test_versao_do_formulario(text, expected):
    """Vazio = a mais nova; o que nao e x.y.z nao chega ao CT (vira parte de uma URL la)."""
    assert thunderstore.parse_version(text) == expected


def test_pasta_do_plugin_volta_a_ns_e_nome():
    assert thunderstore.split_dir("deca-VampireCommandFramework") == ("deca", "VampireCommandFramework")
    assert thunderstore.split_dir("../../etc") is None
    assert thunderstore.split_dir("deca-VampireCommandFramework-0.11.0") is None, "pasta nao leva versao"
    assert thunderstore.package_url("v-rising", "deca", "VampireCommandFramework") ==         "https://thunderstore.io/c/v-rising/p/deca/VampireCommandFramework/"


def test_dragonwilds_aceita_os_tres_arquivos_do_mod_da_unreal_5():
    dw = profiles.profile_for("dragonwilds.service")
    assert dw is profiles.DRAGONWILDS
    assert dw.folder == "/opt/game/RSDragonwilds/Content/Paks/~mods"
    for name in ("MeuMod_P.pak", "MeuMod_P.utoc", "MeuMod_P.ucas"):
        assert dw.accepts(name)
    assert not dw.accepts("dwmapi.dll"), "UE4SS nao roda no servidor dedicado"


def test_enshrouded_usa_o_shroudtopia_provado_no_ct():
    """Provado no CT 303 sob o Proton: o carregador sobe e carrega a DLL de mods/."""
    en = profiles.profile_for("enshrouded.service")
    assert en.kind == profiles.KIND_SHROUDTOPIA
    assert en.folder == "/opt/game/mods"
    assert en.accepts("flight_mod.dll")
    # O carregador entra pelo botao, nunca por envio: um winmm.dll qualquer na pasta de mods
    # nao faria nada, e um na pasta do jogo trocaria o que o Wine carrega.
    assert not en.accepts("shroudtopia.json")


def test_nexus_e_so_link_nunca_download():
    """A API do Nexus so entrega arquivo para conta Premium, e automatizar sem ela viola os
    termos: nenhum perfil pode depender de baixar de la."""
    for p in profiles.PROFILES:
        for _, url in p.sources:
            assert url.startswith("https://")
            assert "/api/" not in url
