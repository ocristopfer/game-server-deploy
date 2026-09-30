"""Gestor de mods: leitura dos server_packages do ETS2, IDs da Workshop e perfil por jogo."""
from __future__ import annotations

from gamepanel.games.mods import ets2, profiles, workshop

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
        assert p.folder.startswith("/opt/game/")
        assert p.kind in (profiles.KIND_PACKAGES, profiles.KIND_FOLDER)
        assert bool(p.upload_names) != bool(p.extensions), p.key
