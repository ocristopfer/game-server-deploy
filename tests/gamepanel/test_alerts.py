#!/usr/bin/env python3
"""Testes dos alertas por webhook.

    pytest admin/test_alerts.py

O envio de verdade e trocado por um capturador (fixture `webhooks`, em conftest.py): o
que se testa aqui e QUANDO o painel decide avisar, que e onde mora a chance de errar.
Alerta a mais vira ruido e o canal deixa de ser lido; alerta a menos e um servidor caido
as 3h que ninguem descobre.
"""
import time
from datetime import datetime, timedelta, timezone

import pytest

from gamepanel import app as panel

URL = "http://exemplo.invalid/hook"


def destino(banco, url, eventos, nome="Teste", ativo=1) -> int:
    """Cadastra um destino e devolve o id."""
    with banco:
        cur = banco.execute(
            "INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
            " VALUES (?, ?, ?, ?, ?)",
            (nome, url, ",".join(eventos), ativo, panel.now_iso()))
    return cur.lastrowid


def liga(banco, eventos, disco=90, memoria=90, cpu=90):
    """Deixa UM destino cadastrado, com estes eventos. O padrao da maioria dos testes."""
    with banco:
        banco.execute("DELETE FROM webhooks")
    destino(banco, URL, eventos)
    panel.config_set(banco, "webhook_disk_pct", str(disco))
    panel.config_set(banco, "webhook_mem_pct", str(memoria))
    panel.config_set(banco, "webhook_cpu_pct", str(cpu))


def relogios_vencidos():
    """Poe os relogios do monitor num passado que vence qualquer limite.

    Zera-los nao serve: time.monotonic() conta desde o boot da MAQUINA, e num container
    recem-subido o zero pode estar a menos de um minuto de distancia — ai o monitor sai
    cedo e o teste falha por causa do uptime de quem rodou, nao do codigo.
    """
    panel._last_monitor = panel._last_state = time.monotonic() - 3600


def estado(reachable=True, service="active", error="", restarts=0, result="", sub=""):
    return {"reachable": reachable, "service": service, "error": error,
            "restarts": restarts, "result": result, "sub": sub}


# Servidor de exemplo SEM linha na tabela `servers`: as duas primeiras secoes so
# exercitam `_alerta_de_estado`, que consulta `jobs` por `server_id` - uma tabela vazia
# devolve "sem job recente" sem precisar de FK nenhuma satisfeita.
SERVIDOR = {"id": 1, "name": "Palworld", "host": "10.0.0.9", "ssh_user": "root",
            "service": "palworld.service"}


@pytest.fixture
def alvo(banco):
    """O servidor de teste, de fato cadastrado. Devolve o dict que as funcoes de
    alerta usam, com o id real - para os testes que dependem de FK (jobs, streams)."""
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Palworld', '10.0.0.9', 22, 'root', 'palworld.service', ?)",
            (panel.now_iso(),))
    sid = banco.execute("SELECT id FROM servers").fetchone()["id"]
    return dict(SERVIDOR, id=sid)


# ------------------------------------------------------------------- configuracao

def test_configuracao_le_destino_e_evento_do_banco(banco):
    liga(banco, ["caiu"])
    cfg = panel.webhook_config(banco)
    assert [d["url"] for d in cfg["ativos"]] == [URL]
    assert cfg["eventos"] == {"caiu"}


def test_evento_desconhecido_no_banco_e_descartado(banco):
    """Banco mexido a mao (ou versao antiga) nao pode virar chave desconhecida."""
    liga(banco, ["caiu"])
    with banco:
        banco.execute("UPDATE webhooks SET eventos = 'caiu,formatar-o-disco'")
    assert panel.webhook_config(banco)["eventos"] == {"caiu"}


def test_limites_tem_piso_e_padrao_para_valor_ilegivel(banco):
    liga(banco, ["caiu"])
    panel.config_set(banco, "webhook_disk_pct", "5")
    assert panel.webhook_config(banco)["disco"] == 50, "limite de disco tem piso"
    panel.config_set(banco, "webhook_disk_pct", "nao e numero")
    assert panel.webhook_config(banco)["disco"] == panel.DISK_PCT_DEFAULT
    panel.config_set(banco, "webhook_mem_pct", "5")
    assert panel.webhook_config(banco)["memoria"] == 50, "limite de memoria tem piso"
    panel.config_set(banco, "webhook_cpu_pct", "vazio")
    assert panel.webhook_config(banco)["cpu"] == panel.CPU_PCT_DEFAULT


# ---------------------------------------------------------------------- varios destinos

@pytest.fixture
def tres_destinos(banco):
    """O ponto do recurso: dois canais ativos com listas diferentes, mais um desligado."""
    with banco:
        banco.execute("DELETE FROM webhooks")
    equipe = destino(banco, "http://equipe.invalid/hook", ["caiu", "voltou"], "Equipe")
    geral = destino(banco, "http://geral.invalid/hook", ["caiu"], "Geral")
    mudo = destino(banco, "http://mudo.invalid/hook", ["caiu"], "Desligado", ativo=0)
    return {"equipe": equipe, "geral": geral, "mudo": mudo}


def test_evento_pedido_pelos_dois_sai_duas_vezes(banco, tres_destinos, webhooks):
    enviou = panel.notify(banco, "caiu", "caiu")
    assert (enviou, len(webhooks)) == (True, 2)
    assert sorted(u for u, _ in webhooks) == [
        "http://equipe.invalid/hook", "http://geral.invalid/hook"]
    assert all("mudo.invalid" not in u for u, _ in webhooks), "destino desligado nao recebe"


def test_evento_de_um_so_sai_uma_vez(banco, tres_destinos, webhooks):
    panel.notify(banco, "voltou", "voltou")
    assert [u for u, _ in webhooks] == ["http://equipe.invalid/hook"]


def test_evento_que_ninguem_pediu_nao_sai(banco, tres_destinos, webhooks):
    enviou = panel.notify(banco, "disco-cheio", "disco")
    assert (enviou, len(webhooks)) == (False, 0)


def test_uniao_dos_destinos_ligados_e_o_que_o_monitor_observa(banco, tres_destinos):
    assert panel.webhook_config(banco)["eventos"] == {"caiu", "voltou"}


def test_destino_quebrado_nao_impede_os_outros(banco, tres_destinos, webhooks, monkeypatch):
    """Um destino fora do ar nao pode calar os outros: o Discord de pe continua
    recebendo mesmo com o Slack recusando a conexao."""
    def parcial(url, texto):
        if "equipe" in url:
            webhooks.append((url, texto))
            return ""
        return "recusou a conexao"

    monkeypatch.setattr(panel, "send_webhook", parcial)
    enviou = panel.notify(banco, "caiu", "caiu")
    assert (enviou, len(webhooks)) == (True, 1)


def test_todos_desligados_nada_sai(banco, tres_destinos, webhooks):
    with banco:
        banco.execute("UPDATE webhooks SET ativo = 0")
    enviou = panel.notify(banco, "caiu", "caiu")
    assert (enviou, len(webhooks)) == (False, 0)


# --------------------------------------------------------- URL nao aparece na tela

def test_mascara_url_esconde_o_token_mas_nao_o_canal():
    """A URL e uma credencial: quem le a tela por cima do ombro nao pode sair de la
    podendo escrever no canal."""
    mascarada = panel.mask_url(
        "https://discord.com/api/webhooks/1544786528700604457/segredo-que-nao-pode-vazar")
    assert "segredo-que-nao-pode-vazar" not in mascarada
    assert "1544786528700604457" in mascarada, "o id continua visivel para reconhecer o canal"
    assert mascarada.startswith("discord.com")


def test_mascara_url_vazia_nao_vira_mascara():
    assert panel.mask_url("") == ""


# ------------------------------------------------------ quando o painel decide avisar

def test_queda_avisa(banco, webhooks):
    liga(banco, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(banco, SERVIDOR, estado(service="inactive"),
                            estado(service="active"))
    assert len(webhooks) == 1
    assert "Palworld" in webhooks[0][1]
    assert "palworld.service" in webhooks[0][1]


def test_volta_avisa(banco, webhooks):
    liga(banco, ["caiu", "voltou"])
    panel._state_alert(banco, SERVIDOR, estado(service="active"),
                            estado(service="inactive"))
    assert len(webhooks) == 1


def test_nada_mudou_nada_sai(banco, webhooks):
    liga(banco, ["caiu", "voltou"])
    panel._state_alert(banco, SERVIDOR, estado(service="active"), estado(service="active"))
    assert len(webhooks) == 0


def test_perder_contato_avisa_com_o_motivo(banco, webhooks):
    liga(banco, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(banco, SERVIDOR,
                            estado(reachable=False, service="inacessivel", error="timeout"),
                            estado(service="active"))
    assert len(webhooks) == 1
    assert "timeout" in webhooks[0][1]


def test_sem_contato_nao_acumula_alerta_de_servico(banco, webhooks):
    """O painel nao sabe o que o servico esta fazendo sem contato: avisar 'caiu' junto
    seria inventar. Sai UMA mensagem, a do contato."""
    liga(banco, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(banco, SERVIDOR, estado(reachable=False, service="inacessivel"),
                            estado(reachable=True, service="active"))
    assert len(webhooks) == 1


def test_continua_sem_contato_nao_repete(banco, webhooks):
    liga(banco, ["caiu", "voltou", "inacessivel", "acessivel"])
    panel._state_alert(banco, SERVIDOR, estado(reachable=False, service="inacessivel"),
                            estado(reachable=False, service="inacessivel"))
    assert len(webhooks) == 0


def test_evento_desligado_na_tela_nao_sai(banco, webhooks):
    liga(banco, ["voltou"])
    panel._state_alert(banco, SERVIDOR, estado(service="inactive"),
                            estado(service="active"))
    assert len(webhooks) == 0


def test_sem_destino_nao_sai_nada(banco):
    with banco:
        banco.execute("DELETE FROM webhooks")
    assert panel.notify(banco, "caiu", "titulo", "detalhe") is False


# -------------------------------------------------------- acao do painel nao vira susto

def test_sem_job_recente_a_queda_e_queda(banco, alvo):
    assert not panel._job_recente(banco, alvo["id"])


def test_restart_pelo_painel_abre_a_janela_de_silencio(banco, alvo):
    with banco:
        banco.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (alvo["id"], "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
    assert panel._job_recente(banco, alvo["id"])


def test_reiniciar_pelo_botao_nao_vira_alerta(banco, alvo, webhooks):
    liga(banco, ["caiu"])
    with banco:
        banco.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (alvo["id"], "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
    panel._state_alert(banco, alvo, estado(service="inactive"), estado(service="active"))
    assert len(webhooks) == 0


def test_job_velho_nao_segura_o_alerta_para_sempre(banco, alvo, webhooks):
    liga(banco, ["caiu"])
    antigo = (datetime.now(timezone.utc) - timedelta(seconds=panel.ALERT_QUIET + 60)).isoformat()
    with banco:
        banco.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (alvo["id"], "root@10.0.0.9", "restart", "ok", "admin", antigo))
    assert not panel._job_recente(banco, alvo["id"])
    panel._state_alert(banco, alvo, estado(service="inactive"), estado(service="active"))
    assert len(webhooks) == 1, "passada a janela, a queda avisa"


# ------------------------------------------------------- o jogo, nao o servico
# O buraco que estas tres secoes cobrem: "servico rodando" nao e "jogo funcionando". Um
# jogo pode estar travado, caindo em loop ou cuspindo erro no log com o systemd achando
# que esta tudo bem — e ate aqui nada disso virava alerta.

def test_servico_em_failed_avisa_que_quebrou(banco, alvo, webhooks):
    liga(banco, ["caiu", "quebrou"])
    panel._state_alert(banco, alvo, estado(service="failed", result="exit-code"),
                            estado(service="active"))
    assert len(webhooks) == 1
    assert "quebrou" in webhooks[0][1], "a mensagem diz que QUEBROU, nao que pararam"
    assert "exit-code" in webhooks[0][1]


def test_quebrar_logo_apos_a_acao_do_painel_ainda_avisa(banco, alvo, webhooks):
    """Parar pelo painel e 'inactive' e cai na janela de silencio. Terminar em 'failed'
    logo depois de uma acao e outra coisa: foi a acao que quebrou o jogo, e e o caso em
    que mais se quer saber."""
    liga(banco, ["caiu", "quebrou"])
    with banco:
        banco.execute(
            "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (alvo["id"], "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
    panel._state_alert(banco, alvo, estado(service="inactive"), estado(service="active"))
    assert len(webhooks) == 0, "parar pelo painel continua silencioso"
    panel._state_alert(banco, alvo, estado(service="failed"), estado(service="active"))
    assert len(webhooks) == 1, "mas quebrar logo apos a acao avisa"


def test_loop_de_restart(banco, alvo, webhooks):
    liga(banco, ["reiniciando"])
    anterior = {"reachable": True, "service": "active", "restarts": 2}

    panel._restart_alert(banco, alvo, estado(restarts=5), anterior)
    assert len(webhooks) == 1
    assert "3x" in webhooks[0][1], "a mensagem diz quantas vezes"

    # Enquanto o contador continua subindo e o MESMO episodio: avisar a cada volta
    # seria o spam que a regra da mudanca existe para evitar.
    webhooks.clear()
    panel._restart_alert(banco, alvo, estado(restarts=8), anterior)
    assert len(webhooks) == 0, "continua subindo, nao repete"

    # Uma volta inteira sem restart novo fecha o episodio.
    panel._restart_alert(banco, alvo, estado(restarts=8), anterior)
    assert not anterior["loop_avisado"], "volta sem restart destrava o alerta"
    webhooks.clear()
    panel._restart_alert(banco, alvo, estado(restarts=11), anterior)
    assert len(webhooks) == 1, "um loop novo volta a avisar"

    # `systemctl restart` na mao zera o NRestarts. Isso e linha de base nova, nao um loop.
    webhooks.clear()
    panel._restart_alert(banco, alvo, estado(restarts=0), anterior)
    assert len(webhooks) == 0, "contador zerado nao vira alerta"
    assert anterior["restarts"] == 0, "e a linha de base acompanha"


def test_jogo_de_pe_mas_mudo(banco, alvo, webhooks, monkeypatch):
    """So quem responde a uma sondagem de verdade pode ficar mudo."""
    liga(banco, ["travou", "respondeu"])
    sondado = dict(alvo, player_source="a2s", query_port=27015)
    mudez = {"reachable": True, "service": "active", "restarts": 0}
    resposta = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: resposta)

    for _ in range(panel.MUTE_ROUNDS - 1):
        panel._mute_alert(banco, sondado, estado(), mudez)
    assert len(webhooks) == 0, "nao avisa no primeiro silencio (UDP perde pacote)"
    panel._mute_alert(banco, sondado, estado(), mudez)
    assert len(webhooks) == 1, f"avisa na volta {panel.MUTE_ROUNDS}"
    assert "nao responde" in webhooks[0][1], "a mensagem separa 'rodando' de 'respondendo'"

    webhooks.clear()
    panel._mute_alert(banco, sondado, estado(), mudez)
    assert len(webhooks) == 0, "continua mudo, nao repete"


def test_voltar_a_responder_avisa_uma_vez(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["travou", "respondeu"])
    sondado = dict(alvo, player_source="a2s", query_port=27015)
    mudez = {"reachable": True, "service": "active", "restarts": 0}
    resposta = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: resposta)
    for _ in range(panel.MUTE_ROUNDS):
        panel._mute_alert(banco, sondado, estado(), mudez)

    webhooks.clear()
    resposta_ok = {"configured": True, "error": "", "players": 4, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: resposta_ok)
    panel._mute_alert(banco, sondado, estado(), mudez)
    assert len(webhooks) == 1, "voltou a responder, avisa uma vez"
    panel._mute_alert(banco, sondado, estado(), mudez)
    assert len(webhooks) == 1, "e nao fica repetindo o alivio"


def test_servico_subindo_nao_conta_como_mudez(banco, alvo, webhooks, monkeypatch):
    """Jogo carregando mapa nao responde e nao pode virar alerta: a contagem so comeca
    com o servico ativo e fora da janela de silencio."""
    liga(banco, ["travou", "respondeu"])
    sondado = dict(alvo, player_source="a2s", query_port=27015)
    resposta = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: resposta)
    mudez = {"reachable": True, "service": "active", "restarts": 0, "mudo": 0}
    for _ in range(panel.MUTE_ROUNDS + 2):
        panel._mute_alert(banco, sondado, estado(service="activating"), mudez)
    assert len(webhooks) == 0


def test_contagem_por_log_nao_gera_alerta_de_mudez(banco, alvo, webhooks):
    """Contagem por log nao pergunta nada ao jogo: nao ha o que ficar mudo."""
    liga(banco, ["travou", "respondeu"])
    por_log = dict(alvo, player_source="log", query_port=0)
    for _ in range(panel.MUTE_ROUNDS + 2):
        panel._mute_alert(banco, por_log, estado(), {"service": "active"})
    assert len(webhooks) == 0


# --------------------------------------------------------- entrada e saida de jogadores

@pytest.fixture
def srv_jogadores(alvo):
    return dict(alvo, player_source="log", query_port=0)


def _cfg(banco, eventos):
    liga(banco, eventos)
    return panel.webhook_config(banco)


def test_primeira_olhada_so_anota_linha_de_base(banco, srv_jogadores, webhooks, monkeypatch):
    cfg = _cfg(banco, ["jogador-entrou", "jogador-saiu"])
    res = {"configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: res)
    memoria = {"reachable": True, "service": "active"}

    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)
    assert len(webhooks) == 0
    assert memoria["jogadores_nomes"] == {"Cristopfer"}


def test_sem_mudanca_de_jogadores_nao_avisa(banco, srv_jogadores, webhooks, monkeypatch):
    cfg = _cfg(banco, ["jogador-entrou", "jogador-saiu"])
    res = {"configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: res)
    memoria = {"reachable": True, "service": "active"}
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)  # linha de base

    webhooks.clear()
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)
    assert len(webhooks) == 0


def test_jogador_novo_avisa_entrada(banco, srv_jogadores, webhooks, monkeypatch):
    cfg = _cfg(banco, ["jogador-entrou", "jogador-saiu"])
    memoria = {"reachable": True, "service": "active"}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]})
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)  # linha de base

    webhooks.clear()
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 2,
        "list": [{"name": "Cristopfer"}, {"name": "Ana"}]})
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)
    assert len(webhooks) == 1
    assert "Ana entrou no jogo" in webhooks[0][1]
    assert "2 jogadores online" in webhooks[0][1]


def test_jogador_saindo_avisa_saida(banco, srv_jogadores, webhooks, monkeypatch):
    cfg = _cfg(banco, ["jogador-entrou", "jogador-saiu"])
    memoria = {"reachable": True, "service": "active", "jogadores_nomes": {"Cristopfer", "Ana"},
               "jogadores_count": 2}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]})
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)
    assert len(webhooks) == 1
    assert "Ana saiu do jogo" in webhooks[0][1]


def test_ultimo_jogador_saindo_avisa(banco, srv_jogadores, webhooks, monkeypatch):
    cfg = _cfg(banco, ["jogador-entrou", "jogador-saiu"])
    memoria = {"reachable": True, "service": "active", "jogadores_nomes": {"Cristopfer"},
               "jogadores_count": 1}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)
    assert len(webhooks) == 1
    assert "nenhum jogador online" in webhooks[0][1]


def test_contagem_numerica_sem_nomes_avisa_variacao(banco, srv_jogadores, webhooks, monkeypatch):
    """Servidor so com contagem (sem nomes)."""
    cfg = _cfg(banco, ["jogador-entrou", "jogador-saiu"])
    memoria = {"reachable": True, "service": "active"}
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)  # linha de base

    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 3, "list": []})
    panel._players_alert(banco, srv_jogadores, "active", memoria, cfg)
    assert len(webhooks) == 1
    assert "3 jogadores conectaram" in webhooks[0][1]


def test_servico_parado_nao_dispara_alerta_de_saida_e_reseta(banco, srv_jogadores, webhooks):
    cfg = _cfg(banco, ["jogador-entrou", "jogador-saiu"])
    memoria = {"reachable": True, "service": "active",
               "jogadores_nomes": {"Cristopfer"}, "jogadores_count": 1}
    panel._players_alert(banco, srv_jogadores, "failed", memoria, cfg)
    assert len(webhooks) == 0
    assert memoria["jogadores_nomes"] is None, "a memoria reseta"


# --------------------------------------------------- a volta rapida do monitor
# Jogador entrando precisa chegar em segundos, nao no minuto seguinte: quem recebe o
# aviso costuma querer entrar junto. A volta rapida existe para isso — e ela nao pode
# custar SSH, senao acelerar o alerta multiplicaria a conta de todo o resto.

@pytest.fixture
def monitor_a2s(banco, alvo, monkeypatch):
    """O servidor cadastrado com A2S: consulta direta ao jogo, sem SSH."""
    liga(banco, ["jogador-entrou", "jogador-saiu", "caiu"])
    with banco:
        banco.execute("UPDATE servers SET player_source = 'a2s', query_port = 27015")

    idas_de_ssh = []

    def status_contado(server, force=False):
        idas_de_ssh.append(int(server["id"]))
        return estado()

    monkeypatch.setattr(panel, "server_status", status_contado)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})
    return idas_de_ssh


def test_volta_completa_consulta_o_systemd(banco, monitor_a2s):
    with panel.app.app_context():
        # Relogios vencidos = volta COMPLETA. Sao precisas duas: a primeira anota o
        # estado do servidor, a segunda a linha de base dos jogadores.
        relogios_vencidos()
        panel.monitor_servers()
        relogios_vencidos()
        panel.monitor_servers()
    assert len(monitor_a2s) == 2


def test_entrada_chega_na_volta_rapida_sem_ssh(banco, monitor_a2s, webhooks, monkeypatch):
    with panel.app.app_context():
        relogios_vencidos()
        panel.monitor_servers()
        relogios_vencidos()
        panel.monitor_servers()
    monitor_a2s.clear()

    # Os relogios recuam 20s: o do estado (60s) ainda nao venceu, o dos jogadores (15s)
    # sim — que e exatamente a situacao no meio de dois minutos.
    recuo = time.monotonic() - 20
    monkeypatch.setattr(panel, "_last_monitor", recuo)
    monkeypatch.setattr(panel, "_last_state", recuo)
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 1, "list": [{"name": "Ana"}]})
    with panel.app.app_context():
        panel.monitor_servers()
    assert any("Ana entrou no jogo" in t for _, t in webhooks)
    assert monitor_a2s == [], "e ela nao gastou nenhuma ida de SSH"


def test_contagem_por_log_nao_entra_na_volta_curta(banco, alvo, webhooks, monkeypatch):
    """Cada leitura por log e uma ida de SSH que arrasta o arquivo inteiro; a 15s isso
    viraria megabytes por minuto para achar duas linhas. Quem conta por log espera a
    volta completa."""
    liga(banco, ["jogador-entrou", "jogador-saiu", "caiu"])
    with banco:
        banco.execute("UPDATE servers SET player_source = 'log', query_port = 0")
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: estado())
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 0, "list": []})

    with panel.app.app_context():
        # Duas completas para ter linha de base: a primeira anota o estado, a segunda
        # os jogadores (servidor vazio).
        relogios_vencidos()
        panel.monitor_servers()
        relogios_vencidos()
        panel.monitor_servers()

    # Chegou gente, mas so o relogio curto venceu: por log, o painel nao vai atras.
    monkeypatch.setattr(panel, "server_players", lambda server, force=False: {
        "configured": True, "error": "", "players": 2,
        "list": [{"name": "Ana"}, {"name": "Bea"}]})
    monkeypatch.setattr(panel, "_last_monitor", time.monotonic() - 20)
    with panel.app.app_context():
        panel.monitor_servers()
    assert len(webhooks) == 0

    # ...mas na volta completa seguinte ela avisa normalmente.
    relogios_vencidos()
    with panel.app.app_context():
        panel.monitor_servers()
    assert any("entrou no jogo" in t for _, t in webhooks)


def test_sem_alerta_de_jogador_20s_ainda_nao_e_hora(banco, alvo, monkeypatch):
    """O passo curto so existe por causa do evento de jogador. Sem ele os mesmos 20s
    nao bastam, e o monitor continua no ritmo de antes — ninguem paga SSH a mais de graca."""
    liga(banco, ["caiu"])
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: estado())
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    recuo = time.monotonic() - 20
    monkeypatch.setattr(panel, "_last_monitor", recuo)
    monkeypatch.setattr(panel, "_last_state", recuo)
    with panel.app.app_context():
        assert panel.monitor_servers() == 0


# ------------------------------------------------------------------- erro no log

def test_erro_no_log_do_jogo(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["erro-no-log"])
    lines_of = ["tudo bem por aqui", "Fatal error: world corrupted", "seguindo"]
    monkeypatch.setattr(panel, "read_log_lines", lambda server, limit=0: lines_of)
    com_regex = dict(alvo, error_re="Fatal error")
    memoria = {}

    panel._log_alert(banco, com_regex, memoria)
    assert len(webhooks) == 1
    assert "world corrupted" in webhooks[0][1], "leva a linha inteira"

    # A mesma linha continua no rabo do log na volta seguinte. Avisar de novo seria um
    # alerta por minuto ate alguem arrumar.
    webhooks.clear()
    panel._log_alert(banco, com_regex, memoria)
    assert len(webhooks) == 0, "a mesma linha nao avisa duas vezes"

    # Cooldown: mesmo com linha nova, o canal nao leva uma enxurrada de uma expressao larga.
    monkeypatch.setattr(panel, "read_log_lines",
                        lambda server, limit=0: ["Fatal error: outra coisa"])
    webhooks.clear()
    panel._log_alert(banco, com_regex, memoria)
    assert len(webhooks) == 0, "linha nova dentro da janela nao passa"
    assert "outra coisa" in memoria["ultimo_erro"], "mas a memoria acompanha a linha nova"

    # Passada a janela, um erro novo volta a avisar.
    memoria["erro_em"] = 0
    monkeypatch.setattr(panel, "read_log_lines",
                        lambda server, limit=0: ["Fatal error: mais uma"])
    webhooks.clear()
    panel._log_alert(banco, com_regex, memoria)
    assert len(webhooks) == 1, "passado o cooldown, avisa de novo"

    monkeypatch.setattr(panel, "read_log_lines",
                        lambda server, limit=0: ["nada de mais aqui"])
    webhooks.clear()
    panel._log_alert(banco, com_regex, memoria)
    assert len(webhooks) == 0, "log limpo nao avisa"
    assert memoria["ultimo_erro"] == "", "e a memoria do erro e esquecida"


def test_erro_no_log_servidor_sem_expressao_nem_le(banco, alvo, webhooks):
    panel._log_alert(banco, alvo, {})
    assert len(webhooks) == 0, "sem expressao, nem chega a ler o log"


def test_erro_no_log_expressao_invalida_nao_estoura(banco, alvo, webhooks):
    """Expressao torta e problema de cadastro, nao motivo para derrubar a volta do monitor."""
    panel._log_alert(banco, dict(alvo, error_re="("), {})
    assert len(webhooks) == 0


# ------------------------------------------------------------------------ disco cheio

def test_disco_cheio(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["disco-cheio"], disco=90)
    discos = {"disks": [{"mount": "/", "pct": 40.0, "used": 4, "total": 10},
                        {"mount": "/opt/game", "pct": 95.0, "used": 95, "total": 100}]}
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: discos)

    # A memoria do monitor NAO pode ser zerada entre as chamadas: e justamente ela que
    # guarda "este disco ja estava cheio da ultima vez".
    panel._disk_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 1
    assert "/opt/game" in webhooks[0][1], "avisa sobre o disco MAIS cheio, nao o primeiro"

    # Um disco a 95% continua a 95% no minuto seguinte: avisar de novo seria spam.
    webhooks.clear()
    panel._disk_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "continua cheio, nao repete"

    # Depois de liberar espaco a marca cai, e uma nova subida volta a avisar.
    discos["disks"] = [{"mount": "/opt/game", "pct": 40.0, "used": 40, "total": 100}]
    panel._disk_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "voltar ao normal nao avisa (esse evento nao existe)"
    discos["disks"] = [{"mount": "/opt/game", "pct": 97.0, "used": 97, "total": 100}]
    panel._disk_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 1, "encheu de novo, avisa de novo"

    # Medidor que falhou nao pode virar alerta de disco vazio nem estourar.
    monkeypatch.setattr(panel, "server_metrics",
                        lambda server, force=False: {"error": "tempo esgotado"})
    webhooks.clear()
    panel._disk_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "medidor com erro nao avisa nada"

    # ...e nao pode apagar a marca de que o disco estava cheio.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "disks": [{"mount": "/opt/game", "pct": 97.0, "used": 97, "total": 100}]})
    panel._disk_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "depois de um erro no medidor, o disco cheio nao repete"


# ------------------------------------------------------------------- memoria quase cheia

GIB = 1024 ** 3


def test_memoria_quase_cheia(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["memoria-alta"], memoria=90)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 95.0, "used": 3.8 * GIB, "total": 4.0 * GIB}})

    # Como no disco, a memoria do monitor NAO pode ser zerada entre as chamadas.
    panel._memory_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 1
    assert "95.0%" in webhooks[0][1]
    assert "3.8 GB" in webhooks[0][1]
    assert "4.0 GB" in webhooks[0][1]

    webhooks.clear()
    panel._memory_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "continua cheia, nao repete"

    # Liberou memoria: a marca cai e uma nova subida volta a avisar.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 40.0, "used": 1.6 * GIB, "total": 4.0 * GIB}})
    panel._memory_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "baixou, nao avisa (esse evento nao existe)"
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 97.0, "used": 3.9 * GIB, "total": 4.0 * GIB}})
    panel._memory_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 1, "encheu de novo, avisa de novo"

    # Medidor que falhou nao pode virar alerta nem estourar...
    monkeypatch.setattr(panel, "server_metrics",
                        lambda server, force=False: {"error": "tempo esgotado"})
    webhooks.clear()
    panel._memory_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "medidor com erro nao avisa nada"

    # ...e nao pode apagar a marca de que a memoria estava cheia.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": 97.0, "used": 3.9 * GIB, "total": 4.0 * GIB}})
    panel._memory_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "depois de um erro no medidor, a memoria cheia nao repete"


def test_memoria_sem_medida_valida_nao_avisa(banco, alvo, webhooks, monkeypatch):
    """Container sem teto de memoria legivel devolve pct None. Comparar None com o
    limite estouraria a volta inteira do monitor, e tratar como 0 esconderia o problema."""
    liga(banco, ["memoria-alta"], memoria=90)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "mem": {"pct": None, "used": 0, "total": 0}})
    panel._memory_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0


# ------------------------------------------------------------------------- CPU alta

def test_cpu_alta(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["cpu-alta"], cpu=90)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": 94.5, "cores": 4, "proc": {"cpu_pct": 92.1}})

    panel._cpu_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 1
    # Sem os nucleos, "94.5%" nao diz se e uma maquina afogada ou um nucleo de quatro; e
    # sem a fatia do jogo nao da para saber se o culpado e o servidor ou outra coisa.
    assert "94.5%" in webhooks[0][1]
    assert "4 nucleos" in webhooks[0][1]
    assert "jogo: 92.1%" in webhooks[0][1]

    webhooks.clear()
    panel._cpu_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "continua alta, nao repete"

    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": 12.0, "cores": 4, "proc": {}})
    panel._cpu_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "baixou, nao avisa (esse evento nao existe)"

    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": 99.0, "cores": 1, "proc": {}})
    panel._cpu_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 1, "subiu de novo, avisa de novo"
    assert "em 1 nucleo" in webhooks[0][1], "um nucleo so nao vira plural"
    assert "nucleos" not in webhooks[0][1]
    assert "jogo:" not in webhooks[0][1], "sem PID do jogo, a mensagem nao inventa a fatia"

    # Duas amostras sao o minimo para calcular uso de CPU; com uma so o medidor devolve None.
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {
        "cpu_pct": None, "cores": 4, "proc": {}})
    webhooks.clear()
    panel._cpu_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "sem amostra de CPU nao avisa"

    monkeypatch.setattr(panel, "server_metrics",
                        lambda server, force=False: {"error": "tempo esgotado"})
    panel._cpu_alert(banco, alvo, panel.webhook_config(banco))
    assert len(webhooks) == 0, "medidor com erro nao avisa nada"


# ------------------------------------------------------- o monitor liga os tres medidores
# Disco, memoria e CPU saem da mesma leitura e correm no mesmo relogio. E facil ligar o
# evento na tela e esquecer o fio dentro da volta do monitor: entao a volta e testada.

@pytest.fixture
def medidor_apertado(alvo, monkeypatch):
    apertado = {"disks": [{"mount": "/", "pct": 99.0, "used": 99, "total": 100}],
                "mem": {"pct": 99.0, "used": 99, "total": 100},
                "cpu_pct": 99.0, "cores": 2, "proc": {}}
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: apertado)
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: estado())
    return apertado


def test_a_volta_do_monitor_dispara_os_tres(banco, medidor_apertado, webhooks):
    liga(banco, ["disco-cheio", "memoria-alta", "cpu-alta"])
    with panel.app.app_context():
        panel.monitor_servers(forcar=True)   # a primeira volta so anota
        panel.monitor_servers(forcar=True)
    texto = "\n".join(t for _, t in webhooks)
    assert "disco quase cheio" in texto
    assert "memoria quase cheia" in texto
    assert "uso de CPU alto" in texto


def test_evento_desmarcado_nao_sai_de_carona(banco, medidor_apertado, webhooks):
    """O contrario: evento desmarcado na tela nao pode sair de carona nos outros."""
    liga(banco, ["disco-cheio"])
    with panel.app.app_context():
        panel.monitor_servers(forcar=True)
        panel.monitor_servers(forcar=True)
    texto = "\n".join(t for _, t in webhooks)
    assert "disco quase cheio" in texto
    assert "memoria quase cheia" not in texto
    assert "uso de CPU alto" not in texto


# ------------------------------------------------------------------ log em tempo real
# Contagem por log era o unico caso sem jeito de ficar rapida por consulta. A saida foi
# parar de perguntar: uma conexao SSH longa ouvindo o log. O que se testa aqui e QUEM
# ganha essa conexao e QUANDO ela e refeita — o resto e subprocesso, que so o servidor
# de verdade exercita.

def test_linha_de_jogador_reconhece_entrada_e_saida():
    entrar_re = panel.compile_pattern(r"\[server\] Player '(?P<name>[^']+)' logged in",
                                      "entrada")
    sair_re = panel.compile_pattern(r"\[server\] Remove Player '(?P<name>[^']+)'", "saida")
    assert panel._player_line(
        "2026-09-08 10:00:00 [server] Player 'Ana' logged in", entrar_re, sair_re)
    assert panel._player_line(
        "2026-09-08 10:05:00 [server] Remove Player 'Ana'", entrar_re, sair_re)
    assert not panel._player_line(
        "2026-09-08 10:00:01 [server] Saving world chunk 42", entrar_re, sair_re), \
        "ruido do log nao dispara nada"
    # Log de jogo tem linha gigante (stack trace, dump de estado); o corte protege o
    # regex de varrer megabytes por linha.
    assert not panel._player_line(
        "x" * 50000 + " [server] Player 'Ana' logged in", entrar_re, sair_re)


def _srv(sid, **campos):
    base = {"id": sid, "host": "10.0.0.9", "ssh_port": 22, "ssh_user": "root",
            "service": "jogo.service", "log_path": "", "query_port": 0,
            "player_source": "log", "join_re": r"Player '(?P<name>[^']+)' logged in",
            "leave_re": ""}
    return {**base, **campos}


CFG_STREAM = {"eventos": {"jogador-entrou", "jogador-saiu"}}


def test_streams_desejados_so_para_quem_conta_por_log():
    assert sorted(panel.wanted_streams([_srv(1)], CFG_STREAM)) == [1]
    # A2S e HTTP ja respondem de graca na volta curta: abrir conexao permanente para
    # eles seria pagar por nada.
    assert panel.wanted_streams(
        [_srv(1, player_source="a2s", query_port=27015)], CFG_STREAM) == {}
    assert panel.wanted_streams([_srv(1, join_re="")], CFG_STREAM) == {}, \
        "sem padrao de entrada nao ha o que ouvir"
    assert panel.wanted_streams([_srv(1)], {"eventos": {"caiu"}}) == {}


def test_assinatura_de_stream_muda_com_o_cadastro():
    """A assinatura e o que decide refazer a conexao: trocar o regex tem de derrubar a
    antiga, senao o painel segue ouvindo com o padrao velho ate o proximo restart."""
    # Duas chamadas, dois dicts DISTINTOS (mas com o mesmo conteudo): o que se confere
    # e que a assinatura depende dos dados do cadastro, nao da identidade do objeto.
    de_novo = panel._stream_signature(_srv(1))
    assert panel._stream_signature(_srv(1)) == de_novo, "mesmo cadastro, mesma assinatura"
    assert panel._stream_signature(_srv(1)) != panel._stream_signature(
        _srv(1, join_re="outro (?P<name>.+)"))
    assert panel._stream_signature(_srv(1)) != panel._stream_signature(
        _srv(1, log_path="/opt/game/logs/x.log"))
    assert panel._stream_signature(_srv(1)) != panel._stream_signature(
        _srv(1, host="10.0.0.10"))


def test_regex_que_nao_compila_faz_a_thread_desistir():
    """Cadastro invalido nao pode virar laco: a thread desiste, e o supervisor tem de
    respeitar isso em vez de recriar a cada volta para ela morrer igual."""
    morto = panel._LogStream(_srv(9, join_re="("), panel._stream_signature(_srv(9)))
    morto._follow()
    assert morto.gave_up, morto.error
    assert "entrada" in morto.error


# --------------------------------------------------------- supervisor das conexoes de log
# Nenhum SSH de verdade aqui: o que se mede e a decisao de abrir, trocar e fechar.

class _StreamFalso:
    def __init__(self, server, signature, registro):
        self.sid, self.signature = int(server["id"]), signature
        self.gave_up, self._vivo, self.parado = False, True, False
        registro.append(self)

    def start(self):
        pass

    def stop(self):
        self.parado, self._vivo = True, False

    def alive(self):
        return self._vivo


@pytest.fixture
def supervisor_falso(banco, alvo, monkeypatch):
    """Troca `_LogStream` por um dublê que so registra abrir/fechar - sem SSH nenhum."""
    criados = []
    monkeypatch.setattr(
        panel, "_LogStream",
        lambda server, signature: _StreamFalso(server, signature, criados))
    panel._streams.clear()
    liga(banco, ["jogador-entrou", "jogador-saiu"])
    with banco:
        banco.execute("UPDATE servers SET player_source=?, query_port=0, join_re=?",
                     ("log", r"Player (?P<name>\S+) logged in"))
    yield criados
    panel._streams.clear()


def test_supervisiona_streams_abre_uma_conexao_por_servidor(banco, supervisor_falso):
    criados = supervisor_falso
    with panel.app.app_context():
        assert panel.supervise_streams() == 1, "abre uma conexao para o servidor por log"
        assert panel.supervise_streams() == 1, "e nao abre outra na volta seguinte"
    assert len(criados) == 1, "so uma conexao foi criada"


def test_regex_novo_derruba_a_conexao_antiga(banco, supervisor_falso):
    """Trocar o regex no cadastro tem de derrubar a conexao antiga: senao o painel
    segue ouvindo com o padrao velho ate alguem reiniciar o painel."""
    criados = supervisor_falso
    with panel.app.app_context():
        panel.supervise_streams()
    with banco:
        banco.execute("UPDATE servers SET join_re=?", (r"Jogador (?P<name>\S+) entrou",))
    with panel.app.app_context():
        panel.supervise_streams()
    assert criados[0].parado
    assert len(criados) == 2, "e abre outra no lugar"


def test_conexao_morta_e_levantada_de_novo(banco, supervisor_falso):
    """Conexao que morreu sozinha (servidor reiniciou, rede caiu) volta na proxima volta."""
    criados = supervisor_falso
    with panel.app.app_context():
        panel.supervise_streams()
    criados[-1]._vivo = False
    with panel.app.app_context():
        panel.supervise_streams()
    assert len(criados) == 2


def test_quem_desistiu_por_cadastro_invalido_nao_vira_laco(banco, supervisor_falso):
    """Recriar nao conserta regex torto, e a cada volta seria uma thread nova morrendo
    igual, enchendo o log de erro."""
    criados = supervisor_falso
    with panel.app.app_context():
        panel.supervise_streams()
    criados[-1]._vivo = False
    criados[-1].gave_up = True
    with panel.app.app_context():
        panel.supervise_streams()
    assert len(criados) == 1


def test_evento_de_jogador_desligado_fecha_tudo(banco, supervisor_falso):
    with panel.app.app_context():
        panel.supervise_streams()
    liga(banco, ["caiu"])
    with panel.app.app_context():
        assert panel.supervise_streams() == 0


# ------------------------------------------------------------------ diario de alertas

def test_o_envio_vira_uma_linha_no_diario(banco, webhooks):
    """O diario e a resposta para "nao chega nada no Discord": sem ele, alerta que nao
    aconteceu e alerta que nao saiu sao a mesma tela vazia."""
    liga(banco, ["caiu"])
    panel.notify(banco, "caiu", "Palworld: parou", "detalhe")
    diario = panel.recent_alerts(banco)
    assert len(diario) == 1
    assert (diario[0]["evento"], diario[0]["status"]) == ("caiu", "enviado")


def test_evento_sem_ninguem_escutando_e_registrado(banco, webhooks):
    """E o caso mais comum de canal mudo, e precisa ficar registrado com essa cara —
    senao a pessoa procura defeito onde nao ha."""
    liga(banco, ["caiu"])
    panel.notify(banco, "cpu-alta", "Palworld: CPU alta", "99%")
    diario = panel.recent_alerts(banco)
    assert diario[0]["status"] == "sem-destino"
    assert diario[0]["evento"] == "cpu-alta"


def test_envio_que_falhou_fica_marcado_com_o_motivo(banco, monkeypatch):
    liga(banco, ["caiu"])
    monkeypatch.setattr(panel, "send_webhook",
                        lambda url, texto: "500 Internal Server Error")
    panel.notify(banco, "caiu", "Palworld: parou de novo", "")
    diario = panel.recent_alerts(banco)
    assert diario[0]["status"] == "falhou"
    assert "500" in diario[0]["erro"]


def test_limpeza_do_diario_segura_o_tamanho_e_guarda_os_novos(banco, webhooks, monkeypatch):
    """O diario nao pode crescer para sempre nem apagar o que interessa."""
    liga(banco, ["caiu"])
    monkeypatch.setattr(panel, "ALERT_LOG_KEEP", 3)
    for i in range(6):
        panel.notify(banco, "caiu", f"alerta {i}", "")
    with panel.app.app_context():
        panel.clean_history(forcar=True)
    diario = panel.recent_alerts(banco)
    assert len(diario) == 3
    assert "alerta 5" in diario[0]["titulo"], "guarda os mais NOVOS"


# ------------------------------------------------------- uma tarefa quebrada nao cala as outras
# O bug que fez tudo emudecer: as quatro tarefas do relogio dividiam um try so, entao
# uma excecao em roda_agendamentos matava o monitor no mesmo tique — para sempre, porque
# a tarefa quebrada quebrava de novo a cada volta.

def test_tarefa_quebrada_nao_cala_o_monitor(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["caiu"])

    def explode():
        raise RuntimeError("agenda quebrada de proposito")

    monkeypatch.setattr(panel, "run_schedules", explode)
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: estado())

    # Relogios vencidos: cada tique vale uma volta COMPLETA, com consulta de estado.
    relogios_vencidos()
    with panel.app.app_context():
        panel._scheduler_tick()   # linha de base

    monkeypatch.setattr(panel, "server_status",
                        lambda server, force=False: estado(service="inactive"))
    relogios_vencidos()
    with panel.app.app_context():
        panel._scheduler_tick()

    texto = "\n".join(t for _, t in webhooks)
    assert "parou de rodar" in texto, "o monitor roda mesmo com a agenda quebrada"
    falhas_no_diario = [a for a in panel.recent_alerts(banco) if a["status"] == "erro-interno"]
    assert falhas_no_diario, "a quebra fica visivel no diario"
    assert "agendamentos" in falhas_no_diario[0]["titulo"], "dizendo qual tarefa caiu"


# ---------------------------------------------------------- linha de base ao subir o painel

def test_primeira_olhada_do_monitor_so_anota(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["caiu", "inacessivel"])
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": True, "service": "inactive", "error": ""})
    with panel.app.app_context():
        panel.monitor_servers(forcar=True)
    assert len(webhooks) == 0
    assert panel._estado_monitor[alvo["id"]]["service"] == "inactive"


def test_apos_a_linha_de_base_a_mudanca_avisa(banco, alvo, webhooks, monkeypatch):
    liga(banco, ["caiu", "inacessivel"])
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": True, "service": "inactive", "error": ""})
    with panel.app.app_context():
        panel.monitor_servers(forcar=True)

    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": False, "service": "inacessivel", "error": "x"})
    with panel.app.app_context():
        panel.monitor_servers(forcar=True)
    assert len(webhooks) == 1


def test_servidor_removido_sai_da_memoria_do_monitor(banco, alvo, monkeypatch):
    liga(banco, ["caiu", "inacessivel"])
    monkeypatch.setattr(panel, "server_metrics", lambda server, force=False: {"disks": []})
    monkeypatch.setattr(panel, "server_status", lambda server, force=False: {
        "reachable": True, "service": "inactive", "error": ""})
    with panel.app.app_context():
        panel.monitor_servers(forcar=True)

    with banco:
        banco.execute("DELETE FROM servers WHERE id = ?", (alvo["id"],))
    with panel.app.app_context():
        panel.monitor_servers(forcar=True)
    assert alvo["id"] not in panel._estado_monitor


# --------------------------------------------------------------- URL invalida nao sai

def test_url_invalida_nao_chega_a_tentar_conexao():
    """A checagem acontece ANTES de qualquer socket: URL torta nao vira tentativa de
    conexao (nem espera de timeout) escondida atras de uma mensagem de rede."""
    assert panel.send_webhook("nao-e-url", "oi").startswith("URL invalida")
    assert panel.send_webhook("", "oi").startswith("URL invalida")
    assert panel.send_webhook("file:///etc/passwd", "oi").startswith("URL invalida")


# ------------------------------------------------------------------------ a tela

@pytest.fixture
def tela_de_alertas(banco, webhooks):
    """Um administrador logado, banco de webhooks vazio. Devolve (cliente, postar, tela)."""
    with banco:
        banco.execute("DELETE FROM webhooks")
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    cli = panel.app.test_client()
    cli.get("/login")
    with cli.session_transaction() as sess:
        entrada = sess.get("csrf", "")
    resp = cli.post("/login", data={"username": "chefe", "password": "senha-do-chefe",
                                    "csrf": entrada}, follow_redirects=False)
    assert resp.status_code == 302, f"login falhou (status {resp.status_code})"

    def postar(url, data=None):
        d = dict(data or {})
        with cli.session_transaction() as sess:
            d["csrf"] = sess.get("csrf", "")
        return cli.post(url, data=d, follow_redirects=False)

    def tela():
        return cli.get("/alertas").get_data(as_text=True)

    return cli, postar, tela


def test_tela_sem_destino_nenhum(tela_de_alertas):
    cli, _postar, tela = tela_de_alertas
    assert cli.get("/alertas").status_code == 200
    assert "nenhum destino ligado" in tela()


SEGREDO_URL = "https://discord.com/api/webhooks/123/tok-que-nao-pode-vazar"


@pytest.fixture
def destino_cadastrado(banco, tela_de_alertas):
    """Um destino "Equipe" cadastrado pela tela, com a URL secreta acima."""
    _cli, postar, _tela = tela_de_alertas
    resp = postar("/alertas/destinos", {"nome": "Equipe", "ativo": "1", "url": SEGREDO_URL,
                                        "eventos": ["caiu", "disco-cheio"]})
    assert resp.status_code == 302
    return panel.webhook_list(banco)[0]["id"]


def test_url_torta_nao_vira_destino(banco, tela_de_alertas, destino_cadastrado):
    _cli, postar, _tela = tela_de_alertas
    postar("/alertas/destinos", {"nome": "Torto", "url": "nao-e-url"})
    assert len(panel.webhook_list(banco)) == 1


def test_destino_aparece_pelo_nome_sem_o_token(tela_de_alertas, destino_cadastrado):
    _cli, _postar, tela = tela_de_alertas
    html = tela()
    assert "Equipe" in html
    assert "tok-que-nao-pode-vazar" not in html, "o token NAO chega ao HTML"
    assert "discord.com/.../123" in html, "o id fica visivel para reconhecer o canal"


def test_salvar_com_url_vazia_mantem_a_url_e_muda_eventos(banco, tela_de_alertas, destino_cadastrado):
    _cli, postar, _tela = tela_de_alertas
    hid = destino_cadastrado
    # O caminho normal e mexer so nos eventos: a URL fica mascarada e o campo de troca
    # vem vazio, entao um POST sem URL NAO pode limpar a que esta salva.
    postar(f"/alertas/destinos/{hid}", {"nome": "Equipe", "url": "", "ativo": "1",
                                        "eventos": ["caiu"]})
    atual = panel.webhook_list(banco)[0]
    assert atual["url"] == SEGREDO_URL
    assert atual["eventos"] == {"caiu"}


def test_sem_a_caixa_ativo_o_destino_desliga(banco, tela_de_alertas, destino_cadastrado):
    _cli, postar, _tela = tela_de_alertas
    hid = destino_cadastrado
    postar(f"/alertas/destinos/{hid}", {"nome": "Equipe", "url": "", "eventos": ["caiu"]})
    assert panel.webhook_list(banco)[0]["ativo"] is False


def test_dois_destinos_tem_grupos_de_caixas_separados(banco, tela_de_alertas, destino_cadastrado):
    _cli, postar, tela = tela_de_alertas
    hid = destino_cadastrado
    postar(f"/alertas/destinos/{hid}",
           {"nome": "Equipe", "url": "", "ativo": "1", "eventos": ["caiu"]})
    postar("/alertas/destinos", {"nome": "Geral", "ativo": "1",
                                 "url": "https://discord.com/api/webhooks/999/outro",
                                 "eventos": ["caiu"]})
    html = tela()
    assert "Equipe" in html
    assert "Geral" in html
    # Cada destino precisa do seu proprio id de caixa: repetido, clicar no rotulo de um
    # marcaria o evento do outro.
    assert f'id="h{hid}-caiu"' in html
    assert f'id="h{hid + 1}-caiu"' in html


def test_testar_usa_a_url_digitada_ou_a_salva(tela_de_alertas, destino_cadastrado, webhooks):
    """Testar serve para conferir uma URL ANTES de salvar: se ha uma digitada, e ela
    que vai; sem nada digitado, testa a que esta salva."""
    _cli, postar, _tela = tela_de_alertas
    hid = destino_cadastrado

    webhooks.clear()
    postar(f"/alertas/destinos/{hid}/testar", {"url": "https://novo.invalid/hook"})
    assert [u for u, _ in webhooks] == ["https://novo.invalid/hook"]

    webhooks.clear()
    postar(f"/alertas/destinos/{hid}/testar", {"url": ""})
    assert [u for u, _ in webhooks] == [SEGREDO_URL]


def test_limites_de_recurso_pela_tela(banco, tela_de_alertas):
    _cli, postar, tela = tela_de_alertas
    postar("/alertas", {"disk_pct": "80"})
    assert panel.webhook_config(banco)["disco"] == 80

    postar("/alertas", {"disk_pct": "10"})
    assert panel.webhook_config(banco)["disco"] == 80, "fora da faixa e recusado, o anterior fica"

    postar("/alertas", {"disk_pct": "80", "mem_pct": "85", "cpu_pct": "70"})
    assert panel.webhook_config(banco)["memoria"] == 85
    assert panel.webhook_config(banco)["cpu"] == 70

    # Um limite recusado nao pode deixar os outros dois ja gravados: a tela volta
    # dizendo "recusado" e o operador nao teria como saber que metade da mudanca passou.
    postar("/alertas", {"disk_pct": "75", "mem_pct": "10", "cpu_pct": "95"})
    assert panel.webhook_config(banco)["memoria"] == 85, "fora da faixa, nada muda junto"
    assert panel.webhook_config(banco)["disco"] == 80
    assert panel.webhook_config(banco)["cpu"] == 70

    html = tela()
    assert 'name="mem_pct"' in html
    assert 'name="cpu_pct"' in html
    assert 'value="85"' in html
    assert 'value="70"' in html
    assert "memoria-alta" in html
    assert "cpu-alta" in html


def test_remover_tira_da_lista(banco, tela_de_alertas, destino_cadastrado):
    _cli, postar, _tela = tela_de_alertas
    postar(f"/alertas/destinos/{destino_cadastrado}/remover")
    assert len(panel.webhook_list(banco)) == 0


def test_alerta_ligado_sem_onde_olhar_avisa_na_tela(banco, tela_de_alertas):
    """Evento ligado sem nenhum servidor onde olhar: a tela tem de dizer isso em voz
    alta. Alerta ligado e mudo e pior que desligado — o canal calado passa por "esta
    tudo bem"."""
    _cli, _postar, tela = tela_de_alertas
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Sem consulta', '10.0.0.7', 22, 'root', 'x.service', ?)",
            (panel.now_iso(),))
        banco.execute("INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
                     " VALUES ('x', 'http://x.invalid', 'travou,erro-no-log', 1, ?)",
                     (panel.now_iso(),))
    faltando = panel.alerts_without_baseline(banco)
    assert sorted(faltando) == ["erro-no-log", "travou"]
    assert "Ligado, mas sem onde olhar" in tela()


def test_configurar_o_que_faltava_tira_o_aviso(banco, tela_de_alertas):
    _cli, _postar, tela = tela_de_alertas
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Sem consulta', '10.0.0.7', 22, 'root', 'x.service', ?)",
            (panel.now_iso(),))
        banco.execute("INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
                     " VALUES ('x', 'http://x.invalid', 'travou,erro-no-log', 1, ?)",
                     (panel.now_iso(),))
        banco.execute("UPDATE servers SET player_source = 'a2s', query_port = 27015,"
                     " error_re = 'Fatal error'")
    assert panel.alerts_without_baseline(banco) == {}
    assert "Ligado, mas sem onde olhar" not in tela()


def test_cadastro_grava_e_valida_a_expressao_de_erro(banco, tela_de_alertas):
    """O cadastro precisa gravar a expressao de erro: sem isso o alerta de log nunca liga."""
    cli, postar, _tela = tela_de_alertas
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('Sem consulta', '10.0.0.7', 22, 'root', 'x.service', ?)",
            (panel.now_iso(),))
    sid_novo = banco.execute("SELECT id FROM servers").fetchone()["id"]

    postar(f"/servers/{sid_novo}/edit", {
        "name": "Sem consulta", "host": "10.0.0.7", "ssh_port": "22", "ssh_user": "root",
        "service": "x.service", "player_source": "none", "error_re": "Out of memory"})
    assert banco.execute("SELECT error_re FROM servers WHERE id = ?",
                        (sid_novo,)).fetchone()["error_re"] == "Out of memory"

    postar(f"/servers/{sid_novo}/edit", {
        "name": "Sem consulta", "host": "10.0.0.7", "ssh_port": "22", "ssh_user": "root",
        "service": "x.service", "player_source": "none", "error_re": "("})
    assert banco.execute("SELECT error_re FROM servers WHERE id = ?", (sid_novo,)).fetchone()[
        "error_re"] == "Out of memory", "expressao que nao compila e recusada no cadastro"

    form = cli.get(f"/servers/{sid_novo}/edit").get_data(as_text=True)
    assert 'name="error_re"' in form
    assert "Out of memory" in form
    assert 'name="error_re"' in cli.get("/servers/new").get_data(as_text=True)


def test_operador_nao_chega_em_alertas(banco, tela_de_alertas):
    """A tela mexe em credenciais: operador nao entra."""
    panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERADOR)
    outro = panel.app.test_client()
    outro.get("/login")
    with outro.session_transaction() as sess:
        e2 = sess.get("csrf", "")
    outro.post("/login", data={"username": "peao", "password": "senha-do-peao", "csrf": e2})
    assert outro.get("/alertas").status_code in (302, 403)
