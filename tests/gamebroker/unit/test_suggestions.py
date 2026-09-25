"""O que o painel sugere no formulario "Adicionar jogo" (admin/sugestoes_de_jogos.py, gerado do
LinuxGSM) tem de ser aceito pelo broker: sugestao que ele recusa faria a pessoa achar que o erro
foi dela. Tambem trava o que nunca pode aparecer nela (segredo, encadeamento de shell)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from gamebroker.services.catalog import validate_dynamic

RAIZ = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "sugestoes_de_jogos", RAIZ / "src" / "gamepanel" / "games" / "catalog" / "suggestions.py"
)
data = importlib.util.module_from_spec(_spec)
sys.modules["sugestoes_de_jogos"] = data
_spec.loader.exec_module(data)

SUGGESTIONS = data.SUGGESTIONS


def _as_the_panel_sends(s: dict) -> dict:
    sending = {"key": s["key"], "name": s["name"], "app_id": s["appid"],
             "ports": s["ports"].split() or ["27015/udp"],   # parcial: a pessoa preenche depois
             "game_port": s["game_port"] or 27015, "recipes": [], "config_files": [],
             "backup_paths": [], "shiftable": s["shiftable"]}
    for field in ("start_script", "start_args"):
        if s[field]:
            sending[field] = s[field]
    if s["query_port"]:
        sending["query_port"] = s["query_port"]
    if s.get("extra_port"):
        sending["extra_port"] = s["extra_port"]
    return sending


def test_ha_sugestoes_suficientes_para_valer_a_busca():
    assert len(SUGGESTIONS) >= 100


@pytest.mark.parametrize("s", SUGGESTIONS, ids=lambda s: s["key"])
def test_toda_sugestao_passa_no_validador_do_broker(s):
    assert validate_dynamic(_as_the_panel_sends(s)).key == s["key"]


def test_chaves_e_nomes_sao_unicos_para_a_busca_nao_ficar_ambigua():
    assert len({s["key"] for s in SUGGESTIONS}) == len(SUGGESTIONS)
    assert len({s["name"] for s in SUGGESTIONS}) == len(SUGGESTIONS)


@pytest.mark.parametrize("s", SUGGESTIONS, ids=lambda s: s["key"])
def test_nenhum_argumento_carrega_segredo_nem_encadeia_comando(s):
    args = s["start_args"]
    for forbidden_word in ("$", ";", "|", "&", "`", "CHANGE_ME", "password", "gslt", "token", "rcon_pass"):
        assert forbidden_word not in args, (s["name"], forbidden_word)


@pytest.mark.parametrize("s", SUGGESTIONS, ids=lambda s: s["key"])
def test_marcador_de_consulta_so_existe_com_porta_de_consulta(s):
    if "{QUERY_PORT}" in s["start_args"]:
        assert s["query_port"], s["name"]
    if "{EXTRA_PORT}" in s["start_args"]:
        assert s.get("extra_port"), s["name"]


@pytest.mark.parametrize("s", [s for s in SUGGESTIONS if s["shiftable"]], ids=lambda s: s["key"])
def test_jogo_marcado_para_andar_de_porta_so_tem_as_duas_portas_avisaveis(s):
    numbers = {int(p.split("/")[0]) for p in s["ports"].split()}
    assert numbers <= {s["game_port"], s["query_port"], s.get("extra_port", 0)}


def test_satisfactory_traz_a_porta_confiavel_em_tcp():
    s = next(s for s in SUGGESTIONS if s["appid"] == 1690800)
    assert "8888/tcp" in s["ports"]
    assert "-ReliablePort=8888" in s["start_args"]


def test_porta_de_administracao_nunca_e_exposta():
    """Rust guarda o RCON em 28016: vai no comando, nunca no firewall."""
    rust = next(s for s in SUGGESTIONS if s["appid"] == 258550)
    assert "28016" not in rust["ports"]
    assert "+rcon.port 28016" in rust["start_args"]


def test_quase_toda_sugestao_traz_porta_e_protocolo():
    """Regerar sem o info_game.sh/info_messages.sh nao da erro nenhum: so volta a sair ~30
    jogos sem porta e tudo como UDP presumido. Isto e o que acusa."""
    without_port = [s["key"] for s in SUGGESTIONS if not s["game_port"]]
    presumed = [s["key"] for s in SUGGESTIONS if any("presumido" in w for w in s["warnings"])]
    assert len(without_port) <= 5, without_port
    assert len(presumed) <= 5, presumed


def test_project_zomboid_e_terraria_saem_com_a_porta_de_verdade():
    by_key = {s["key"]: s for s in SUGGESTIONS}
    assert by_key["project-zomboid"]["game_port"] == 16261
    assert by_key["terraria"]["ports"] == "7777/tcp"
