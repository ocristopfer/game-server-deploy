"""O que o painel sugere no formulario "Adicionar jogo" (admin/sugestoes_de_jogos.py, gerado do
LinuxGSM) tem de ser aceito pelo broker: sugestao que ele recusa faria a pessoa achar que o erro
foi dela. Tambem trava o que nunca pode aparecer nela (segredo, encadeamento de shell)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from gamebroker.catalogo import validar_dinamico

RAIZ = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "sugestoes_de_jogos", RAIZ / "src" / "gamepanel" / "games" / "catalog" / "suggestions.py"
)
dados = importlib.util.module_from_spec(_spec)
sys.modules["sugestoes_de_jogos"] = dados
_spec.loader.exec_module(dados)

SUGESTOES = dados.SUGESTOES


def _como_o_painel_envia(s: dict) -> dict:
    envio = {"chave": s["chave"], "nome": s["nome"], "app_id": s["appid"],
             "portas": s["portas"].split() or ["27015/udp"],   # parcial: a pessoa preenche depois
             "porta_jogo": s["porta_jogo"] or 27015, "receitas": [], "config_files": [],
             "backup_paths": [], "deslocavel": s["deslocavel"]}
    for campo in ("start_script", "start_args"):
        if s[campo]:
            envio[campo] = s[campo]
    if s["porta_query"]:
        envio["porta_query"] = s["porta_query"]
    if s.get("porta_extra"):
        envio["porta_extra"] = s["porta_extra"]
    return envio


def test_ha_sugestoes_suficientes_para_valer_a_busca():
    assert len(SUGESTOES) >= 100


@pytest.mark.parametrize("s", SUGESTOES, ids=lambda s: s["chave"])
def test_toda_sugestao_passa_no_validador_do_broker(s):
    assert validar_dinamico(_como_o_painel_envia(s)).chave == s["chave"]


def test_chaves_e_nomes_sao_unicos_para_a_busca_nao_ficar_ambigua():
    assert len({s["chave"] for s in SUGESTOES}) == len(SUGESTOES)
    assert len({s["nome"] for s in SUGESTOES}) == len(SUGESTOES)


@pytest.mark.parametrize("s", SUGESTOES, ids=lambda s: s["chave"])
def test_nenhum_argumento_carrega_segredo_nem_encadeia_comando(s):
    args = s["start_args"]
    for proibido in ("$", ";", "|", "&", "`", "CHANGE_ME", "password", "gslt", "token", "rcon_pass"):
        assert proibido not in args, (s["nome"], proibido)


@pytest.mark.parametrize("s", SUGESTOES, ids=lambda s: s["chave"])
def test_marcador_de_consulta_so_existe_com_porta_de_consulta(s):
    if "{QUERY_PORT}" in s["start_args"]:
        assert s["porta_query"], s["nome"]
    if "{EXTRA_PORT}" in s["start_args"]:
        assert s.get("porta_extra"), s["nome"]


@pytest.mark.parametrize("s", [s for s in SUGESTOES if s["deslocavel"]], ids=lambda s: s["chave"])
def test_jogo_marcado_para_andar_de_porta_so_tem_as_duas_portas_avisaveis(s):
    numeros = {int(p.split("/")[0]) for p in s["portas"].split()}
    assert numeros <= {s["porta_jogo"], s["porta_query"], s.get("porta_extra", 0)}


def test_satisfactory_traz_a_porta_confiavel_em_tcp():
    s = next(s for s in SUGESTOES if s["appid"] == 1690800)
    assert "8888/tcp" in s["portas"]
    assert "-ReliablePort=8888" in s["start_args"]


def test_porta_de_administracao_nunca_e_exposta():
    """Rust guarda o RCON em 28016: vai no comando, nunca no firewall."""
    rust = next(s for s in SUGESTOES if s["appid"] == 258550)
    assert "28016" not in rust["portas"]
    assert "+rcon.port 28016" in rust["start_args"]
