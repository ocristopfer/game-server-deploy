"""Allocator: CTID, IP and ports picked based on what is already taken."""
from __future__ import annotations

import pytest

import gamebroker.services.allocator as alocador
from gamebroker.domain.exceptions import OutOfResources
from gamebroker.services.catalog import validate_dynamic


def _game(game_data, **changes):
    game_data.update(changes)
    return validate_dynamic(game_data)


def test_ctid_pula_os_usados():
    assert alocador.pick_ctid(range(300, 305), {300, 301}) == 302


def test_ctid_esgotado():
    with pytest.raises(OutOfResources, match="CTID"):
        alocador.pick_ctid(range(300, 302), {300, 301})


def test_ip_pula_usados_e_quem_responde_na_rede():
    candidates = ("10.0.0.30", "10.0.0.31", "10.0.0.32")
    ip = alocador.pick_ip(candidates, {"10.0.0.30"}, lambda ip: ip == "10.0.0.31")
    assert ip == "10.0.0.32"


def test_ip_esgotado():
    with pytest.raises(OutOfResources, match="IP"):
        alocador.pick_ip(("10.0.0.30",), set(), lambda _ip: True)


def test_faixa_de_ips_valida():
    assert alocador.ips_in_range("10.20.1", 30, 32) == ("10.20.1.30", "10.20.1.31", "10.20.1.32")


@pytest.mark.parametrize(("prefix", "start", "end"), [
    ("10.20.1", 0, 5), ("10.20.1", 9, 3), ("10.20.1", 1, 255), ("nao-ip", 1, 5)])
def test_faixa_de_ips_invalida(prefix, start, end):
    with pytest.raises(ValueError):
        alocador.ips_in_range(prefix, start, end)


FAIXA = range(31000, 31010)


def test_ctid_acompanha_o_ultimo_numero_do_ip():
    ip, ctid = alocador.pick_ip_and_ctid(("10.0.0.102", "10.0.0.103"), 200, set(), set(), lambda _ip: False)
    assert (ip, ctid) == ("10.0.0.102", 302)


def test_ip_e_pulado_se_o_ctid_dele_esta_ocupado():
    # CTID 302 exists (created by hand): .102 is unusable, even with the IP free.
    ip, ctid = alocador.pick_ip_and_ctid(("10.0.0.102", "10.0.0.103"), 200, {302}, set(), lambda _ip: False)
    assert (ip, ctid) == ("10.0.0.103", 303)


def test_ip_e_ctid_pulam_ip_usado_e_quem_responde():
    candidates = ("10.0.0.102", "10.0.0.103", "10.0.0.104")
    ip, ctid = alocador.pick_ip_and_ctid(candidates, 200, set(), {"10.0.0.102"}, lambda ip: ip == "10.0.0.103")
    assert (ip, ctid) == ("10.0.0.104", 304)


def test_ip_e_ctid_esgotados():
    with pytest.raises(OutOfResources, match="IP/CTID"):
        alocador.pick_ip_and_ctid(("10.0.0.102",), 200, {302}, set(), lambda _ip: False)


def test_jogo_fixo_usa_as_portas_padrao_e_ganha_papel(game_data):
    ports = alocador.allocate_ports(_game(game_data, shiftable=False), set(), FAIXA)
    assert [(p.number, p.proto, p.role) for p in ports] == [
        (7777, "udp", "jogo"), (27016, "udp", "query")]


def test_jogo_fixo_com_porta_ocupada_e_recusado(game_data):
    game = _game(game_data, shiftable=False)
    with pytest.raises(OutOfResources, match=r"27016/udp.*nao aceita mudar"):
        alocador.allocate_ports(game, {(27016, "udp")}, FAIXA)


def test_jogo_deslocavel_ignora_as_portas_padrao_e_usa_a_faixa(game_data):
    # The default ports are not even taken: the game still moves to the broker's range.
    ports = alocador.allocate_ports(_game(game_data, shiftable=True), set(), FAIXA)
    assert [(p.number, p.role) for p in ports] == [(31000, "jogo"), (31001, "query")]
    assert [p.base for p in ports] == [7777, 27016]


def test_jogo_deslocavel_pega_o_primeiro_bloco_inteiro_livre(game_data):
    taken = {(31000, "udp"), (31003, "udp")}
    ports = alocador.allocate_ports(_game(game_data, shiftable=True), taken, FAIXA)
    assert [p.number for p in ports] == [31001, 31002]


def test_mesma_porta_em_udp_e_tcp_fica_com_o_mesmo_numero(game_data):
    game = _game(game_data, ports=["7777/udp", "7777/tcp"], query_port=0, shiftable=True,
                 start_args="-port={PORT}")
    ports = alocador.allocate_ports(game, set(), FAIXA)
    assert [(p.number, p.proto) for p in ports] == [(31000, "udp"), (31000, "tcp")]


def test_faixa_cheia_e_recusada_com_a_faixa_na_mensagem(game_data):
    taken = {(n, "udp") for n in FAIXA}
    with pytest.raises(OutOfResources, match=r"31000-31009.*cheia"):
        alocador.allocate_ports(_game(game_data, shiftable=True), taken, FAIXA)


def test_bloco_nao_atravessa_o_fim_da_faixa(game_data):
    # Only the last port of the range is left: a two-port block does not fit.
    taken = {(n, "udp") for n in range(31000, 31009)}
    with pytest.raises(OutOfResources, match="cheia"):
        alocador.allocate_ports(_game(game_data, shiftable=True), taken, FAIXA)


def test_protocolo_diferente_nao_conflita(game_data):
    ports = alocador.allocate_ports(_game(game_data, shiftable=False), {(7777, "tcp")}, FAIXA)
    assert ports[0].number == 7777


def test_porta_do_papel(game_data):
    ports = alocador.allocate_ports(_game(game_data), set(), FAIXA)
    assert alocador.port_with_role(ports, alocador.ROLE_GAME) == 31000
    assert alocador.port_with_role(ports, alocador.ROLE_QUERY) == 31001
    assert alocador.port_with_role(ports, "inexistente") == 0
