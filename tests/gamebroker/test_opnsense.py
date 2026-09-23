"""Backend OPNsense: leitura de portas ocupadas (aliases!) e abrir/fechar redirects."""
from __future__ import annotations

import pytest
from fake_http import FakeServer, alias_summary

from gamebroker.integrations.http_client import Client
from gamebroker.runtime.opnsense import Opnsense, OpnsenseError, ReadError, busy_ports, instance_description
from gamebroker.services.allocator import AllocatedPort

PORTAS = [AllocatedPort(7001, 7001, "udp", "jogo"), AllocatedPort(7002, 7002, "udp", "query")]


def _line(**campos):
    base = {"uuid": "u", "descr": "x", "interface": "wan", "protocol": "udp", "destination.port": "1234"}
    return {**base, **campos}


# --- leitura de portas ocupadas (o parser que decide se uma porta esta livre) ------------------

def test_porta_numerica_simples():
    assert busy_ports([_line(protocol="tcp", **{"destination.port": "7660"})], "wan") == {(7660, "tcp")}


def test_alias_do_jeito_que_o_opnsense_de_verdade_devolve():
    """Formato copiado do d_nat/search_rule real (regra 'palworld')."""
    summary = ("<strong>UDP -> 192.168.2.21 (CT 211). 8211 jogo, 27015 query A2S (mapear 1:1). "
              "NAO inclua a REST 8212/tcp nem o RCON 25575/tcp.</strong><br/>8211<br/>27015")
    rule = _line(**{"destination.port": "JOGO_PALWORLD",
                      "alias_meta_destination.port": [{"value": "JOGO_PALWORLD", "isAlias": True, "summary": summary}]})
    assert busy_ports([rule], "wan") == {(8211, "udp"), (27015, "udp")}


def test_descricao_do_alias_com_numeros_nao_vira_porta():
    """A descricao cita 8212/tcp e 25575/tcp so como aviso: nao sao portas do alias."""
    summary = alias_summary("nao inclua 8212 nem 25575", ["8211"])
    rule = _line(**{"destination.port": "A", "alias_meta_destination.port": [{"summary": summary}]})
    assert busy_ports([rule], "wan") == {(8211, "udp")}


def test_alias_com_varias_portas_e_faixa():
    summary = alias_summary("dayz", ["2302", "2303", "2304", "27016", "30000-30002"])
    rule = _line(**{"destination.port": "JOGO_DayZ", "alias_meta_destination.port": [{"summary": summary}]})
    assert {p for p, _ in busy_ports([rule], "wan")} == {2302, 2303, 2304, 27016, 30000, 30001, 30002}


def test_alias_sem_descricao():
    rule = _line(**{"destination.port": "A", "alias_meta_destination.port": [{"summary": "8211<br/>27015"}]})
    assert {p for p, _ in busy_ports([rule], "wan")} == {8211, 27015}


@pytest.mark.parametrize("protocolo", ["tcp/udp", "TCP/UDP", "any", "", "icmp"])
def test_protocolo_combinado_ou_desconhecido_ocupa_tcp_e_udp(protocolo):
    taken = busy_ports([_line(protocol=protocolo, **{"destination.port": "7787"})], "wan")
    assert taken == {(7787, "tcp"), (7787, "udp")}


def test_regra_desativada_continua_ocupando():
    assert busy_ports([_line(disabled="1", **{"destination.port": "7001"})], "wan") == {(7001, "udp")}


def test_so_conta_a_interface_wan():
    lan = _line(interface="lan", **{"destination.port": "53"})
    wan = _line(interface="WAN", **{"destination.port": "7001"})
    assert busy_ports([lan, wan], "wan") == {(7001, "udp")}


def test_regra_sem_porta_de_destino_e_ignorada():
    assert busy_ports([_line(**{"destination.port": ""})], "wan") == set()


@pytest.mark.parametrize("porta", ["0", "65536", "99999", "8000-7000", "1-999999", "a-b"])
def test_porta_fora_do_intervalo_e_erro_e_nao_livre(porta):
    with pytest.raises(ReadError):
        busy_ports([_line(**{"destination.port": porta})], "wan")


@pytest.mark.parametrize("meta", [None, [], "texto", [{"summary": None}], [{"value": "A"}],
                                  [{"summary": "<strong>so descricao</strong>"}],
                                  [{"summary": alias_summary("x", ["8211", "OUTRO_ALIAS"])}],
                                  [{"summary": alias_summary("x", ["8211", "rm -rf"])}]])
def test_alias_que_nao_entendo_faz_o_broker_recusar(meta):
    """Falha FECHADA: na duvida o broker nao abre porta nova (nunca supoe que esta livre)."""
    rule = _line(**{"destination.port": "ALIAS_ESTRANHO", "alias_meta_destination.port": meta})
    with pytest.raises(ReadError, match="regra"):
        busy_ports([rule], "wan")


def test_resposta_sem_lista_de_regras():
    with pytest.raises(ReadError):
        busy_ports({"rows": []}, "wan")


def test_faixa_gigante_e_erro():
    with pytest.raises(ReadError):
        busy_ports([_line(**{"destination.port": "1000-60000"})], "wan")


# --- backend contra o OPNsense falso ---------------------------------------------------------------

def test_portas_externas_via_http_inclui_aliases_e_desativadas(opn):
    opn.fake.existing_rule("palworld", "JOGO_PALWORLD", alias=["8211", "27015"], desativada=True)
    opn.fake.existing_rule("team-speak", "9987", protocolo="udp")
    assert opn.backend.external_ports() == {(8211, "udp"), (27015, "udp"), (9987, "udp")}


def test_abrir_cria_uma_regra_por_porta_e_aplica(opn):
    opn.backend.open_ports(300, "10.0.0.30", PORTAS)
    rules = list(opn.fake.regras.values())
    assert sorted((r["destination.port"], r["protocol"]) for r in rules) == [("7001", "udp"), ("7002", "udp")]
    assert {r["descr"] for r in rules} == {"gamepanel:300"}
    assert {r["target"] for r in rules} == {"10.0.0.30"}
    assert {r["interface"] for r in rules} == {"wan"}
    assert {r["pass"] for r in rules} == {"pass"}, "sem pass o WAN barra o pacote"
    assert {r["disabled"] for r in rules} == {"0"}
    assert opn.fake.aplicacoes == 1


def test_abrir_duas_vezes_nao_duplica(opn):
    opn.backend.open_ports(300, "10.0.0.30", PORTAS)
    opn.backend.open_ports(300, "10.0.0.30", PORTAS)
    assert len(opn.fake.regras) == 2


def test_fechar_apaga_so_as_regras_da_instancia(opn):
    opn.fake.existing_rule("team-speak", "9987")
    opn.fake.existing_rule("", "2222", protocolo="tcp")
    opn.backend.open_ports(300, "10.0.0.30", PORTAS)
    opn.backend.open_ports(301, "10.0.0.31", [AllocatedPort(8001, 8001, "udp", "jogo")])
    opn.backend.close_ports(300)
    remaining = sorted(r["descr"] for r in opn.fake.regras.values())
    assert remaining == ["", "gamepanel:301", "team-speak"]


def test_fechar_sem_regras_nao_aplica_nada(opn):
    opn.backend.close_ports(300)
    assert opn.fake.aplicacoes == 0


def test_fechar_nao_confunde_ctid_que_e_prefixo_de_outro(opn):
    opn.backend.open_ports(30, "10.0.0.30", [AllocatedPort(7001, 7001, "udp", "jogo")])
    opn.backend.open_ports(300, "10.0.0.31", [AllocatedPort(8001, 8001, "udp", "jogo")])
    opn.backend.close_ports(30)
    assert [r["descr"] for r in opn.fake.regras.values()] == ["gamepanel:300"]


def test_falha_no_meio_desfaz_o_que_ja_criou(opn):
    opn.fake.falhar_no_add_numero = 2
    with pytest.raises(OpnsenseError, match="rule.target"):
        opn.backend.open_ports(300, "10.0.0.30", PORTAS)
    assert opn.fake.regras == {}


def test_apply_sem_privilegio_desfaz_e_avisa(opn):
    opn.fake.apply_permitido = False
    with pytest.raises(OpnsenseError, match="HTTP 403"):
        opn.backend.open_ports(300, "10.0.0.30", PORTAS)
    assert opn.fake.regras == {}


@pytest.mark.parametrize("ip", ["10.0.0.300", "nao-e-ip", "10.0.0.30; drop", ""])
def test_ip_invalido_nunca_chega_ao_opnsense(opn, ip):
    with pytest.raises(ValueError):
        opn.backend.open_ports(300, ip, PORTAS)
    assert opn.server.requisicoes == []


@pytest.mark.parametrize("porta", [AllocatedPort(1, 0, "udp", "x"), AllocatedPort(1, 70000, "udp", "x"),
                                   AllocatedPort(1, 80, "icmp", "x")])
def test_porta_invalida_e_recusada(opn, porta):
    with pytest.raises(OpnsenseError, match="porta invalida"):
        opn.backend.open_ports(300, "10.0.0.30", [porta])
    assert opn.fake.regras == {}


def test_credencial_errada_e_erro_sem_segredo(opn):
    opn.backend._c = Client(opn.server.url, {"Authorization": "Basic segredo-errado"})
    with pytest.raises(OpnsenseError) as error:
        opn.backend.external_ports()
    assert "HTTP 401" in str(error.value)
    assert "segredo-errado" not in str(error.value)


def test_acessivel(opn):
    assert opn.backend.reachable() is True
    opn.server.stop()
    assert opn.backend.reachable() is False


def test_interface_invalida():
    with pytest.raises(ValueError):
        Opnsense(Client("http://127.0.0.1:1", {}), "wan; rm")


def test_descricao_usa_so_inteiro():
    assert instance_description(300) == "gamepanel:300"
    with pytest.raises(ValueError):
        instance_description("300; drop")  # type: ignore[arg-type]


def test_servidor_que_responde_lixo_no_apply():
    def handler(metodo, caminho, *_):
        if caminho.endswith("search_rule"):
            return 200, {"rows": []}
        if caminho.endswith("add_rule"):
            return 200, {"result": "saved", "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
        if "del_rule" in caminho:
            return 200, {"result": "deleted"}
        return 200, {"status": "ERRO interno"}

    server = FakeServer(handler)
    try:
        backend = Opnsense(Client(server.url, {}), "wan")
        with pytest.raises(OpnsenseError, match="nao confirmou"):
            backend.open_ports(300, "10.0.0.30", PORTAS)
    finally:
        server.stop()


def test_sonda_de_saude_nao_espera_o_prazo_inteiro(monkeypatch):
    import time

    import gamebroker.runtime.opnsense as modulo
    monkeypatch.setattr(modulo, "SONDA_TIMEOUT", 0.3)
    server = FakeServer(lambda *_a: (time.sleep(1.5), (200, {"rows": []}))[1])
    try:
        backend = Opnsense(Client(server.url, {}, timeout=30), "wan")
        start_at = time.monotonic()
        assert backend.reachable() is False
        assert time.monotonic() - start_at < 1.2
    finally:
        server.stop()
