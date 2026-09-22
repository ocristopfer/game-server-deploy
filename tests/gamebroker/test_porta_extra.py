"""Terceira porta que o broker avisa ao jogo ({EXTRA_PORT}): a "confiavel" do Satisfactory
(-ReliablePort), que ate entao ficava fixa em 8888 e impedia duas instancias no mesmo firewall."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import gamebroker.services.allocator as alocador
import gamebroker.services.catalog as cat
from gamebroker.domain.exceptions import ErroDeValidacao
from gamebroker.runtime.ssh_installer import montar_env

RAIZ = Path(__file__).resolve().parent.parent.parent
FAIXA = range(31000, 31100)


def _valores(env: str) -> dict[str, str]:
    return dict(re.findall(r"^([A-Z_]+)=(.*)$", env, re.M))


@pytest.fixture
def satisfactory():
    jogos, errors = cat.load_curated(RAIZ / "games")
    assert errors == []
    return jogos["satisfactory"]


# --- o Satisfactory de verdade (games/satisfactory.env) ----------------------------------------

def test_satisfactory_declara_a_porta_confiavel_e_pode_andar_de_porta(satisfactory):
    assert satisfactory.extra_port == 8888
    assert satisfactory.shiftable
    assert satisfactory.creatable
    assert "{EXTRA_PORT}" in satisfactory.start_args
    assert cat.Port(8888, "tcp") in satisfactory.ports


def test_satisfactory_recebe_tres_numeros_seguidos_da_faixa_com_o_protocolo_certo(satisfactory):
    ports = alocador.alocar_portas(satisfactory, set(), FAIXA)
    assert [(p.number, p.proto) for p in ports] == [(31000, "udp"), (31000, "tcp"), (31001, "tcp")]
    assert alocador.porta_da_base(ports, 8888) == 31001
    assert alocador.porta_do_papel(ports, alocador.PAPEL_JOGO) == 31000


def test_duas_instancias_do_satisfactory_nao_dividem_a_confiavel(satisfactory):
    primeira = alocador.alocar_portas(satisfactory, set(), FAIXA)
    ocupadas = {p.key for p in primeira}
    segunda = alocador.alocar_portas(satisfactory, ocupadas, FAIXA)
    assert alocador.porta_da_base(segunda, 8888) == 31003
    assert {p.key for p in primeira}.isdisjoint({p.key for p in segunda})


def test_install_env_leva_a_porta_sorteada_e_o_jogo_recebe_o_argumento(satisfactory):
    ports = alocador.alocar_portas(satisfactory, set(), FAIXA)
    v = _valores(montar_env(satisfactory, ports))
    assert v["GAME_PORT"] == "31000"
    assert v["EXTRA_PORT"] == "31001"
    assert "{EXTRA_PORT}" in v["START_ARGS"], "quem troca o marcador e o ct-fases.sh, dentro do CT"


def test_jogo_sem_porta_extra_recebe_extra_zero(dados_de_jogo):
    jogo = cat.validate_dynamic(dados_de_jogo)
    ports = alocador.alocar_portas(jogo, set(), FAIXA)
    assert _valores(montar_env(jogo, ports))["EXTRA_PORT"] == "0"


# --- jogo cadastrado pela API ---------------------------------------------------------------------

@pytest.fixture
def com_extra(dados_de_jogo):
    dados_de_jogo.update(portas=["7777/udp", "27016/udp", "8888/tcp"], porta_extra=8888,
                         start_args="-port={PORT} -queryport={QUERY_PORT} -reliable={EXTRA_PORT}")
    return dados_de_jogo


def test_jogo_com_porta_extra_e_aceito_e_volta_pelo_formato_gravado(com_extra):
    jogo = cat.validate_dynamic(com_extra)
    assert jogo.extra_port == 8888
    assert cat.validate_dynamic(jogo.as_stored()) == jogo


def test_publico_mostra_a_porta_extra(com_extra):
    assert cat.validate_dynamic(com_extra).as_public()["porta_extra"] == 8888


@pytest.mark.parametrize(("mudancas", "campo"), [
    ({"porta_extra": 9999}, "porta_extra"),               # nao esta entre as portas expostas
    ({"porta_extra": 7777}, "porta_extra"),               # igual a porta do jogo
    ({"porta_extra": 27016}, "porta_extra"),              # igual a de consulta
    ({"porta_extra": "8888"}, "porta_extra"),             # tem de ser numero
    ({"start_args": "-port={PORT} -queryport={QUERY_PORT}"}, "deslocavel"),   # falta o marcador
])
def test_porta_extra_invalida_e_recusada(com_extra, mudancas, campo):
    com_extra.update(mudancas)
    with pytest.raises(ErroDeValidacao) as erro:
        cat.validate_dynamic(com_extra)
    assert campo in str(erro.value)


def test_marcador_extra_sem_porta_extra_e_recusado(dados_de_jogo):
    """Sem porta extra o marcador viraria "0" na linha de comando do jogo."""
    dados_de_jogo["start_args"] = "-port={PORT} -queryport={QUERY_PORT} -x={EXTRA_PORT}"
    with pytest.raises(ErroDeValidacao, match="EXTRA_PORT"):
        cat.validate_dynamic(dados_de_jogo)


def test_quarta_porta_continua_recusada_para_jogo_que_anda_de_porta(com_extra):
    com_extra["portas"] = ["7777/udp", "27016/udp", "8888/tcp", "9999/udp"]
    with pytest.raises(ErroDeValidacao, match="mais portas"):
        cat.validate_dynamic(com_extra)


def test_jogo_fixo_pode_ter_porta_extra_sem_andar_de_porta(com_extra):
    com_extra["deslocavel"] = False
    ports = alocador.alocar_portas(cat.validate_dynamic(com_extra), set(), FAIXA)
    assert [p.number for p in ports] == [7777, 27016, 8888]


# --- .env curado --------------------------------------------------------------------------------------

def test_env_curado_com_marcador_extra_e_sem_porta_extra_vira_erro_do_catalogo(tmp_path):
    (tmp_path / "ruim.env").write_text(
        'GAME_KEY=ruim\nSTEAM_APP_ID=1\nGAME_PORT=7001\nGAME_PORTS="7001/udp"\nSTART_ARGS="-r {EXTRA_PORT}"\n',
        encoding="utf-8")
    jogos, errors = cat.load_curated(tmp_path)
    assert jogos == {}
    assert "EXTRA_PORT" in errors[0]


def test_env_curado_deslocavel_com_porta_extra_exige_o_marcador(tmp_path):
    (tmp_path / "ruim.env").write_text(
        'GAME_KEY=ruim\nSTEAM_APP_ID=1\nGAME_PORT=7001\nGAME_PORTS="7001/udp 7002/tcp"\n'
        'EXTRA_PORT=7002\nSTART_ARGS="-p {PORT}"\nPORTS_SHIFTABLE=1\n', encoding="utf-8")
    _, errors = cat.load_curated(tmp_path)
    assert "{EXTRA_PORT}" in errors[0]
