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


# ----------------------------------------------------------------------------
# A lista escrita a mao (manual_suggestions.py): servidor so de Windows, que o LinuxGSM nao tem
# ----------------------------------------------------------------------------

_spec_manual = importlib.util.spec_from_file_location(
    "manual_suggestions", RAIZ / "src" / "gamepanel" / "games" / "catalog" / "manual_suggestions.py"
)
manual = importlib.util.module_from_spec(_spec_manual)
sys.modules["manual_suggestions"] = manual
_spec_manual.loader.exec_module(manual)
MANUAL = manual.SUGGESTIONS


def _manual_as_the_panel_sends(s: dict) -> dict:
    sending = _as_the_panel_sends(s)
    sending.update(platform=s["platform"], recipes=list(s["recipes"]),
                   config_files=list(s["config_files"]), backup_paths=list(s["backup_paths"]),
                   player_source=s["player_source"], memory_mb=s["memory_mb"], cores=s["cores"],
                   disk_gb=s["disk_gb"])
    if s["config_path"]:
        sending["config_path"] = s["config_path"]
    return sending


@pytest.mark.parametrize("s", MANUAL, ids=lambda s: s["key"])
def test_sugestao_manual_passa_no_validador_do_broker(s):
    assert validate_dynamic(_manual_as_the_panel_sends(s)).key == s["key"]


@pytest.mark.parametrize("s", MANUAL, ids=lambda s: s["key"])
def test_sugestao_manual_de_windows_usa_proton(s):
    """Regra do repositorio: Proton primeiro; wine so com o motivo escrito num curado."""
    if s["platform"] == "windows":
        assert "proton" in s["recipes"]
        assert "wine" not in s["recipes"]


@pytest.mark.parametrize("s", MANUAL, ids=lambda s: s["key"])
def test_sugestao_manual_nao_carrega_segredo_nem_encadeia_comando(s):
    for forbidden_word in ("$", ";", "|", "&", "`", "password", "token"):
        assert forbidden_word not in s["start_args"], (s["name"], forbidden_word)


def test_lista_manual_nao_repete_o_linuxgsm():
    """Repetir um jogo nas duas listas daria dois botoes com dados diferentes para o mesmo App ID."""
    assert not {s["appid"] for s in MANUAL} & {s["appid"] for s in SUGGESTIONS}
    assert not {s["key"] for s in MANUAL} & {s["key"] for s in SUGGESTIONS}


def test_lista_manual_nao_repete_um_curado():
    """Chave de um curado num jogo dinamico vira sobreposicao POR CIMA do .env (ver o Valheim).
    Curado ja aparece na busca pelo catalogo da pagina; aqui ele nao entra."""
    curated_keys, curated_appids = set(), set()
    for env in (RAIZ / "games").glob("[!_]*.env"):
        text = env.read_text(encoding="utf-8")
        curated_keys.add(env.stem)
        for line in text.splitlines():
            if line.startswith("STEAM_APP_ID="):
                curated_appids.add(int(line.split("=", 1)[1]))
    assert not {s["key"] for s in MANUAL} & curated_keys
    assert not {s["appid"] for s in MANUAL} & curated_appids


# ----------------------------------------------------------------------------
# A lista gerada dos eggs do Pterodactyl (pterodactyl_suggestions.py)
# ----------------------------------------------------------------------------

_spec_ptero = importlib.util.spec_from_file_location(
    "pterodactyl_suggestions",
    RAIZ / "src" / "gamepanel" / "games" / "catalog" / "pterodactyl_suggestions.py",
)
ptero = importlib.util.module_from_spec(_spec_ptero)
sys.modules["pterodactyl_suggestions"] = ptero
_spec_ptero.loader.exec_module(ptero)
PTERO = ptero.SUGGESTIONS


def _ptero_as_the_panel_sends(s: dict) -> dict:
    sending = _manual_as_the_panel_sends({**s, "memory_mb": 4096, "cores": 2, "disk_gb": 20})
    if not s["ports"]:
        sending["player_source"] = "log"
        sending.pop("query_port", None)
        sending.pop("extra_port", None)
    return sending


def test_o_pterodactyl_traz_jogos_que_as_outras_fontes_nao_tem():
    assert len(PTERO) >= 30
    assert sum(s["platform"] == "windows" for s in PTERO) >= 15, "o motivo de existir: servidor so de Windows"


@pytest.mark.parametrize("s", PTERO, ids=lambda s: s["key"])
def test_sugestao_do_pterodactyl_passa_no_validador_do_broker(s):
    assert validate_dynamic(_ptero_as_the_panel_sends(s)).key == s["key"]


@pytest.mark.parametrize("s", PTERO, ids=lambda s: s["key"])
def test_sugestao_do_pterodactyl_de_windows_usa_proton(s):
    if s["platform"] == "windows":
        assert "proton" in s["recipes"]
        assert "wine" not in s["recipes"]


@pytest.mark.parametrize("s", PTERO, ids=lambda s: s["key"])
def test_sugestao_do_pterodactyl_nao_carrega_segredo_nem_caminho_do_container(s):
    for forbidden_word in ("$", ";", "|", "&", "`", "{{", "password", "token", "/home/container"):
        assert forbidden_word not in s["start_args"], (s["name"], forbidden_word)
    assert "/home/container" not in s["start_script"]


def test_nenhum_app_id_ou_chave_aparece_em_duas_fontes():
    """Dois botoes para o mesmo jogo, com dados diferentes, e a pessoa nao sabe qual vale. Dentro
    do LinuxGSM o App ID se repete de proposito (os mods do HLDS sao todos o 90): conta o CRUZAMENTO."""
    linuxgsm = {s["appid"] for s in SUGGESTIONS}
    manual_ids = {s["appid"] for s in MANUAL}
    ptero_ids = [s["appid"] for s in PTERO]
    assert len(ptero_ids) == len(set(ptero_ids))
    assert not set(ptero_ids) & (linuxgsm | manual_ids)
    keys = [s["key"] for s in (*SUGGESTIONS, *MANUAL, *PTERO)]
    assert len(keys) == len(set(keys))


def test_pterodactyl_nao_repete_um_curado():
    curated = set()
    for env in (RAIZ / "games").glob("[!_]*.env"):
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("STEAM_APP_ID="):
                curated.add(int(line.split("=", 1)[1]))
    assert not {s["appid"] for s in PTERO} & curated


def test_complemento_so_existe_para_jogo_do_linuxgsm_e_so_em_campo_vazio():
    by_appid = {s["appid"]: s for s in SUGGESTIONS}
    assert ptero.COMPLEMENTS, "sem complemento nenhum a juncao nao esta sendo gerada"
    for appid, extra in ptero.COMPLEMENTS.items():
        base = by_appid[appid]
        for field in extra:
            if field in ("config_path", "config_files", "ports"):
                assert not base.get(field), (base["name"], field)
        assert "start_args" not in extra, "o comando do LinuxGSM nunca e trocado pelo do egg"


@pytest.mark.parametrize("appid", sorted(ptero.COMPLEMENTS))
def test_linuxgsm_com_complemento_passa_no_validador(appid):
    base = next(s for s in SUGGESTIONS if s["appid"] == appid)
    merged = {**base, **ptero.COMPLEMENTS[appid]}
    sending = _as_the_panel_sends(merged)
    sending["config_files"] = list(merged.get("config_files") or [])
    if merged.get("config_path"):
        sending["config_path"] = merged["config_path"]
    assert validate_dynamic(sending).key == base["key"]
