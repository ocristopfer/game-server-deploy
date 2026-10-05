#!/usr/bin/env python3
"""Tests for the webhook alerts.

    pytest admin/test_alerts.py

The real sending is swapped for a capturer (`webhooks` fixture, in conftest.py): what is
tested here is WHEN the panel decides to notify, which is where the chance of error lives.
One alert too many becomes noise and the channel stops being read; one alert too few is a
server down at 3 AM that nobody finds out about.
"""
import time
from datetime import UTC, datetime, timedelta

import pytest

from gamepanel import app as panel

URL = "http://exemplo.invalid/hook"


def register_target(database, url, eventos, name="Teste", ativo=1) -> int:
    """Registers a destination and returns its id."""
    with database:
        cur = database.execute(
            "INSERT INTO webhooks (name, url, events, enabled, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, url, ",".join(eventos), ativo, panel.now_iso()))
    return cur.lastrowid


def enable(database, eventos, disco=90, memoria=90, cpu=90):
    """Leaves ONE destination registered, with these events. The default for most tests."""
    with database:
        database.execute("DELETE FROM webhooks")
    register_target(database, URL, eventos)
    panel.config_set(database, "webhook_disk_pct", str(disco))
    panel.config_set(database, "webhook_mem_pct", str(memoria))
    panel.config_set(database, "webhook_cpu_pct", str(cpu))


def expired_clocks():
    """Puts the monitor clocks in a past that beats any limit.

    Zeroing them does not work: time.monotonic() counts from the MACHINE's boot, and in a
    freshly started container zero may be less than a minute away - then the monitor exits
    early and the test fails because of the runner's uptime, not because of the code.
    """
    panel.monitor_tick.mark(time.monotonic() - 3600)
    panel.state_tick.mark(time.monotonic() - 3600)


def state(reachable=True, service="active", error="", restarts=0, result="", sub=""):
    return {"reachable": reachable, "service": service, "error": error,
            "restarts": restarts, "result": result, "sub": sub}


# Sample server WITHOUT a row in the `servers` table: the first two sections only
# exercise `_alerta_de_estado`, which queries `jobs` by `server_id` - an empty table
# returns "no recent job" without needing any FK to be satisfied.
SERVER = {"id": 1, "name": "Palworld", "host": "10.0.0.9", "ssh_user": "root",
            "service": "palworld.service"}


@pytest.fixture
def target(database):
    """The test server, actually registered. Returns the dict the alert functions
    use, with the real id - for the tests that depend on FKs (jobs, streams)."""
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Palworld', '10.0.0.9', 22, 'root', 'palworld.service', ?)",
            (panel.now_iso(),))
    sid = database.execute("SELECT id FROM servers").fetchone()["id"]
    return dict(SERVER, id=sid)


# ------------------------------------------------------------------- configuration

def test_configuracao_le_destino_e_evento_do_banco(database):
    enable(database, ["caiu"])
    cfg = panel.webhook_config(database)
    assert [d["url"] for d in cfg["active"]] == [URL]
    assert cfg["events"] == {"caiu"}


def test_evento_desconhecido_no_banco_e_descartado(database):
    """A database edited by hand (or an old version) must not turn into an unknown key."""
    enable(database, ["caiu"])
    with database:
        database.execute("UPDATE webhooks SET events = 'caiu,formatar-o-disco'")
    assert panel.webhook_config(database)["events"] == {"caiu"}


def test_limites_tem_piso_e_padrao_para_valor_ilegivel(database):
    enable(database, ["caiu"])
    panel.config_set(database, "webhook_disk_pct", "5")
    assert panel.webhook_config(database)["disk"] == 50, "limite de disco tem piso"
    panel.config_set(database, "webhook_disk_pct", "nao e numero")
    assert panel.webhook_config(database)["disk"] == panel.DISK_PCT_DEFAULT
    panel.config_set(database, "webhook_mem_pct", "5")
    assert panel.webhook_config(database)["memory"] == 50, "limite de memoria tem piso"
    panel.config_set(database, "webhook_cpu_pct", "vazio")
    assert panel.webhook_config(database)["cpu"] == panel.CPU_PCT_DEFAULT


# ---------------------------------------------------------------------- several destinations

@pytest.fixture
def three_targets(database):
    """The point of the feature: two active channels with different lists, plus a disabled one."""
    with database:
        database.execute("DELETE FROM webhooks")
    team = register_target(database, "http://equipe.invalid/hook", ["caiu", "voltou"], "Equipe")
    overall = register_target(database, "http://geral.invalid/hook", ["caiu"], "Geral")
    muted = register_target(database, "http://mudo.invalid/hook", ["caiu"], "Desligado", ativo=0)
    return {"equipe": team, "geral": overall, "mudo": muted}


def test_evento_pedido_pelos_dois_sai_duas_vezes(database, three_targets, webhooks):
    did_send = panel.notify(database, "caiu", "caiu")
    assert (did_send, len(webhooks)) == (True, 2)
    assert sorted(u for u, _ in webhooks) == [
        "http://equipe.invalid/hook", "http://geral.invalid/hook"]
    assert all("mudo.invalid" not in u for u, _ in webhooks), "destino desligado nao recebe"


def test_evento_de_um_so_sai_uma_vez(database, three_targets, webhooks):
    panel.notify(database, "voltou", "voltou")
    assert [u for u, _ in webhooks] == ["http://equipe.invalid/hook"]


def test_evento_que_ninguem_pediu_nao_sai(database, three_targets, webhooks):
    did_send = panel.notify(database, "disco-cheio", "disco")
    assert (did_send, len(webhooks)) == (False, 0)


def test_uniao_dos_destinos_ligados_e_o_que_o_monitor_observa(database, three_targets):
    assert panel.webhook_config(database)["events"] == {"caiu", "voltou"}


def test_destino_quebrado_nao_impede_os_outros(database, three_targets, webhooks, monkeypatch):
    """A destination that is down must not silence the others: the Discord that is up keeps
    receiving even with Slack refusing the connection."""
    def partial(url, text):
        if "equipe" in url:
            webhooks.append((url, text))
            return ""
        return "recusou a conexao"

    monkeypatch.setattr(panel, "send_webhook", partial)
    did_send = panel.notify(database, "caiu", "caiu")
    assert (did_send, len(webhooks)) == (True, 1)


def test_todos_desligados_nada_sai(database, three_targets, webhooks):
    with database:
        database.execute("UPDATE webhooks SET enabled = 0")
    did_send = panel.notify(database, "caiu", "caiu")
    assert (did_send, len(webhooks)) == (False, 0)


# --------------------------------------------------------- URL does not show on screen

def test_mascara_url_esconde_o_token_mas_nao_o_canal():
    """The URL is a credential: whoever reads the screen over someone's shoulder must not
    leave able to write to the channel."""
    masked = panel.mask_url(
        "https://discord.com/api/webhooks/1544786528700604457/segredo-que-nao-pode-vazar")
    assert "segredo-que-nao-pode-vazar" not in masked
    assert "1544786528700604457" in masked, "o id continua visivel para reconhecer o canal"
    assert masked.startswith("discord.com")


def test_mascara_url_vazia_nao_vira_mascara():
    assert panel.mask_url("") == ""


# ------------------------------------------------------ when the panel decides to notify

def test_queda_avisa(database, webhooks):
    enable(database, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(database, SERVER, state(service="inactive"),
                            state(service="active"))
    assert len(webhooks) == 1
    assert "Palworld" in webhooks[0][1]
    assert "palworld.service" in webhooks[0][1]


def test_volta_avisa(database, webhooks):
    enable(database, ["caiu", "voltou"])
    panel._state_alert(database, SERVER, state(service="active"),
                            state(service="inactive"))
    assert len(webhooks) == 1


def test_nada_mudou_nada_sai(database, webhooks):
    enable(database, ["caiu", "voltou"])
    panel._state_alert(database, SERVER, state(service="active"), state(service="active"))
    assert len(webhooks) == 0


def test_perder_contato_avisa_com_o_motivo(database, webhooks):
    enable(database, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(database, SERVER,
                            state(reachable=False, service="inacessivel", error="timeout"),
                            state(service="active"))
    assert len(webhooks) == 1
    assert "timeout" in webhooks[0][1]


def test_sem_contato_nao_acumula_alerta_de_servico(database, webhooks):
    """The panel does not know what the service is doing without contact: also reporting
    'caiu' would be making it up. ONE message goes out, the contact one."""
    enable(database, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(database, SERVER, state(reachable=False, service="inacessivel"),
                            state(reachable=True, service="active"))
    assert len(webhooks) == 1


def test_continua_sem_contato_nao_repete(database, webhooks):
    enable(database, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(database, SERVER, state(reachable=False, service="inacessivel"),
                            state(reachable=False, service="inacessivel"))
    assert len(webhooks) == 0


def test_evento_desligado_na_tela_nao_sai(database, webhooks):
    enable(database, ["voltou"])
    panel._state_alert(database, SERVER, state(service="inactive"),
                            state(service="active"))
    assert len(webhooks) == 0


def test_sem_destino_nao_sai_nada(database):
    with database:
        database.execute("DELETE FROM webhooks")
    assert panel.notify(database, "caiu", "titulo", "detalhe") is False


# -------------------------------------------------------- panel action is not a scare

def test_sem_job_recente_a_queda_e_queda(database, target):
    assert not panel._recent_job(database, target["id"])


def test_restart_pelo_painel_abre_a_janela_de_silencio(database, target):
    with database:
        database.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (target["id"], "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
    assert panel._recent_job(database, target["id"])


def test_reiniciar_pelo_botao_nao_vira_alerta(database, target, webhooks):
    enable(database, ["caiu"])
    with database:
        database.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (target["id"], "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
    panel._state_alert(database, target, state(service="inactive"), state(service="active"))
    assert len(webhooks) == 0


def test_job_velho_nao_segura_o_alerta_para_sempre(database, target, webhooks):
    enable(database, ["caiu"])
    old_one = (datetime.now(UTC) - timedelta(seconds=panel.ALERT_QUIET + 60)).isoformat()
    with database:
        database.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (target["id"], "root@10.0.0.9", "restart", "ok", "admin", old_one))
    assert not panel._recent_job(database, target["id"])
    panel._state_alert(database, target, state(service="inactive"), state(service="active"))
    assert len(webhooks) == 1, "passada a janela, a queda avisa"


# ------------------------------------------------------- the game, not the service
# The hole these three sections cover: "service running" is not "game working". A game
# can be frozen, crashing in a loop or spitting errors into the log while systemd thinks
# everything is fine - and until now none of that became an alert.

def test_instance_service_em_failed_avisa_que_quebrou(database, target, webhooks):
    enable(database, ["caiu", "quebrou"])
    panel._state_alert(database, target, state(service="failed", result="exit-code"),
                            state(service="active"))
    assert len(webhooks) == 1
    assert "quebrou" in webhooks[0][1], "a mensagem diz que QUEBROU, nao que pararam"
    assert "exit-code" in webhooks[0][1]


def test_quebrar_logo_apos_a_acao_do_painel_ainda_avisa(database, target, webhooks):
    """Stopping from the panel is 'inactive' and falls inside the silence window. Ending in
    'failed' right after an action is something else: the action broke the game, and that is
    the case one most wants to know about."""
    enable(database, ["caiu", "quebrou"])
    with database:
        database.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (target["id"], "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
    panel._state_alert(database, target, state(service="inactive"), state(service="active"))
    assert len(webhooks) == 0, "parar pelo painel continua silencioso"
    panel._state_alert(database, target, state(service="failed"), state(service="active"))
    assert len(webhooks) == 1, "mas quebrar logo apos a acao avisa"


def test_loop_de_restart(database, target, webhooks):
    enable(database, ["reiniciando"])
    previous = {"reachable": True, "service": "active", "restarts": 2}

    panel._restart_alert(database, target, state(restarts=5), previous)
    assert len(webhooks) == 1
    assert "3x" in webhooks[0][1], "a mensagem diz quantas vezes"

    # While the counter keeps rising it is the SAME episode: notifying on every pass
    # would be the spam the change rule exists to avoid.
    webhooks.clear()
    panel._restart_alert(database, target, state(restarts=8), previous)
    assert len(webhooks) == 0, "continua subindo, nao repete"

    # A whole pass with no new restart closes the episode.
    panel._restart_alert(database, target, state(restarts=8), previous)
    assert not previous["loop_avisado"], "volta sem restart destrava o alerta"
    webhooks.clear()
    panel._restart_alert(database, target, state(restarts=11), previous)
    assert len(webhooks) == 1, "um loop novo volta a avisar"

    # A manual `systemctl restart` zeroes NRestarts. That is a new baseline, not a loop.
    webhooks.clear()
    panel._restart_alert(database, target, state(restarts=0), previous)
    assert len(webhooks) == 0, "contador zerado nao vira alerta"
    assert previous["restarts"] == 0, "e a linha de base acompanha"


def test_jogo_de_pe_mas_mudo(database, target, webhooks, monkeypatch):
    """Only something that answers a real probe can go silent."""
    enable(database, ["travou", "respondeu"])
    probed = dict(target, player_source="a2s", query_port=27015)
    muteness = {"reachable": True, "service": "active", "restarts": 0}
    response = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: response)

    for _ in range(panel.MUTE_ROUNDS - 1):
        panel._mute_alert(database, probed, state(), muteness)
    assert len(webhooks) == 0, "nao avisa no primeiro silencio (UDP perde pacote)"
    panel._mute_alert(database, probed, state(), muteness)
    assert len(webhooks) == 1, f"avisa na volta {panel.MUTE_ROUNDS}"
    assert "não responde" in webhooks[0][1], "a mensagem separa 'rodando' de 'respondendo'"

    webhooks.clear()
    panel._mute_alert(database, probed, state(), muteness)
    assert len(webhooks) == 0, "continua mudo, nao repete"


def test_voltar_a_responder_avisa_uma_vez(database, target, webhooks, monkeypatch):
    enable(database, ["travou", "respondeu"])
    probed = dict(target, player_source="a2s", query_port=27015)
    muteness = {"reachable": True, "service": "active", "restarts": 0}
    response = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: response)
    for _ in range(panel.MUTE_ROUNDS):
        panel._mute_alert(database, probed, state(), muteness)

    webhooks.clear()
    ok_response = {"configured": True, "error": "", "players": 4, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: ok_response)
    panel._mute_alert(database, probed, state(), muteness)
    assert len(webhooks) == 1, "voltou a responder, avisa uma vez"
    panel._mute_alert(database, probed, state(), muteness)
    assert len(webhooks) == 1, "e nao fica repetindo o alivio"


def test_instance_service_subindo_nao_conta_como_mudez(database, target, webhooks, monkeypatch):
    """A game loading its map does not answer and must not become an alert: counting only
    starts with the service active and outside the silence window."""
    enable(database, ["travou", "respondeu"])
    probed = dict(target, player_source="a2s", query_port=27015)
    response = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: response)
    muteness = {"reachable": True, "service": "active", "restarts": 0, "mudo": 0}
    for _ in range(panel.MUTE_ROUNDS + 2):
        panel._mute_alert(database, probed, state(service="activating"), muteness)
    assert len(webhooks) == 0


def test_contagem_por_log_nao_gera_alerta_de_mudez(database, target, webhooks):
    """Counting by log asks the game nothing: there is nothing to go silent."""
    enable(database, ["travou", "respondeu"])
    by_log = dict(target, player_source="log", query_port=0)
    for _ in range(panel.MUTE_ROUNDS + 2):
        panel._mute_alert(database, by_log, state(), {"service": "active"})
    assert len(webhooks) == 0


# --------------------------------------------------------- players joining and leaving

@pytest.fixture
def players_server(target):
    return dict(target, player_source="log", query_port=0)


def _cfg(database, eventos):
    enable(database, eventos)
    return panel.webhook_config(database)


def test_primeira_olhada_so_anota_linha_de_base(database, players_server, webhooks, monkeypatch):
    cfg = _cfg(database, ["jogador-entrou", "jogador-saiu"])
    res = {"configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: res)
    memory = {"reachable": True, "service": "active"}

    panel._players_alert(database, players_server, "active", memory, cfg)
    assert len(webhooks) == 0
    assert memory["jogadores_nomes"] == {"Cristopfer"}


def test_sem_mudanca_de_jogadores_nao_avisa(database, players_server, webhooks, monkeypatch):
    cfg = _cfg(database, ["jogador-entrou", "jogador-saiu"])
    res = {"configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: res)
    memory = {"reachable": True, "service": "active"}
    panel._players_alert(database, players_server, "active", memory, cfg)  # baseline

    webhooks.clear()
    panel._players_alert(database, players_server, "active", memory, cfg)
    assert len(webhooks) == 0


def test_jogador_novo_avisa_entrada(database, players_server, webhooks, monkeypatch):
    cfg = _cfg(database, ["jogador-entrou", "jogador-saiu"])
    memory = {"reachable": True, "service": "active"}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]})
    panel._players_alert(database, players_server, "active", memory, cfg)  # baseline

    webhooks.clear()
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 2,
        "list": [{"name": "Cristopfer"}, {"name": "Ana"}]})
    panel._players_alert(database, players_server, "active", memory, cfg)
    assert len(webhooks) == 1
    assert "Ana entrou no jogo" in webhooks[0][1]
    assert "2 jogadores online" in webhooks[0][1]


def test_jogador_saindo_avisa_saida(database, players_server, webhooks, monkeypatch):
    cfg = _cfg(database, ["jogador-entrou", "jogador-saiu"])
    memory = {"reachable": True, "service": "active", "jogadores_nomes": {"Cristopfer", "Ana"},
               "jogadores_count": 2}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]})
    panel._players_alert(database, players_server, "active", memory, cfg)
    assert len(webhooks) == 1
    assert "Ana saiu do jogo" in webhooks[0][1]


def test_ultimo_jogador_saindo_avisa(database, players_server, webhooks, monkeypatch):
    cfg = _cfg(database, ["jogador-entrou", "jogador-saiu"])
    memory = {"reachable": True, "service": "active", "jogadores_nomes": {"Cristopfer"},
               "jogadores_count": 1}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})
    panel._players_alert(database, players_server, "active", memory, cfg)
    assert len(webhooks) == 1
    assert "nenhum jogador online" in webhooks[0][1]


def test_contagem_numerica_sem_nomes_avisa_variacao(database, players_server, webhooks, monkeypatch):
    """Server with count only (no names)."""
    cfg = _cfg(database, ["jogador-entrou", "jogador-saiu"])
    memory = {"reachable": True, "service": "active"}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})
    panel._players_alert(database, players_server, "active", memory, cfg)  # baseline

    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 3, "list": []})
    panel._players_alert(database, players_server, "active", memory, cfg)
    assert len(webhooks) == 1
    assert "3 jogadores conectaram" in webhooks[0][1]


def test_instance_service_parado_nao_dispara_alerta_de_saida_e_reseta(database, players_server, webhooks):
    cfg = _cfg(database, ["jogador-entrou", "jogador-saiu"])
    memory = {"reachable": True, "service": "active",
               "jogadores_nomes": {"Cristopfer"}, "jogadores_count": 1}
    panel._players_alert(database, players_server, "failed", memory, cfg)
    assert len(webhooks) == 0
    assert memory["jogadores_nomes"] is None, "a memoria reseta"


# --------------------------------------------------- the monitor's fast pass
# A player joining must arrive in seconds, not in the next minute: whoever gets the
# notice usually wants to join too. The fast pass exists for that - and it must not
# cost SSH, otherwise speeding up the alert would multiply the bill for everything else.

@pytest.fixture
def a2s_monitor(database, target, monkeypatch):
    """The server registered with A2S: direct query to the game, no SSH."""
    enable(database, ["jogador-entrou", "jogador-saiu", "caiu"])
    with database:
        database.execute("UPDATE servers SET player_source = 'a2s', query_port = 27015")

    ssh_trips = []

    def counted_status(server, force=False):
        ssh_trips.append(int(server["id"]))
        return state()

    monkeypatch.setattr(panel, "server_status", counted_status)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})
    return ssh_trips


def test_volta_completa_consulta_o_systemd(database, a2s_monitor):
    with panel.app.app_context():
        # Expired clocks = FULL pass. Two are needed: the first records the
        # server state, the second the players baseline.
        expired_clocks()
        panel.monitor_servers()
        expired_clocks()
        panel.monitor_servers()
    assert len(a2s_monitor) == 2


def test_entrada_chega_na_volta_rapida_sem_ssh(database, a2s_monitor, webhooks, monkeypatch):
    with panel.app.app_context():
        expired_clocks()
        panel.monitor_servers()
        expired_clocks()
        panel.monitor_servers()
    a2s_monitor.clear()

    # The clocks go back 20s: the state one (60s) has not expired yet, the players one (15s)
    # has - which is exactly the situation in the middle of two minutes.
    indent = time.monotonic() - 20
    panel.monitor_tick.mark(indent)
    panel.state_tick.mark(indent)
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 1, "list": [{"name": "Ana"}]})
    with panel.app.app_context():
        panel.monitor_servers()
    assert any("Ana entrou no jogo" in t for _, t in webhooks)
    assert a2s_monitor == [], "e ela nao gastou nenhuma ida de SSH"


def test_contagem_por_log_nao_entra_na_volta_curta(database, target, webhooks, monkeypatch):
    """Each log read is an SSH trip that drags the whole file; at 15s that would
    become megabytes per minute to find two lines. Counting by log waits for the
    full pass."""
    enable(database, ["jogador-entrou", "jogador-saiu", "caiu"])
    with database:
        database.execute("UPDATE servers SET player_source = 'log', query_port = 0")
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: state())
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})

    with panel.app.app_context():
        # Two full passes to get a baseline: the first records the state, the second
        # the players (empty server).
        expired_clocks()
        panel.monitor_servers()
        expired_clocks()
        panel.monitor_servers()

    # People arrived, but only the short clock expired: by log, the panel does not go fetch.
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 2,
        "list": [{"name": "Ana"}, {"name": "Bea"}]})
    panel.monitor_tick.mark(time.monotonic() - 20)
    with panel.app.app_context():
        panel.monitor_servers()
    assert len(webhooks) == 0

    # ...but on the next full pass it notifies normally.
    expired_clocks()
    with panel.app.app_context():
        panel.monitor_servers()
    assert any("entrou no jogo" in t for _, t in webhooks)


def test_sem_alerta_de_jogador_20s_ainda_nao_e_hora(database, target, monkeypatch):
    """The short step only exists because of the player event. Without it the same 20s
    are not enough, and the monitor keeps its old pace - nobody pays extra SSH for nothing."""
    enable(database, ["caiu"])
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: state())
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    indent = time.monotonic() - 20
    panel.monitor_tick.mark(indent)
    panel.state_tick.mark(indent)
    with panel.app.app_context():
        assert panel.monitor_servers() == 0


# ------------------------------------------------------------------- error in the log

def test_erro_no_log_do_jogo(database, target, webhooks, monkeypatch):
    enable(database, ["erro-no-log"])
    lines_of = ["tudo bem por aqui", "Fatal error: world corrupted", "seguindo"]
    monkeypatch.setattr(panel, "read_log_lines", lambda server, limit=0: lines_of)
    with_regex = dict(target, error_re="Fatal error")
    memory = {}

    panel._log_alert(database, with_regex, memory)
    assert len(webhooks) == 1
    assert "world corrupted" in webhooks[0][1], "leva a linha inteira"

    # The same line is still at the tail of the log on the next pass. Notifying again would
    # be one alert per minute until someone fixes it.
    webhooks.clear()
    panel._log_alert(database, with_regex, memory)
    assert len(webhooks) == 0, "a mesma linha nao avisa duas vezes"

    # Cooldown: even with a new line, the channel does not get flooded by a broad expression.
    monkeypatch.setattr(panel, "read_log_lines",
                        lambda server, limit=0: ["Fatal error: outra coisa"])
    webhooks.clear()
    panel._log_alert(database, with_regex, memory)
    assert len(webhooks) == 0, "linha nova dentro da janela nao passa"
    assert "outra coisa" in memory["ultimo_erro"], "mas a memoria acompanha a linha nova"

    # Once the window has passed, a new error notifies again.
    memory["erro_em"] = 0
    monkeypatch.setattr(panel, "read_log_lines",
                        lambda server, limit=0: ["Fatal error: mais uma"])
    webhooks.clear()
    panel._log_alert(database, with_regex, memory)
    assert len(webhooks) == 1, "passado o cooldown, avisa de novo"

    monkeypatch.setattr(panel, "read_log_lines",
                        lambda server, limit=0: ["nada de mais aqui"])
    webhooks.clear()
    panel._log_alert(database, with_regex, memory)
    assert len(webhooks) == 0, "log limpo nao avisa"
    assert memory["ultimo_erro"] == "", "e a memoria do erro e esquecida"


def test_erro_no_log_servidor_sem_expressao_nem_le(database, target, webhooks):
    panel._log_alert(database, target, {})
    assert len(webhooks) == 0, "sem expressao, nem chega a ler o log"


def test_erro_no_log_expressao_invalida_nao_estoura(database, target, webhooks):
    """A broken expression is a registration problem, not a reason to bring down the monitor pass."""
    panel._log_alert(database, dict(target, error_re="("), {})
    assert len(webhooks) == 0


# ------------------------------------------------------------------------ disk full

def test_disco_cheio(database, target, webhooks, monkeypatch):
    enable(database, ["disco-cheio"], disco=90)
    disks = {"disks": [{"mount": "/", "pct": 40.0, "used": 4, "total": 10},
                        {"mount": "/opt/game", "pct": 95.0, "used": 95, "total": 100}]}
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: disks)

    # The monitor memory must NOT be reset between calls: it is precisely what
    # remembers "this disk was already full last time".
    panel._disk_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 1
    assert "/opt/game" in webhooks[0][1], "avisa sobre o disco MAIS cheio, nao o primeiro"

    # A disk at 95% is still at 95% the next minute: notifying again would be spam.
    webhooks.clear()
    panel._disk_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "continua cheio, nao repete"

    # After freeing space the mark drops, and a new rise notifies again.
    disks["disks"] = [{"mount": "/opt/game", "pct": 40.0, "used": 40, "total": 100}]
    panel._disk_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "voltar ao normal nao avisa (esse evento nao existe)"
    disks["disks"] = [{"mount": "/opt/game", "pct": 97.0, "used": 97, "total": 100}]
    panel._disk_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 1, "encheu de novo, avisa de novo"

    # A meter that failed must not become an empty-disk alert nor blow up.
    monkeypatch.setattr(panel, "server_metrics",
                        lambda server, force=False: {"error": "tempo esgotado"})
    webhooks.clear()
    panel._disk_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "medidor com erro nao avisa nada"

    # ...and must not erase the mark that the disk was full.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "disks": [{"mount": "/opt/game", "pct": 97.0, "used": 97, "total": 100}]})
    panel._disk_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "depois de um erro no medidor, o disco cheio nao repete"


# ------------------------------------------------------------------- memory almost full

GIB = 1024 ** 3


def test_memoria_quase_cheia(database, target, webhooks, monkeypatch):
    enable(database, ["memoria-alta"], memoria=90)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 95.0, "used": 3.8 * GIB, "total": 4.0 * GIB}})

    # As with the disk, the monitor memory must NOT be reset between calls.
    panel._memory_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 1
    assert "95.0%" in webhooks[0][1]
    assert "3.8 GB" in webhooks[0][1]
    assert "4.0 GB" in webhooks[0][1]

    webhooks.clear()
    panel._memory_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "continua cheia, nao repete"

    # Memory freed: the mark drops and a new rise notifies again.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 40.0, "used": 1.6 * GIB, "total": 4.0 * GIB}})
    panel._memory_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "baixou, nao avisa (esse evento nao existe)"
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 97.0, "used": 3.9 * GIB, "total": 4.0 * GIB}})
    panel._memory_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 1, "encheu de novo, avisa de novo"

    # A meter that failed must not become an alert nor blow up...
    monkeypatch.setattr(panel, "server_metrics",
                        lambda server, force=False: {"error": "tempo esgotado"})
    webhooks.clear()
    panel._memory_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "medidor com erro nao avisa nada"

    # ...and must not erase the mark that memory was full.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 97.0, "used": 3.9 * GIB, "total": 4.0 * GIB}})
    panel._memory_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "depois de um erro no medidor, a memoria cheia nao repete"


def test_memoria_sem_medida_valida_nao_avisa(database, target, webhooks, monkeypatch):
    """A container without a readable memory ceiling returns pct None. Comparing None with the
    limit would blow up the whole monitor pass, and treating it as 0 would hide the problem."""
    enable(database, ["memoria-alta"], memoria=90)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": None, "used": 0, "total": 0}})
    panel._memory_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0


# ------------------------------------------------------------------------- high CPU

def test_cpu_alta(database, target, webhooks, monkeypatch):
    enable(database, ["cpu-alta"], cpu=90)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": 94.5, "cores": 4, "proc": {"cpu_pct": 92.1}})

    panel._cpu_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 1
    # Without the cores, "94.5%" does not say whether it is a drowning machine or one core of
    # four; and without the game's share there is no telling if the culprit is the server or something else.
    assert "94.5%" in webhooks[0][1]
    assert "4 núcleos" in webhooks[0][1]
    assert "jogo: 92.1%" in webhooks[0][1]

    webhooks.clear()
    panel._cpu_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "continua alta, nao repete"

    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": 12.0, "cores": 4, "proc": {}})
    panel._cpu_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "baixou, nao avisa (esse evento nao existe)"

    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": 99.0, "cores": 1, "proc": {}})
    panel._cpu_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 1, "subiu de novo, avisa de novo"
    assert "em 1 núcleo" in webhooks[0][1], "um nucleo so nao vira plural"
    assert "nucleos" not in webhooks[0][1]
    assert "jogo:" not in webhooks[0][1], "sem PID do jogo, a mensagem nao inventa a fatia"

    # Two samples are the minimum to compute CPU usage; with only one the meter returns None.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": None, "cores": 4, "proc": {}})
    webhooks.clear()
    panel._cpu_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "sem amostra de CPU nao avisa"

    monkeypatch.setattr(panel, "server_metrics",
                        lambda server, force=False: {"error": "tempo esgotado"})
    panel._cpu_alert(database, target, panel.webhook_config(database))
    assert len(webhooks) == 0, "medidor com erro nao avisa nada"


# ------------------------------------------------------- the monitor wires up the three meters
# Disk, memory and CPU come from the same read and run on the same clock. It is easy to turn
# the event on in the UI and forget the wire inside the monitor pass: so the pass is tested.

@pytest.fixture
def tight_meter(target, monkeypatch):
    tight = {"disks": [{"mount": "/", "pct": 99.0, "used": 99, "total": 100}],
                "mem": {"pct": 99.0, "used": 99, "total": 100},
                "cpu_pct": 99.0, "cores": 2, "proc": {}}
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: tight)
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: state())
    return tight


def test_a_volta_do_monitor_dispara_os_tres(database, tight_meter, webhooks):
    enable(database, ["disco-cheio", "memoria-alta", "cpu-alta"])
    with panel.app.app_context():
        panel.monitor_servers(force=True)   # the first pass only records
        panel.monitor_servers(force=True)
    text = "\n".join(t for _, t in webhooks)
    assert "disco quase cheio" in text
    assert "memória quase cheia" in text
    assert "uso de CPU alto" in text


def test_evento_desmarcado_nao_sai_de_carona(database, tight_meter, webhooks):
    """The opposite: an event unchecked in the UI must not ride along with the others."""
    enable(database, ["disco-cheio"])
    with panel.app.app_context():
        panel.monitor_servers(force=True)
        panel.monitor_servers(force=True)
    text = "\n".join(t for _, t in webhooks)
    assert "disco quase cheio" in text
    assert "memoria quase cheia" not in text
    assert "uso de CPU alto" not in text


# ------------------------------------------------------------------ real-time log
# Counting by log was the only case with no way to get fast through querying. The way out
# was to stop asking: a long-lived SSH connection listening to the log. What is tested here
# is WHO gets that connection and WHEN it is redone - the rest is a subprocess, which only
# the real server exercises.

def test_linha_de_jogador_reconhece_entrada_e_saida():
    join_re = panel.compile_pattern(r"\[server\] Player '(?P<name>[^']+)' logged in",
                                      "entrada")
    leave_re = panel.compile_pattern(r"\[server\] Remove Player '(?P<name>[^']+)'", "saida")
    assert panel._player_line(
        "2026-09-08 10:00:00 [server] Player 'Ana' logged in", join_re, leave_re)
    assert panel._player_line(
        "2026-09-08 10:05:00 [server] Remove Player 'Ana'", join_re, leave_re)
    assert not panel._player_line(
        "2026-09-08 10:00:01 [server] Saving world chunk 42", join_re, leave_re), \
        "ruido do log nao dispara nada"
    # Game logs have huge lines (stack traces, state dumps); the cut keeps the
    # regex from scanning megabytes per line.
    assert not panel._player_line(
        "x" * 50000 + " [server] Player 'Ana' logged in", join_re, leave_re)


def _srv(sid, **fields):
    base = {"id": sid, "host": "10.0.0.9", "ssh_port": 22, "ssh_user": "root",
            "service": "jogo.service", "log_path": "", "query_port": 0,
            "player_source": "log", "join_re": r"Player '(?P<name>[^']+)' logged in",
            "leave_re": ""}
    return {**base, **fields}


CFG_STREAM = {"events": {"jogador-entrou", "jogador-saiu"}}


def test_streams_desejados_so_para_quem_conta_por_log():
    assert sorted(panel.wanted_streams([_srv(1)], CFG_STREAM)) == [1]
    # A2S and HTTP already answer for free on the short pass: opening a permanent connection
    # for them would be paying for nothing.
    assert panel.wanted_streams(
        [_srv(1, player_source="a2s", query_port=27015)], CFG_STREAM) == {}
    assert panel.wanted_streams([_srv(1, join_re="")], CFG_STREAM) == {}, \
        "sem padrao de entrada nao ha o que ouvir"
    assert panel.wanted_streams([_srv(1)], {"events": {"caiu"}}) == {}


def test_assinatura_de_stream_muda_com_o_cadastro():
    """The signature is what decides to redo the connection: changing the regex has to drop
    the old one, otherwise the panel keeps listening with the old pattern until the next restart."""
    # Two calls, two DISTINCT dicts (but with the same content): what is checked
    # is that the signature depends on the registration data, not on the object identity.
    again = panel._stream_signature(_srv(1))
    assert panel._stream_signature(_srv(1)) == again, "mesmo cadastro, mesma assinatura"
    assert panel._stream_signature(_srv(1)) != panel._stream_signature(
        _srv(1, join_re="outro (?P<name>.+)"))
    assert panel._stream_signature(_srv(1)) != panel._stream_signature(
        _srv(1, log_path="/opt/game/logs/x.log"))
    assert panel._stream_signature(_srv(1)) != panel._stream_signature(
        _srv(1, host="10.0.0.10"))


def test_regex_que_nao_compila_faz_a_thread_desistir():
    """An invalid registration must not become a loop: the thread gives up, and the supervisor
    has to respect that instead of recreating it every pass just for it to die the same way."""
    dead_one = panel._LogStream(_srv(9, join_re="("), panel._stream_signature(_srv(9)))
    dead_one._follow()
    assert dead_one.gave_up, dead_one.error
    assert "entrada" in dead_one.error


# --------------------------------------------------------- log connection supervisor
# No real SSH here: what is measured is the decision to open, swap and close.

class _FakeStream:
    def __init__(self, server, signature, record):
        self.sid, self.signature = int(server["id"]), signature
        self.gave_up, self._vivo, self.parado = False, True, False
        record.append(self)

    def start(self):
        pass

    def stop(self):
        self.parado, self._vivo = True, False

    def alive(self):
        return self._vivo


@pytest.fixture
def fake_supervisor(database, target, monkeypatch):
    """Swaps `_LogStream` for a double that only records open/close - no SSH at all."""
    created_ones = []
    monkeypatch.setattr(
        panel, "_LogStream",
        lambda server, signature: _FakeStream(server, signature, created_ones))
    panel._streams.clear()
    enable(database, ["jogador-entrou", "jogador-saiu"])
    with database:
        database.execute("UPDATE servers SET player_source=?, query_port=0, join_re=?",
                     ("log", r"Player (?P<name>\S+) logged in"))
    yield created_ones
    panel._streams.clear()


def test_supervisiona_streams_abre_uma_conexao_por_servidor(database, fake_supervisor):
    created_ones = fake_supervisor
    with panel.app.app_context():
        assert panel.supervise_streams() == 1, "abre uma conexao para o servidor por log"
        assert panel.supervise_streams() == 1, "e nao abre outra na volta seguinte"
    assert len(created_ones) == 1, "so uma conexao foi criada"


def test_regex_novo_derruba_a_conexao_antiga(database, fake_supervisor):
    """Changing the regex in the registration has to drop the old connection: otherwise the
    panel keeps listening with the old pattern until someone restarts the panel."""
    created_ones = fake_supervisor
    with panel.app.app_context():
        panel.supervise_streams()
    with database:
        database.execute("UPDATE servers SET join_re=?", (r"Jogador (?P<name>\S+) entrou",))
    with panel.app.app_context():
        panel.supervise_streams()
    assert created_ones[0].parado
    assert len(created_ones) == 2, "e abre outra no lugar"


def test_http_client_morta_e_levantada_de_novo(database, fake_supervisor):
    """A connection that died on its own (server restarted, network dropped) comes back next pass."""
    created_ones = fake_supervisor
    with panel.app.app_context():
        panel.supervise_streams()
    created_ones[-1]._vivo = False
    with panel.app.app_context():
        panel.supervise_streams()
    assert len(created_ones) == 2


def test_quem_desistiu_por_cadastro_invalido_nao_vira_laco(database, fake_supervisor):
    """Recreating does not fix a broken regex, and every pass would be a new thread dying
    the same way, filling the log with errors."""
    created_ones = fake_supervisor
    with panel.app.app_context():
        panel.supervise_streams()
    created_ones[-1]._vivo = False
    created_ones[-1].gave_up = True
    with panel.app.app_context():
        panel.supervise_streams()
    assert len(created_ones) == 1


def test_evento_de_jogador_desligado_fecha_tudo(database, fake_supervisor):
    with panel.app.app_context():
        panel.supervise_streams()
    enable(database, ["caiu"])
    with panel.app.app_context():
        assert panel.supervise_streams() == 0


# ------------------------------------------------------------------ alert journal

def test_o_envio_vira_uma_linha_no_diario(database, webhooks):
    """The journal is the answer to "nothing arrives on Discord": without it, an alert that did
    not happen and an alert that did not go out are the same empty screen."""
    enable(database, ["caiu"])
    panel.notify(database, "caiu", "Palworld: parou", "detalhe")
    journal = panel.recent_alerts(database)
    assert len(journal) == 1
    assert (journal[0]["event"], journal[0]["status"]) == ("caiu", "enviado")


def test_evento_sem_ninguem_escutando_e_registrado(database, webhooks):
    """It is the most common case of a silent channel, and it has to be recorded looking like
    that - otherwise the person hunts for a defect where there is none."""
    enable(database, ["caiu"])
    panel.notify(database, "cpu-alta", "Palworld: CPU alta", "99%")
    journal = panel.recent_alerts(database)
    assert journal[0]["status"] == "sem-destino"
    assert journal[0]["event"] == "cpu-alta"


def test_envio_que_falhou_fica_marcado_com_o_motivo(database, monkeypatch):
    enable(database, ["caiu"])
    monkeypatch.setattr(panel, "send_webhook",
                        lambda url, text: "500 Internal Server Error")
    panel.notify(database, "caiu", "Palworld: parou de novo", "")
    journal = panel.recent_alerts(database)
    assert journal[0]["status"] == "falhou"
    assert "500" in journal[0]["error"]


def test_limpeza_do_diario_segura_o_tamanho_e_guarda_os_novos(database, webhooks, monkeypatch):
    """The journal must not grow forever nor delete what matters."""
    enable(database, ["caiu"])
    monkeypatch.setattr(panel, "ALERT_LOG_KEEP", 3)
    for i in range(6):
        panel.notify(database, "caiu", f"alerta {i}", "")
    with panel.app.app_context():
        panel.clean_history(force=True)
    journal = panel.recent_alerts(database)
    assert len(journal) == 3
    assert "alerta 5" in journal[0]["title"], "guarda os mais NOVOS"


# ------------------------------------------------------- one broken task does not silence the others
# The bug that made everything go quiet: the four clock tasks shared a single try, so an
# exception in roda_agendamentos killed the monitor on the same tick - forever, because
# the broken task broke again on every pass.

def test_tarefa_quebrada_nao_cala_o_monitor(database, target, webhooks, monkeypatch):
    enable(database, ["caiu"])

    def explode():
        raise RuntimeError("agenda quebrada de proposito")

    monkeypatch.setattr(panel, "run_schedules", explode)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: state())

    # Expired clocks: every tick counts as a FULL pass, with a state query.
    expired_clocks()
    with panel.app.app_context():
        panel._scheduler_tick()   # baseline

    monkeypatch.setattr(panel, "server_status",
                        lambda server, force=False: state(service="inactive"))
    expired_clocks()
    with panel.app.app_context():
        panel._scheduler_tick()

    text = "\n".join(t for _, t in webhooks)
    assert "parou de rodar" in text, "o monitor roda mesmo com a agenda quebrada"
    failures_in_journal = [a for a in panel.recent_alerts(database) if a["status"] == "erro-interno"]
    assert failures_in_journal, "a quebra fica visivel no diario"
    assert "agendamentos" in failures_in_journal[0]["title"], "dizendo qual tarefa caiu"


# ---------------------------------------------------------- baseline when the panel starts

def test_primeira_olhada_do_monitor_so_anota(database, target, webhooks, monkeypatch):
    enable(database, ["caiu", "inacessivel"])
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": True, "service": "inactive", "error": ""})
    with panel.app.app_context():
        panel.monitor_servers(force=True)
    assert len(webhooks) == 0
    assert panel._monitor_state[target["id"]]["service"] == "inactive"


def test_apos_a_linha_de_base_a_mudanca_avisa(database, target, webhooks, monkeypatch):
    enable(database, ["caiu", "inacessivel"])
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": True, "service": "inactive", "error": ""})
    with panel.app.app_context():
        panel.monitor_servers(force=True)

    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": False, "service": "inacessivel", "error": "x"})
    with panel.app.app_context():
        panel.monitor_servers(force=True)
    assert len(webhooks) == 1


def test_servidor_removido_sai_da_memoria_do_monitor(database, target, monkeypatch):
    enable(database, ["caiu", "inacessivel"])
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": True, "service": "inactive", "error": ""})
    with panel.app.app_context():
        panel.monitor_servers(force=True)

    with database:
        database.execute("DELETE FROM servers WHERE id = ?", (target["id"],))
    with panel.app.app_context():
        panel.monitor_servers(force=True)
    assert target["id"] not in panel._monitor_state


# --------------------------------------------------------------- invalid URL does not go out

def test_url_invalida_nao_chega_a_tentar_conexao():
    """The check happens BEFORE any socket: a malformed URL does not turn into a connection
    attempt (nor a timeout wait) hidden behind a network message."""
    assert panel.send_webhook("nao-e-url", "oi").startswith("URL invalida")
    assert panel.send_webhook("", "oi").startswith("URL invalida")
    assert panel.send_webhook("file:///etc/passwd", "oi").startswith("URL invalida")


# ------------------------------------------------------------------------ the screen

@pytest.fixture
def alerts_screen(database, webhooks):
    """A logged-in administrator, empty webhooks database. Returns (client, post, screen)."""
    with database:
        database.execute("DELETE FROM webhooks")
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    cli = panel.app.test_client()
    cli.get("/login")
    with cli.session_transaction() as sess:
        entry = sess.get("csrf", "")
    resp = cli.post("/login", data={"username": "chefe", "password": "senha-do-chefe",
                                    "csrf": entry}, follow_redirects=False)
    assert resp.status_code == 302, f"login falhou (status {resp.status_code})"

    def post(url, data=None):
        d = dict(data or {})
        with cli.session_transaction() as sess:
            d["csrf"] = sess.get("csrf", "")
        return cli.post(url, data=d, follow_redirects=False)

    def screen():
        return cli.get("/alerts").get_data(as_text=True)

    return cli, post, screen


def test_tela_sem_destino_nenhum(alerts_screen):
    cli, _postar, screen = alerts_screen
    assert cli.get("/alerts").status_code == 200
    assert "nenhum destino ligado" in screen()


SECRET_URL = "https://discord.com/api/webhooks/123/tok-que-nao-pode-vazar"


@pytest.fixture
def registered_target(database, alerts_screen):
    """An "Equipe" destination registered through the screen, with the secret URL above."""
    _cli, post, _screen = alerts_screen
    resp = post("/alerts/targets", {"name": "Equipe", "enabled": "1", "url": SECRET_URL,
                                        "events": ["caiu", "disco-cheio"]})
    assert resp.status_code == 302
    return panel.webhook_list(database)[0]["id"]


def test_url_torta_nao_vira_destino(database, alerts_screen, registered_target):
    _cli, post, _screen = alerts_screen
    post("/alerts/targets", {"name": "Torto", "url": "nao-e-url"})
    assert len(panel.webhook_list(database)) == 1


def test_destino_aparece_pelo_nome_sem_o_token(alerts_screen, registered_target):
    _cli, _postar, screen = alerts_screen
    html = screen()
    assert "Equipe" in html
    assert "tok-que-nao-pode-vazar" not in html, "o token NAO chega ao HTML"
    assert "discord.com/.../123" in html, "o id fica visivel para reconhecer o canal"


def test_salvar_com_url_vazia_mantem_a_url_e_muda_eventos(database, alerts_screen, registered_target):
    _cli, post, _screen = alerts_screen
    hid = registered_target
    # The normal path is to touch only the events: the URL is masked and the replacement
    # field comes empty, so a POST without a URL must NOT clear the saved one.
    post(f"/alerts/targets/{hid}", {"name": "Equipe", "url": "", "enabled": "1",
                                        "events": ["caiu"]})
    current_one = panel.webhook_list(database)[0]
    assert current_one["url"] == SECRET_URL
    assert current_one["events"] == {"caiu"}


def test_sem_a_caixa_ativo_o_destino_desliga(database, alerts_screen, registered_target):
    _cli, post, _screen = alerts_screen
    hid = registered_target
    post(f"/alerts/targets/{hid}", {"name": "Equipe", "url": "", "events": ["caiu"]})
    assert panel.webhook_list(database)[0]["enabled"] is False


def test_dois_destinos_tem_grupos_de_caixas_separados(database, alerts_screen, registered_target):
    _cli, post, screen = alerts_screen
    hid = registered_target
    post(f"/alerts/targets/{hid}", {"name": "Equipe", "url": "", "enabled": "1", "events": ["caiu"]})
    post("/alerts/targets", {"name": "Geral", "enabled": "1",
                                 "url": "https://discord.com/api/webhooks/999/outro",
                                 "events": ["caiu"]})
    html = screen()
    assert "Equipe" in html
    assert "Geral" in html
    # Each destination needs its own checkbox id: if repeated, clicking the label of one
    # would tick the other's event.
    assert f'id="h{hid}-caiu"' in html
    assert f'id="h{hid + 1}-caiu"' in html


def test_testar_usa_a_url_digitada_ou_a_salva(alerts_screen, registered_target, webhooks):
    """Testing is for checking a URL BEFORE saving: if one was typed, that one is
    used; with nothing typed, it tests the saved one."""
    _cli, post, _screen = alerts_screen
    hid = registered_target

    webhooks.clear()
    post(f"/alerts/targets/{hid}/test", {"url": "https://novo.invalid/hook"})
    assert [u for u, _ in webhooks] == ["https://novo.invalid/hook"]

    webhooks.clear()
    post(f"/alerts/targets/{hid}/test", {"url": ""})
    assert [u for u, _ in webhooks] == [SECRET_URL]


def test_limites_de_recurso_pela_tela(database, alerts_screen):
    _cli, post, screen = alerts_screen
    post("/alerts", {"disk_pct": "80"})
    assert panel.webhook_config(database)["disk"] == 80

    post("/alerts", {"disk_pct": "10"})
    assert panel.webhook_config(database)["disk"] == 80, "fora da faixa e recusado, o anterior fica"

    post("/alerts", {"disk_pct": "80", "mem_pct": "85", "cpu_pct": "70"})
    assert panel.webhook_config(database)["memory"] == 85
    assert panel.webhook_config(database)["cpu"] == 70

    # A rejected limit must not leave the other two already saved: the screen comes back
    # saying "rejected" and the operator would have no way to know half the change went through.
    post("/alerts", {"disk_pct": "75", "mem_pct": "10", "cpu_pct": "95"})
    assert panel.webhook_config(database)["memory"] == 85, "fora da faixa, nada muda junto"
    assert panel.webhook_config(database)["disk"] == 80
    assert panel.webhook_config(database)["cpu"] == 70

    html = screen()
    assert 'name="mem_pct"' in html
    assert 'name="cpu_pct"' in html
    assert 'value="85"' in html
    assert 'value="70"' in html
    assert "memoria-alta" in html
    assert "cpu-alta" in html


def test_remover_tira_da_lista(database, alerts_screen, registered_target):
    _cli, post, _screen = alerts_screen
    post(f"/alerts/targets/{registered_target}/delete")
    assert len(panel.webhook_list(database)) == 0


def test_alerta_ligado_sem_onde_olhar_avisa_na_tela(database, alerts_screen):
    """Event on with no server to watch: the screen has to say so out
    loud. An alert that is on and mute is worse than off - the silent channel passes for
    "all is well"."""
    _cli, _postar, screen = alerts_screen
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Sem consulta', '10.0.0.7', 22, 'root', 'x.service', ?)",
            (panel.now_iso(),))
        database.execute("INSERT INTO webhooks (name, url, events, enabled, created_at)"
                     " VALUES ('x', 'http://x.invalid', 'travou,erro-no-log', 1, ?)",
                     (panel.now_iso(),))
    missing = panel.alerts_without_baseline(database)
    assert sorted(missing) == ["erro-no-log", "travou"]
    assert "Ligado, mas sem onde olhar" in screen()


def test_configurar_o_que_faltava_tira_o_aviso(database, alerts_screen):
    _cli, _postar, screen = alerts_screen
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Sem consulta', '10.0.0.7', 22, 'root', 'x.service', ?)",
            (panel.now_iso(),))
        database.execute("INSERT INTO webhooks (name, url, events, enabled, created_at)"
                     " VALUES ('x', 'http://x.invalid', 'travou,erro-no-log', 1, ?)",
                     (panel.now_iso(),))
        database.execute("UPDATE servers SET player_source = 'a2s', query_port = 27015,"
                     " error_re = 'Fatal error'")
    assert panel.alerts_without_baseline(database) == {}
    assert "Ligado, mas sem onde olhar" not in screen()


def test_cadastro_grava_e_valida_a_expressao_de_erro(database, alerts_screen):
    """The registration must save the error expression: without it the log alert never turns on."""
    cli, post, _screen = alerts_screen
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Sem consulta', '10.0.0.7', 22, 'root', 'x.service', ?)",
            (panel.now_iso(),))
    fresh_sid = database.execute("SELECT id FROM servers").fetchone()["id"]

    post(f"/servers/{fresh_sid}/edit", {
        "name": "Sem consulta", "host": "10.0.0.7", "ssh_port": "22", "ssh_user": "root",
        "service": "x.service", "player_source": "none", "error_re": "Out of memory"})
    assert database.execute("SELECT error_re FROM servers WHERE id = ?",
                        (fresh_sid,)).fetchone()["error_re"] == "Out of memory"

    post(f"/servers/{fresh_sid}/edit", {
        "name": "Sem consulta", "host": "10.0.0.7", "ssh_port": "22", "ssh_user": "root",
        "service": "x.service", "player_source": "none", "error_re": "("})
    assert database.execute("SELECT error_re FROM servers WHERE id = ?", (fresh_sid,)).fetchone()[
        "error_re"] == "Out of memory", "expressao que nao compila e recusada no cadastro"

    form = cli.get(f"/servers/{fresh_sid}/edit").get_data(as_text=True)
    assert 'name="error_re"' in form
    assert "Out of memory" in form
    assert 'name="error_re"' in cli.get("/servers/new").get_data(as_text=True)


def test_operador_nao_chega_em_alertas(database, alerts_screen):
    """The screen touches credentials: operators do not get in."""
    panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERATOR)
    other = panel.app.test_client()
    other.get("/login")
    with other.session_transaction() as sess:
        e2 = sess.get("csrf", "")
    other.post("/login", data={"username": "peao", "password": "senha-do-peao", "csrf": e2})
    assert other.get("/alerts").status_code in (302, 403)
