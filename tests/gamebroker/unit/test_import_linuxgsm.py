"""tools/import-linuxgsm.py: o que sai dele vira sugestao no formulario, e o LinuxGSM e um
arquivo de terceiros. Cada regra de seguranca do conversor tem um caso aqui."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from gamebroker.services.catalog import KEY_RE, NAME_RE

RAIZ = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("importar_linuxgsm", RAIZ / "tools" / "import-linuxgsm.py")
imp = importlib.util.module_from_spec(_spec)
sys.modules["importar_linuxgsm"] = imp
_spec.loader.exec_module(imp)

# Trechos reais do LinuxGSM (sfserver e pwserver).
SATISFACTORY = '''
appid="1690800"
port="7777"
queryport="15777"
beaconport="15000"
reliableport="8888"
servername="LinuxGSM"
serverfiles="${rootdir}/serverfiles"
executable="./FactoryServer-Linux-Shipping"
executabledir="${serverfiles}/Engine/Binaries/Linux"
startparameters="FactoryGame -Port=${port} -ServerQueryPort=${queryport} -BeaconPort=${beaconport} -ReliablePort=${reliableport} -log"
'''
PALWORLD = '''
appid="2394010"
port="8211"
steamport="27015"
systemdir="${serverfiles}/Pal"
executable="./PalServer-Linux-Shipping"
executabledir="${systemdir}/Binaries/Linux/"
startparameters="-publiclobby -useperfthreads -servername='${servername}' -port='${port}' -queryport='${steamport}'"
'''


def test_satisfactory_reproduz_as_portas_e_o_protocolo_de_cada_uma():
    s = imp.sugerir("Satisfactory", SATISFACTORY)
    assert s["ports"] == "7777/udp 15777/udp 15000/udp 8888/tcp", "a porta confiavel e TCP"
    assert s["game_port"] == 7777
    assert s["query_port"] == 15777
    assert s["start_args"] == ("FactoryGame -Port={PORT} -ServerQueryPort={QUERY_PORT} "
                               "-BeaconPort=15000 -ReliablePort=8888 -log")
    assert s["start_script"] == "Engine/Binaries/Linux/FactoryServer-Linux-Shipping"


def test_jogo_com_duas_portas_extras_nao_anda_de_porta():
    """O broker avisa ao jogo UMA porta extra. Com beacon E confiavel elas ficam fixas."""
    s = imp.sugerir("Satisfactory", SATISFACTORY)
    assert s["shiftable"] is False
    assert s["extra_port"] == 0


UMA_EXTRA = '''
appid="99"
port="7777"
reliableport="8888"
startparameters="-Port=${port} -ReliablePort=${reliableport} -log"
'''


def test_uma_porta_extra_vira_o_marcador_e_o_jogo_pode_andar_de_porta():
    s = imp.sugerir("Um Jogo", UMA_EXTRA)
    assert s["start_args"] == "-Port={PORT} -ReliablePort={EXTRA_PORT} -log"
    assert s["extra_port"] == 8888
    assert s["ports"] == "7777/udp 8888/tcp"
    assert s["shiftable"] is True


def test_palworld_anda_de_porta_e_perde_so_o_nome_do_servidor():
    s = imp.sugerir("Palworld", PALWORLD)
    assert s["start_args"] == "-publiclobby -useperfthreads -port={PORT} -queryport={QUERY_PORT}"
    assert s["shiftable"] is True
    assert s["start_script"] == "Pal/Binaries/Linux/PalServer-Linux-Shipping"
    assert any("servername" in warning for warning in s["warnings"])


HOSTIL = '''
appid="42"
port="27015"
rconport="27020"
telnetport="27021"
serverpassword="CHANGE_ME"
rconpassword="CHANGE_ME"
gslt="TOKEN-SECRETO"
seed=""
startparameters="-port ${port} +password ${serverpassword} +rcon_password ${rconpassword} +rcon.port ${rconport} +telnet ${telnetport} +gslt ${gslt} +seed ${seed} +ok yes $(id) ; rm -rf / `x` '${port}' | cat"
'''


def test_segredo_nunca_e_resolvido_nem_vai_para_a_sugestao():
    s = imp.sugerir("Hostil", HOSTIL)
    text = s["start_args"] + " " + s["ports"]
    for forbidden_word in ("CHANGE_ME", "TOKEN-SECRETO", "password", "gslt"):
        assert forbidden_word not in text


def test_o_que_nao_cabe_no_charset_e_removido_nao_escapado():
    args = imp.sugerir("Hostil", HOSTIL)["start_args"]
    for dangerous in ("$", ";", "`", "|", "(", ")", "'", '"', "rm -rf"):
        assert dangerous not in args


def test_porta_de_administracao_fica_so_no_argumento_e_nunca_no_firewall():
    s = imp.sugerir("Hostil", HOSTIL)
    assert "+rcon.port 27020" in s["start_args"], "o jogo precisa dela para subir"
    assert "27020" not in s["ports"]
    assert "27021" not in s["ports"]
    assert any("administracao" in warning for warning in s["warnings"])


def test_variavel_vazia_nao_deixa_opcao_solta_engolindo_a_proxima():
    args = imp.sugerir("Hostil", HOSTIL)["start_args"]
    assert "+seed" not in args
    assert "+ok yes" in args


def test_sem_appid_nao_ha_sugestao():
    assert imp.sugerir("Minecraft", 'port="25565"\nstartparameters="-port ${port}"') is None


def test_sem_porta_no_cfg_a_sugestao_sai_parcial_com_aviso():
    s = imp.sugerir("Barotrauma", 'appid="1026340"\nexecutable="./DedicatedServer"\nexecutabledir="${serverfiles}"')
    assert s["appid"] == 1026340
    assert s["ports"] == ""
    assert s["game_port"] == 0
    assert s["shiftable"] is False
    assert any("portas" in warning for warning in s["warnings"])


def test_executavel_fora_de_opt_game_e_descartado():
    s = imp.sugerir("Estranho", 'appid="7"\nport="1234"\nexecutable="/usr/bin/sh"\nexecutabledir="/usr/bin"')
    assert s["start_script"] == ""


@pytest.mark.parametrize("name", ["Counter-Strike: Global Offensive", "Sven Co-op", "Ark: Survival Évolved",
                                  "7 Days to Die", "Killing Floor 2 (Beta)"])
def test_nome_e_chave_saem_no_formato_do_broker(name):
    assert NAME_RE.fullmatch(imp.display_name(name))
    assert KEY_RE.fullmatch(imp.game_key(name))


def test_ler_atribuicoes_ignora_comentario_e_usa_a_ultima_atribuicao():
    v = imp.ler_atribuicoes('# port="1"\nport="7777" # padrao\nport="8888"\nvazio=""\nsolto=abc')
    assert v == {"port": "8888", "vazio": "", "solto": "abc"}


def test_resolver_nao_entra_em_laco_com_variavel_que_se_refere_a_si_mesma():
    assert re.fullmatch(r".*\$\{a\}.*", imp.resolver("x ${a}", {"a": "${a}"}))


# --- dados fora do _default.cfg ---------------------------------------------------------
# Trechos reais: fn_info_game_pz / fn_info_game_vh (info_game.sh), fn_info_messages_terraria
# (info_messages.sh) e o server.ini padrao do Project Zomboid (Game-Server-Configs).

INFO_GAME = '''
fn_info_game_pz() {
	if [ -f "${servercfgfullpath}" ]; then
		fn_info_game_ini "adminpassword" "AdminPassword"
		fn_info_game_ini "port" "DefaultPort"
	fi
	port="${port:-"0"}"
	queryport="${port:-"0"}"
}

fn_info_game_vh() {
	port="${port:-"0"}"
	queryport="$((port + 1))"
}
'''
PZ_CFG = '''
appid="380870"
servercfgdefault="server.ini"
servercfgdir="${HOME}/Zomboid/Server"
servercfg="${selfname}.ini"
executable="./start-server.sh"
executabledir="${serverfiles}"
'''
PZ_SERVER_INI = "PVP=true\nDefaultPort=16261\nUDPPort=16262\n"
VALHEIM = '''
appid="896660"
port="2456"
querytype=""
startparameters="-name '${servername}' -port ${port} -world '${worldname}' -public 1"
executable="./valheim_server.x86_64"
executabledir="${serverfiles}"
'''
MESSAGES = '''
fn_info_messages_terraria() {
	{
		fn_port "header"
		fn_port "Game" port tcp
		fn_port "Query" queryport tcp
	} | column -s $'\\t' -t
}

fn_info_messages_ac() {
	{
		fn_port "Game" port udp
		fn_port "Game" port tcp
		fn_port "HTTP" httpport tcp
	}
}
'''


def _extras(short: str, configs: dict[str, str] | None = None, messages: str = "") -> object:
    return imp.GameExtras(
        info_body=imp.info_function(INFO_GAME, short),
        messages_body=imp.info_function(messages, short, prefix="fn_info_messages_"),
        read_config=lambda name: (configs or {}).get(name))


def test_porta_que_mora_no_config_do_jogo_sai_da_config_padrao():
    """Era o caso do 7777: sem porta, o formulario mostrava o EXEMPLO do campo como se fosse ela."""
    s = imp.sugerir("Project Zomboid", PZ_CFG, _extras("pz", {"server.ini": PZ_SERVER_INI}))
    assert (s["game_port"], s["ports"]) == (16261, "16261/udp")
    assert any("server.ini" in w for w in s["warnings"]), "diz de onde a porta veio"
    assert s["shiftable"] is False, "o jogo le a porta do arquivo, nao do comando"


def test_sem_a_config_padrao_continua_parcial_e_avisa():
    s = imp.sugerir("Project Zomboid", PZ_CFG, _extras("pz", {}))
    assert s["game_port"] == 0
    assert any("preencha as portas" in w for w in s["warnings"])


def test_consulta_derivada_da_porta_entra_no_firewall_e_o_jogo_para_de_andar():
    """Valheim: sem a 2457 o servidor nao aparece na lista, e o broker nao sabe avisa-la."""
    s = imp.sugerir("Valheim", VALHEIM, _extras("vh"))
    assert s["ports"] == "2456/udp 2457/udp"
    assert s["query_port"] == 2457
    assert s["shiftable"] is False
    assert "{QUERY_PORT}" not in s["start_args"]


def test_protocolo_vem_do_info_messages_e_so_presume_quando_ele_cala():
    terraria = 'appid="105600"\nport="7777"\nstartparameters="-port ${port}"'
    s = imp.sugerir("Terraria", terraria, _extras("terraria", messages=MESSAGES))
    assert s["ports"] == "7777/tcp"
    assert not any("presumido" in w for w in s["warnings"])
    assert any("presumido" in w for w in imp.sugerir("Terraria", terraria)["warnings"])


def test_a_mesma_porta_em_dois_protocolos_e_a_admin_nunca():
    protocols = imp.port_protocols(imp.info_function(MESSAGES, "ac", prefix="fn_info_messages_"))
    assert protocols == {"port": ["udp", "tcp"], "httpport": ["tcp"]}


def test_consulta_da_steam_e_udp_mesmo_quando_o_linuxgsm_diz_tcp():
    cfg = 'appid="1"\nport="7777"\nqueryport="27015"\nstartparameters="-Port=${port} -QueryPort=${queryport}"'
    messages = 'fn_info_messages_x() {\n\tfn_port "Game" port udp\n\tfn_port "Query" queryport tcp\n}\n'
    s = imp.sugerir("Um Jogo", cfg, imp.GameExtras(messages_body=imp.info_function(messages, "x", "fn_info_messages_")))
    assert s["ports"] == "7777/udp 27015/udp"


@pytest.mark.parametrize(("kind", "key", "text", "value"), [
    ("ini", "DefaultPort", "DefaultPortX=1\nDefaultPort = 16261\n", "16261"),
    ("keyvalue_pairs_equals", "port", "maxplayers=8\nport=7777\n", "7777"),
    ("keyvalue_pairs_space", "sv_port", 'sv_name "x"\nsv_port 8303\n', "8303"),
    ("quakec", "net_port", 'set net_port "27960"\n', "27960"),
    ("lua", "BindPort", '  BindPort = 7777, -- porta\n', "7777"),
    ("pc_config", "hostPort", 'hostPort : 27015\n', "27015"),
    ("json", ".a2s.port", '{"bindPort": 2001, "a2s": {"port": 17777}}', "17777"),
    ("xml", "/serversettings/@port", '<serversettings port="27015" name="x"/>', "27015"),
    ("xml", "/SettingData/GamePort", "<SettingData><GamePort>27016</GamePort></SettingData>", "27016"),
    ("xml", "/ServerSettings/property[@name='ServerPort']/@value",
     '<ServerSettings><property name="ServerPort" value="26900"/></ServerSettings>', "26900"),
])
def test_leitores_de_config_como_os_do_info_game(kind, key, text, value):
    assert imp.config_value(kind, key, text) == value


@pytest.mark.parametrize("text", ["{nao e json", "<nao-fecha", ""])
def test_config_quebrada_nao_derruba_o_importador(text):
    assert imp.config_value("json", ".port", text) == ""
    assert imp.config_value("xml", "/a/@port", text) == ""


def test_a2s_so_com_consulta_da_steam_e_porta_propria():
    assert imp.player_source({"querytype": "protocol-valve"}, 27015) == "a2s"
    assert imp.player_source({"querytype": "protocol-valve"}, 0) == "log"
    assert imp.player_source({"querytype": "minecraft"}, 25565) == "log"


def test_pasta_de_config_so_dentro_da_pasta_do_jogo():
    ark = {"systemdir": "${serverfiles}/ShooterGame", "servercfgdir": "${systemdir}/Saved/Config/LinuxServer",
           "servercfg": "GameUserSettings.ini"}
    folder = "/opt/game/ShooterGame/Saved/Config/LinuxServer"
    assert imp.config_location(ark) == (folder, [f"{folder}/GameUserSettings.ini"])
    # Fora de /opt/game (pasta do LinuxGSM) ou com o nome da instancia: nada.
    assert imp.config_location({"servercfgdir": "${HOME}/Zomboid/Server", "servercfg": "${selfname}.ini"}) == ("", [])
    assert imp.config_location({"servercfgdir": "${serverfiles}", "servercfg": "${selfname}.xml"}) == ("/opt/game", [])
    # Formato que a tela Config nao abre fica so na pasta.
    assert imp.config_location({"servercfgdir": "${serverfiles}", "servercfg": "config.lua"}) == ("/opt/game", [])


def test_argumento_recusado_pelo_broker_esvazia_o_campo_e_nao_descarta_a_sugestao(monkeypatch):
    """O importador lia `erro.campo`, que nao existe: a sugestao inteira sumia."""
    real = imp.validate_dynamic

    def refuse_args(data):
        if data.get("start_args"):
            raise imp.ValidationError("start_args", "formato invalido")
        return real(data)

    monkeypatch.setattr(imp, "validate_dynamic", refuse_args)
    s = imp.sugerir("Palworld", PALWORLD)
    assert s is not None
    assert s["start_args"] == ""
    assert any("start_args" in w for w in s["warnings"])
