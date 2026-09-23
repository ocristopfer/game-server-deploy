"""Terceira porta que o broker avisa ao jogo ({EXTRA_PORT}): a "confiavel" do Satisfactory
(-ReliablePort), que ate entao ficava fixa em 8888 e impedia duas instancias no mesmo firewall."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import gamebroker.services.allocator as alocador
import gamebroker.services.catalog as cat
from gamebroker.domain.exceptions import ValidationError
from gamebroker.runtime.ssh_installer import build_env

RAIZ = Path(__file__).resolve().parents[3]
FAIXA = range(31000, 31100)


def _values(env: str) -> dict[str, str]:
    return dict(re.findall(r"^([A-Z_]+)=(.*)$", env, re.M))


@pytest.fixture
def satisfactory():
    games, errors = cat.load_curated(RAIZ / "games")
    assert errors == []
    return games["satisfactory"]


# --- o Satisfactory de verdade (games/satisfactory.env) ----------------------------------------

def test_satisfactory_declara_a_porta_confiavel_e_pode_andar_de_porta(satisfactory):
    assert satisfactory.extra_port == 8888
    assert satisfactory.shiftable
    assert satisfactory.creatable
    assert "{EXTRA_PORT}" in satisfactory.start_args
    assert cat.Port(8888, "tcp") in satisfactory.ports


def test_satisfactory_recebe_tres_numeros_seguidos_da_faixa_com_o_protocolo_certo(satisfactory):
    ports = alocador.allocate_ports(satisfactory, set(), FAIXA)
    assert [(p.number, p.proto) for p in ports] == [(31000, "udp"), (31000, "tcp"), (31001, "tcp")]
    assert alocador.port_from_base(ports, 8888) == 31001
    assert alocador.port_with_role(ports, alocador.ROLE_GAME) == 31000


def test_duas_instancias_do_satisfactory_nao_dividem_a_confiavel(satisfactory):
    first_one = alocador.allocate_ports(satisfactory, set(), FAIXA)
    taken = {p.key for p in first_one}
    second_one = alocador.allocate_ports(satisfactory, taken, FAIXA)
    assert alocador.port_from_base(second_one, 8888) == 31003
    assert {p.key for p in first_one}.isdisjoint({p.key for p in second_one})


def test_install_env_leva_a_porta_sorteada_e_o_jogo_recebe_o_argumento(satisfactory):
    ports = alocador.allocate_ports(satisfactory, set(), FAIXA)
    v = _values(build_env(satisfactory, ports))
    assert v["GAME_PORT"] == "31000"
    assert v["EXTRA_PORT"] == "31001"
    assert "{EXTRA_PORT}" in v["START_ARGS"], "quem troca o marcador e o ct-phases.sh, dentro do CT"


def test_jogo_sem_porta_extra_recebe_extra_zero(game_data):
    game = cat.validate_dynamic(game_data)
    ports = alocador.allocate_ports(game, set(), FAIXA)
    assert _values(build_env(game, ports))["EXTRA_PORT"] == "0"


# --- jogo cadastrado pela API ---------------------------------------------------------------------

@pytest.fixture
def with_extra(game_data):
    game_data.update(ports=["7777/udp", "27016/udp", "8888/tcp"], extra_port=8888,
                         start_args="-port={PORT} -queryport={QUERY_PORT} -reliable={EXTRA_PORT}")
    return game_data


def test_jogo_com_porta_extra_e_aceito_e_volta_pelo_formato_gravado(with_extra):
    game = cat.validate_dynamic(with_extra)
    assert game.extra_port == 8888
    assert cat.validate_dynamic(game.as_stored()) == game


def test_publico_mostra_a_porta_extra(with_extra):
    assert cat.validate_dynamic(with_extra).as_public()["extra_port"] == 8888


@pytest.mark.parametrize(("changes", "field"), [
    ({"extra_port": 9999}, "extra_port"),               # nao esta entre as portas expostas
    ({"extra_port": 7777}, "extra_port"),               # igual a porta do jogo
    ({"extra_port": 27016}, "extra_port"),              # igual a de consulta
    ({"extra_port": "8888"}, "extra_port"),             # tem de ser numero
    ({"start_args": "-port={PORT} -queryport={QUERY_PORT}"}, "shiftable"),   # falta o marcador
])
def test_extra_port_invalida_e_recusada(with_extra, changes, field):
    with_extra.update(changes)
    with pytest.raises(ValidationError) as error:
        cat.validate_dynamic(with_extra)
    assert field in str(error.value)


def test_marcador_extra_sem_porta_extra_e_recusado(game_data):
    """Sem porta extra o marcador viraria "0" na linha de comando do jogo."""
    game_data["start_args"] = "-port={PORT} -queryport={QUERY_PORT} -x={EXTRA_PORT}"
    with pytest.raises(ValidationError, match="EXTRA_PORT"):
        cat.validate_dynamic(game_data)


def test_quarta_porta_continua_recusada_para_jogo_que_anda_de_porta(with_extra):
    with_extra["ports"] = ["7777/udp", "27016/udp", "8888/tcp", "9999/udp"]
    with pytest.raises(ValidationError, match="mais portas"):
        cat.validate_dynamic(with_extra)


def test_jogo_fixo_pode_ter_porta_extra_sem_andar_de_porta(with_extra):
    with_extra["shiftable"] = False
    ports = alocador.allocate_ports(cat.validate_dynamic(with_extra), set(), FAIXA)
    assert [p.number for p in ports] == [7777, 27016, 8888]


# --- .env curado --------------------------------------------------------------------------------------

def test_env_curado_com_marcador_extra_e_sem_porta_extra_vira_erro_do_catalogo(tmp_path):
    (tmp_path / "ruim.env").write_text(
        'GAME_KEY=ruim\nSTEAM_APP_ID=1\nGAME_PORT=7001\nGAME_PORTS="7001/udp"\nSTART_ARGS="-r {EXTRA_PORT}"\n',
        encoding="utf-8")
    games, errors = cat.load_curated(tmp_path)
    assert games == {}
    assert "EXTRA_PORT" in errors[0]


def test_env_curado_deslocavel_com_porta_extra_exige_o_marcador(tmp_path):
    (tmp_path / "ruim.env").write_text(
        'GAME_KEY=ruim\nSTEAM_APP_ID=1\nGAME_PORT=7001\nGAME_PORTS="7001/udp 7002/tcp"\n'
        'EXTRA_PORT=7002\nSTART_ARGS="-p {PORT}"\nPORTS_SHIFTABLE=1\n', encoding="utf-8")
    _, errors = cat.load_curated(tmp_path)
    assert "{EXTRA_PORT}" in errors[0]
