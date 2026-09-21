"""Backend OPNsense: leitura de portas ocupadas (aliases!) e abrir/fechar redirects."""
from __future__ import annotations

import pytest

from broker.alocador import PortaAlocada
from broker.conexao import Cliente
from broker.http_falso import ServidorFalso, resumo_de_alias
from broker.opnsense import (ErroDeLeitura, ErroDoOpnsense, Opnsense, descricao_da_instancia,
                             portas_ocupadas)

PORTAS = [PortaAlocada(7001, 7001, "udp", "jogo"), PortaAlocada(7002, 7002, "udp", "query")]


def _linha(**campos):
    base = {"uuid": "u", "descr": "x", "interface": "wan", "protocol": "udp", "destination.port": "1234"}
    return {**base, **campos}


# --- leitura de portas ocupadas (o parser que decide se uma porta esta livre) ------------------

def test_porta_numerica_simples():
    assert portas_ocupadas([_linha(protocol="tcp", **{"destination.port": "7660"})], "wan") == {(7660, "tcp")}


def test_alias_do_jeito_que_o_opnsense_de_verdade_devolve():
    """Formato copiado do d_nat/search_rule real (regra 'palworld')."""
    resumo = ("<strong>UDP -> 192.168.2.21 (CT 211). 8211 jogo, 27015 query A2S (mapear 1:1). "
              "NAO inclua a REST 8212/tcp nem o RCON 25575/tcp.</strong><br/>8211<br/>27015")
    regra = _linha(**{"destination.port": "JOGO_PALWORLD",
                      "alias_meta_destination.port": [{"value": "JOGO_PALWORLD", "isAlias": True, "summary": resumo}]})
    assert portas_ocupadas([regra], "wan") == {(8211, "udp"), (27015, "udp")}


def test_descricao_do_alias_com_numeros_nao_vira_porta():
    """A descricao cita 8212/tcp e 25575/tcp so como aviso: nao sao portas do alias."""
    resumo = resumo_de_alias("nao inclua 8212 nem 25575", ["8211"])
    regra = _linha(**{"destination.port": "A", "alias_meta_destination.port": [{"summary": resumo}]})
    assert portas_ocupadas([regra], "wan") == {(8211, "udp")}


def test_alias_com_varias_portas_e_faixa():
    resumo = resumo_de_alias("dayz", ["2302", "2303", "2304", "27016", "30000-30002"])
    regra = _linha(**{"destination.port": "JOGO_DayZ", "alias_meta_destination.port": [{"summary": resumo}]})
    assert {p for p, _ in portas_ocupadas([regra], "wan")} == {2302, 2303, 2304, 27016, 30000, 30001, 30002}


def test_alias_sem_descricao():
    regra = _linha(**{"destination.port": "A", "alias_meta_destination.port": [{"summary": "8211<br/>27015"}]})
    assert {p for p, _ in portas_ocupadas([regra], "wan")} == {8211, 27015}


@pytest.mark.parametrize("protocolo", ["tcp/udp", "TCP/UDP", "any", "", "icmp"])
def test_protocolo_combinado_ou_desconhecido_ocupa_tcp_e_udp(protocolo):
    ocupadas = portas_ocupadas([_linha(protocol=protocolo, **{"destination.port": "7787"})], "wan")
    assert ocupadas == {(7787, "tcp"), (7787, "udp")}


def test_regra_desativada_continua_ocupando():
    assert portas_ocupadas([_linha(disabled="1", **{"destination.port": "7001"})], "wan") == {(7001, "udp")}


def test_so_conta_a_interface_wan():
    lan = _linha(interface="lan", **{"destination.port": "53"})
    wan = _linha(interface="WAN", **{"destination.port": "7001"})
    assert portas_ocupadas([lan, wan], "wan") == {(7001, "udp")}


def test_regra_sem_porta_de_destino_e_ignorada():
    assert portas_ocupadas([_linha(**{"destination.port": ""})], "wan") == set()


@pytest.mark.parametrize("porta", ["0", "65536", "99999", "8000-7000", "1-999999", "a-b"])
def test_porta_fora_do_intervalo_e_erro_e_nao_livre(porta):
    with pytest.raises(ErroDeLeitura):
        portas_ocupadas([_linha(**{"destination.port": porta})], "wan")


@pytest.mark.parametrize("meta", [None, [], "texto", [{"summary": None}], [{"value": "A"}],
                                  [{"summary": "<strong>so descricao</strong>"}],
                                  [{"summary": resumo_de_alias("x", ["8211", "OUTRO_ALIAS"])}],
                                  [{"summary": resumo_de_alias("x", ["8211", "rm -rf"])}]])
def test_alias_que_nao_entendo_faz_o_broker_recusar(meta):
    """Falha FECHADA: na duvida o broker nao abre porta nova (nunca supoe que esta livre)."""
    regra = _linha(**{"destination.port": "ALIAS_ESTRANHO", "alias_meta_destination.port": meta})
    with pytest.raises(ErroDeLeitura, match="regra"):
        portas_ocupadas([regra], "wan")


def test_resposta_sem_lista_de_regras():
    with pytest.raises(ErroDeLeitura):
        portas_ocupadas({"rows": []}, "wan")


def test_faixa_gigante_e_erro():
    with pytest.raises(ErroDeLeitura):
        portas_ocupadas([_linha(**{"destination.port": "1000-60000"})], "wan")


# --- backend contra o OPNsense falso ---------------------------------------------------------------

def test_portas_externas_via_http_inclui_aliases_e_desativadas(opn):
    opn.falso.regra_existente("palworld", "JOGO_PALWORLD", alias=["8211", "27015"], desativada=True)
    opn.falso.regra_existente("team-speak", "9987", protocolo="udp")
    assert opn.backend.portas_externas() == {(8211, "udp"), (27015, "udp"), (9987, "udp")}


def test_abrir_cria_uma_regra_por_porta_e_aplica(opn):
    opn.backend.abrir(300, "10.0.0.30", PORTAS)
    regras = list(opn.falso.regras.values())
    assert sorted((r["destination.port"], r["protocol"]) for r in regras) == [("7001", "udp"), ("7002", "udp")]
    assert {r["descr"] for r in regras} == {"gamepanel:300"}
    assert {r["target"] for r in regras} == {"10.0.0.30"}
    assert {r["interface"] for r in regras} == {"wan"}
    assert {r["pass"] for r in regras} == {"pass"}, "sem pass o WAN barra o pacote"
    assert {r["disabled"] for r in regras} == {"0"}
    assert opn.falso.aplicacoes == 1


def test_abrir_duas_vezes_nao_duplica(opn):
    opn.backend.abrir(300, "10.0.0.30", PORTAS)
    opn.backend.abrir(300, "10.0.0.30", PORTAS)
    assert len(opn.falso.regras) == 2


def test_fechar_apaga_so_as_regras_da_instancia(opn):
    opn.falso.regra_existente("team-speak", "9987")
    opn.falso.regra_existente("", "2222", protocolo="tcp")
    opn.backend.abrir(300, "10.0.0.30", PORTAS)
    opn.backend.abrir(301, "10.0.0.31", [PortaAlocada(8001, 8001, "udp", "jogo")])
    opn.backend.fechar(300)
    restantes = sorted(r["descr"] for r in opn.falso.regras.values())
    assert restantes == ["", "gamepanel:301", "team-speak"]


def test_fechar_sem_regras_nao_aplica_nada(opn):
    opn.backend.fechar(300)
    assert opn.falso.aplicacoes == 0


def test_fechar_nao_confunde_ctid_que_e_prefixo_de_outro(opn):
    opn.backend.abrir(30, "10.0.0.30", [PortaAlocada(7001, 7001, "udp", "jogo")])
    opn.backend.abrir(300, "10.0.0.31", [PortaAlocada(8001, 8001, "udp", "jogo")])
    opn.backend.fechar(30)
    assert [r["descr"] for r in opn.falso.regras.values()] == ["gamepanel:300"]


def test_falha_no_meio_desfaz_o_que_ja_criou(opn):
    opn.falso.falhar_no_add_numero = 2
    with pytest.raises(ErroDoOpnsense, match="rule.target"):
        opn.backend.abrir(300, "10.0.0.30", PORTAS)
    assert opn.falso.regras == {}


def test_apply_sem_privilegio_desfaz_e_avisa(opn):
    opn.falso.apply_permitido = False
    with pytest.raises(ErroDoOpnsense, match="HTTP 403"):
        opn.backend.abrir(300, "10.0.0.30", PORTAS)
    assert opn.falso.regras == {}


@pytest.mark.parametrize("ip", ["10.0.0.300", "nao-e-ip", "10.0.0.30; drop", ""])
def test_ip_invalido_nunca_chega_ao_opnsense(opn, ip):
    with pytest.raises(ValueError):
        opn.backend.abrir(300, ip, PORTAS)
    assert opn.servidor.requisicoes == []


@pytest.mark.parametrize("porta", [PortaAlocada(1, 0, "udp", "x"), PortaAlocada(1, 70000, "udp", "x"),
                                   PortaAlocada(1, 80, "icmp", "x")])
def test_porta_invalida_e_recusada(opn, porta):
    with pytest.raises(ErroDoOpnsense, match="porta invalida"):
        opn.backend.abrir(300, "10.0.0.30", [porta])
    assert opn.falso.regras == {}


def test_credencial_errada_e_erro_sem_segredo(opn):
    opn.backend._c = Cliente(opn.servidor.url, {"Authorization": "Basic segredo-errado"})
    with pytest.raises(ErroDoOpnsense) as erro:
        opn.backend.portas_externas()
    assert "HTTP 401" in str(erro.value)
    assert "segredo-errado" not in str(erro.value)


def test_acessivel(opn):
    assert opn.backend.acessivel() is True
    opn.servidor.parar()
    assert opn.backend.acessivel() is False


def test_interface_invalida():
    with pytest.raises(ValueError):
        Opnsense(Cliente("http://127.0.0.1:1", {}), "wan; rm")


def test_descricao_usa_so_inteiro():
    assert descricao_da_instancia(300) == "gamepanel:300"
    with pytest.raises(ValueError):
        descricao_da_instancia("300; drop")  # type: ignore[arg-type]


def test_servidor_que_responde_lixo_no_apply():
    def tratador(metodo, caminho, *_):
        if caminho.endswith("search_rule"):
            return 200, {"rows": []}
        if caminho.endswith("add_rule"):
            return 200, {"result": "saved", "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
        if "del_rule" in caminho:
            return 200, {"result": "deleted"}
        return 200, {"status": "ERRO interno"}

    servidor = ServidorFalso(tratador)
    try:
        backend = Opnsense(Cliente(servidor.url, {}), "wan")
        with pytest.raises(ErroDoOpnsense, match="nao confirmou"):
            backend.abrir(300, "10.0.0.30", PORTAS)
    finally:
        servidor.parar()
