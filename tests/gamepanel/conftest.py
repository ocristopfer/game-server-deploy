"""Cenario compartilhado pelas suites do painel.

Duas coisas acontecem aqui que nao dariam para fazer dentro de um arquivo de teste:

1. **O banco e escolhido antes de qualquer import.** O `app.py` le `GAMEPANEL_DB` e
   chama `init_db()` na hora em que e importado. Como o pytest carrega este arquivo
   antes de colecionar os testes, e aqui - e so aqui - que da para apontar o painel
   para um banco descartavel. Errar isso significa rodar os testes contra o
   `/var/lib/gamepanel/panel.db` de verdade.

2. **Cada modulo comeca com o banco limpo.** Antes da migracao para pytest cada suite
   era um processo com o seu proprio banco temporario; agora todas dividem um processo
   so. A fixture `banco` devolve o mesmo isolamento esvaziando as tabelas.
"""
from __future__ import annotations

import os
import sys
import tempfile

# Atribuicao direta, NUNCA setdefault - antes do `import app`, sempre. Ver o item 1 do
# docstring.
#
# O container do painel (docker/panel/Dockerfile) fixa `ENV GAMEPANEL_DB=/var/lib/
# gamepanel/panel.db`: essa variavel JA esta definida quando este processo comeca, e
# `setdefault` teria sido um no-op ali. Foi exatamente isso que aconteceu numa versao
# anterior deste arquivo: os testes rodaram contra o banco de verdade do container de
# dev, apagando o usuario 'admin' e enchendo a tela de servidores com "alvo", "outro"
# e "Sem consulta". Atribuicao direta garante um banco descartavel em QUALQUER
# ambiente, container ou maquina local, independente do que veio no environment.
os.environ["GAMEPANEL_DB"] = os.path.join(tempfile.mkdtemp(), "teste.db")
# Alertas nunca saem para a rede a partir daqui: quem quiser exercitar o envio troca
# `panel.envia_webhook` por um capturador (ver a fixture `webhooks`).
os.environ["GAMEPANEL_WEBHOOK_URL"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time  # noqa: E402

import pytest  # noqa: E402

from gamepanel import app as panel  # noqa: E402
from gamepanel.security import totp  # noqa: E402

# Toda tabela do SCHEMA. Esvaziar e melhor que recriar: `init_db()` tambem roda as
# migracoes, e repeti-las a cada teste mediria o tempo delas, nao o do teste.
TABELAS = ("alert_log", "jobs", "samples", "schedules", "servers", "settings",
           "users", "webhooks")


@pytest.fixture
def database():
    """Conexao propria com o banco vazio. Fecha sozinha no fim do teste."""
    conn = panel._connect()
    with conn:
        for table in TABELAS:
            conn.execute(f"DELETE FROM {table}")
    _reset_module_state()
    try:
        yield conn
    finally:
        conn.close()


def _reset_module_state() -> None:
    """Limpa os caches e relogios que o `app.py` guarda em variaveis de modulo.

    Sem isto um teste herda a leitura do anterior: o monitor acha que ja viu aquele
    servidor (e nao alerta), o cache de status devolve o estado de outro cenario, e a
    volta do relogio acha que ainda nao e hora. Foi o motivo de cada suite ser um
    processo separado antes; agora e uma funcao.
    """
    panel._monitor_state.clear()
    panel._status_cache.clear()
    panel._metrics_cache.clear()
    panel._players_cache.clear()
    panel.login_lockout.reset()
    panel.totp_lockout.reset()
    panel._last_monitor = 0.0
    panel._last_state = 0.0
    panel._last_disk = 0.0
    panel._last_log = 0.0
    panel._last_sample = 0.0
    panel._last_cleanup = 0.0


@pytest.fixture
def webhooks(database, monkeypatch):
    """Captura o que o painel MANDARIA, sem tocar na rede.

    Devolve a lista de `(url, texto)`. O que se testa nas suites de alerta e QUANDO o
    painel decide avisar - alerta a mais vira ruido e o canal deixa de ser lido; alerta
    a menos e um servidor caido as 3h que ninguem descobre.
    """
    sent_ones: list[tuple[str, str]] = []

    def capture(url, text):
        sent_ones.append((url, text))
        return ""      # string vazia = enviado com sucesso

    monkeypatch.setattr(panel, "send_webhook", capture)
    return sent_ones


@pytest.fixture
def client(database):
    """Cliente HTTP do Flask, sem ninguem logado."""
    panel.app.config["TESTING"] = True
    return panel.app.test_client()


def _login(cli, username: str, senha: str):
    """Loga `username` no cliente de teste `cli`. Devolve o proprio `cli`, logado.

    Falhar alto (nao 302) e sempre um erro de FIXTURE, nao do teste que a usa - por
    isso o `assert` aqui, e nao um `check()` que so anotaria mais uma falha na lista.
    """
    cli.get("/login")
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    resp = cli.post("/login", data={"username": username, "password": senha, "csrf": token},
                    follow_redirects=False)
    assert resp.status_code == 302, f"login de {username} falhou ({resp.status_code})"
    return cli


def _post(cli, url, data=None):
    """POST com o CSRF da sessao ja preenchido - e o que todo POST do painel exige."""
    data = dict(data or {})
    with cli.session_transaction() as sess:
        data["csrf"] = sess.get("csrf", "")
    return cli.post(url, data=data, follow_redirects=False)


@pytest.fixture
def post():
    """`postar(cli, url, dados)`: POST com CSRF, sem redirecionar."""
    return _post


@pytest.fixture
def login(database):
    """`entrar(username, senha)`: devolve um cliente NOVO, ja logado.

    Cada chamada cria seu proprio `test_client()` - dois logins na mesma suite (chefe e
    peao, por exemplo) nao podem compartilhar sessao.
    """
    def _do(username: str, senha: str):
        return _login(panel.app.test_client(), username, senha)
    return _do


@pytest.fixture
def admin(login):
    """Um administrador cadastrado e logado - o caso mais comum nas suites da web."""
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    return login("chefe", "senha-do-chefe")


@pytest.fixture
def operator(login):
    """Um operador cadastrado e logado, para os testes de permissao."""
    panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERATOR)
    return login("peao", "senha-do-peao")


@pytest.fixture
def admin_2fa(admin):
    """O mesmo `chefe`, com o segundo fator ATIVO.

    `broker_required` exige 2FA da PESSOA sempre, nao so quando `GAMEPANEL_REQUIRE_2FA`
    esta ligado — sem esta fixture, todo teste de rota do broker cairia na tela de
    ativacao em vez do que quer exercitar. Ativar 2FA na sessao ja logada nao a
    derruba (`_store_second_factor` nao mexe na sessao), entao o mesmo cliente
    continua servindo depois.
    """
    admin.get("/account/2fa")
    with admin.session_transaction() as sess:
        secret = sess["totp_pendente"]
    response = _post(admin, "/account/2fa", {"codigo": totp.code(secret, totp.step_of(time.time()))})
    assert response.status_code == 200, "nao consegui ativar o 2FA de 'chefe' para o teste"
    return admin
