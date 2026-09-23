"""tools/import-linuxgsm.py: o que sai dele vira sugestao no formulario, e o LinuxGSM e um
arquivo de terceiros. Cada regra de seguranca do conversor tem um caso aqui."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from gamebroker.services.catalog import KEY_RE, NAME_RE

RAIZ = Path(__file__).resolve().parent.parent.parent
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
