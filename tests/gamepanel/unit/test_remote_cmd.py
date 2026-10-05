"""The command builder (`runtime.remote_cmd`): the exact strings, in both access modes.

Two promises are checked here, and both are about EXACT text:

- legacy mode (`ssh_user == 'root'`) sends byte for byte what the panel always sent. A server
  registered before the hardening must not notice anything; a stray `sudo` there would break it;
- helper mode (any other user) reaches root only through the lines of the sudoers file in
  docs/security-hardening-contract.md. One word more or less and `sudo -n` refuses - which is
  a failure at the first click on a real server, and invisible in any test that only looks for
  "sudo" somewhere in the string.
"""
from __future__ import annotations

import subprocess

import pytest

from gamepanel import app as panel
from gamepanel.games.mods import antivirus
from gamepanel.runtime import backups, files, presence_probe, remote_cmd
from gamepanel.runtime.ssh import quote_command

LEGACY = {"id": 1, "ssh_user": "root", "service": "palworld.service", "host": "ct"}
HELPER = {"id": 2, "ssh_user": "gamepanel", "service": "palworld.service", "host": "ct"}
# A dict the way the older tests and some callers build it: no ssh_user at all.
NO_USER = {"id": 3, "service": "palworld.service", "host": "ct"}


# ------------------------------------------------------------------- mode

@pytest.mark.parametrize(("server", "expected"), [
    (LEGACY, True), (HELPER, False), (NO_USER, True), ({"ssh_user": ""}, True),
    ({"ssh_user": "steam"}, False),
])
def test_privileged_so_quando_o_login_e_root(server, expected):
    assert remote_cmd.privileged(server) is expected


def test_quem_age_no_conteudo_e_root_no_legado_e_steam_no_helper():
    assert remote_cmd.content_user(LEGACY) == "root"
    assert remote_cmd.content_user(HELPER) == "steam"


def test_servidor_sem_o_campo_conta_como_root():
    """Missing = a server from before the choice existed; it still speaks legacy mode."""
    assert remote_cmd.ssh_user(NO_USER) == "root"


# ---------------------------------------------------------- root actions

@pytest.mark.parametrize(("action", "expected"), [
    ("start", "systemctl start palworld.service"),
    ("stop", "systemctl stop palworld.service"),
    ("restart", "systemctl restart palworld.service"),
    ("update", "/usr/local/bin/update-game"),
    ("check-update", "/usr/local/bin/check-game-update"),
])
def test_acao_no_modo_root_e_o_comando_de_sempre(action, expected):
    assert remote_cmd.as_root_action(LEGACY, action) == expected


@pytest.mark.parametrize(("action", "expected"), [
    ("start", "sudo -n /usr/local/sbin/gp-service start"),
    ("stop", "sudo -n /usr/local/sbin/gp-service stop"),
    ("restart", "sudo -n /usr/local/sbin/gp-service restart"),
    ("update", "sudo -n /usr/local/bin/update-game"),
    ("check-update", "sudo -n /usr/local/bin/check-game-update"),
])
def test_acao_no_modo_helper_e_a_linha_exata_do_sudoers(action, expected):
    assert remote_cmd.as_root_action(HELPER, action) == expected


def test_helper_nunca_manda_o_nome_da_unidade():
    """gp-service reads the unit from the root-owned ct.env: a name in the argument would
    not even match the sudoers line, and is exactly what the line exists to forbid."""
    assert "palworld" not in remote_cmd.as_root_action(HELPER, "stop")


def test_acao_desconhecida_e_erro():
    with pytest.raises(ValueError, match="acao sem comando"):
        remote_cmd.as_root_action(LEGACY, "format-disk")


def test_os_botoes_do_app_usam_o_construtor():
    assert panel.COMMANDS["start"](LEGACY) == "systemctl start palworld.service"
    assert panel.COMMANDS["update"](HELPER) == "sudo -n /usr/local/bin/update-game"


# --------------------------------------------------------------- presence

def test_presenca_no_modo_root_e_a_constante_de_sempre():
    assert remote_cmd.presence(LEGACY) == presence_probe.PRESENCE_COMMAND
    assert remote_cmd.presence(LEGACY) == "nft -j list set inet ct_firewall players"


def test_presenca_no_modo_helper_e_a_linha_exata_do_sudoers():
    assert remote_cmd.presence(HELPER) == "sudo -n /usr/sbin/nft -j list set inet ct_firewall players"


def test_presenca_pergunta_com_o_comando_do_modo():
    sent: list[str] = []

    def ssh_output(server, command, timeout):
        sent.append(command)
        return '{"nftables": [{"set": {"name": "players", "elem": [1, 2]}}]}'

    assert presence_probe.players_from_presence(ssh_output, HELPER)["players"] == 2
    assert sent == ["sudo -n /usr/sbin/nft -j list set inet ct_firewall players"]


# ---------------------------------------------------------------- content

def test_conteudo_no_modo_root_e_o_comando_cru():
    assert remote_cmd.as_steam(LEGACY, "bash", "-lc", "echo oi", "gp") == "bash -lc 'echo oi' gp"


def test_conteudo_no_modo_helper_vira_steam_a_partir_da_raiz():
    assert remote_cmd.as_steam(HELPER, "bash", "-lc", "echo oi", "gp") == (
        "cd / && sudo -n -u steam -- bash -lc 'echo oi' gp")


def test_sem_privilegio_e_igual_nos_dois_modos():
    assert remote_cmd.unprivileged("systemctl", "show", "x y") == "systemctl show 'x y'"


def test_terminal_root_e_o_shell_do_proprio_ssh():
    assert remote_cmd.interactive_shell(LEGACY) is None


def test_terminal_helper_e_o_shell_de_login_do_steam():
    assert remote_cmd.interactive_shell(HELPER) == "sudo -n -u steam -i"


def test_clamav_pelo_helper_fixo():
    assert remote_cmd.clamav_ensure() == "sudo -n /usr/local/sbin/gp-clamav-ensure"


# ------------------------------------------- the runtime modules, end to end

class _Capture:
    def __init__(self, stdout: str = "") -> None:
        self.sent: list[str] = []
        self.stdout = stdout

    def __call__(self, server, command, timeout=None, stdin_data=None, multiplex=True):
        self.sent.append(command)
        return subprocess.CompletedProcess([], 0, self.stdout, "")


def test_listar_pasta_no_modo_root_nao_mudou():
    run = _Capture()
    files.list_dir(run, LEGACY, "/opt/game", 500)
    assert run.sent == [quote_command("bash", "-lc", files.LIST_SCRIPT, "gp", "/opt/game", "500")]


def test_listar_pasta_no_modo_helper_roda_como_steam():
    run = _Capture()
    files.list_dir(run, HELPER, "/opt/game", 500)
    assert run.sent == ["cd / && " + quote_command(
        "sudo", "-n", "-u", "steam", "--", "bash", "-lc", files.LIST_SCRIPT, "gp", "/opt/game", "500")]


def test_gravar_arquivo_no_modo_helper_roda_como_steam():
    run = _Capture("gravado: 3 bytes")
    files.write_file(run, HELPER, "/opt/game/a.ini", b"abc")
    assert run.sent[0].startswith("cd / && sudo -n -u steam -- bash -lc ")


def test_backup_no_modo_root_nao_mudou():
    cmd = backups.backup_command(LEGACY, "/var/backups/gamepanel", 5, ["/opt/game/save"])
    assert cmd == quote_command("bash", "-lc", backups.BACKUP_SCRIPT, "gp", "/var/backups/gamepanel",
                                "palworld", "5", "", "/opt/game/save")


def test_backup_no_modo_helper_roda_como_steam():
    cmd = backups.backup_command(HELPER, "/var/backups/gamepanel", 5, ["/opt/game/save"])
    assert cmd.startswith("cd / && sudo -n -u steam -- bash -lc ")


def test_restauracao_leva_o_modo_e_as_pastas():
    """The restore runs as the login user in both modes and switches inside: it needs steam
    for the archive and the fixed helper for the service, and steam itself has no sudo."""
    legacy = backups.restore_command(LEGACY, "/var/backups/gamepanel", "palworld-1.tar.gz", ["/opt/game/save"])
    helper = backups.restore_command(HELPER, "/var/backups/gamepanel", "palworld-1.tar.gz", ["/opt/game/save"])
    tail = ["/var/backups/gamepanel", "palworld-1.tar.gz", "palworld.service"]
    assert legacy == quote_command("bash", "-lc", backups.RESTORE_SCRIPT, "gp", *tail, "root", "/opt/game/save")
    assert helper == quote_command("bash", "-lc", backups.RESTORE_SCRIPT, "gp", *tail, "steam", "/opt/game/save")


def test_o_script_de_restauracao_so_chega_ao_root_pelas_linhas_do_sudoers():
    script = backups.RESTORE_SCRIPT
    assert "sudo -n -u steam --" in script
    assert "sudo -n /usr/local/sbin/gp-service" in script
    assert "--no-same-owner --no-same-permissions" in script


def test_copia_do_painel_volta_como_steam_no_modo_helper():
    assert backups.receive_command(HELPER, "/var/backups/gamepanel", "x.tar.gz").startswith(
        "cd / && sudo -n -u steam -- bash -lc ")
    assert backups.receive_command(LEGACY, "/var/backups/gamepanel", "x.tar.gz") == quote_command(
        "bash", "-lc", backups.BACKUP_RECEIVE_SCRIPT, "gp", "/var/backups/gamepanel", "x.tar.gz")


# --------------------------------------------------------------- antivirus

def test_antivirus_no_modo_root_e_um_passo_so_e_o_script_de_sempre():
    assert antivirus.scan_steps(LEGACY, "/var/tmp/gamepanel-incoming-ab") == [
        quote_command("bash", "-c", antivirus.SCAN_SCRIPT, "gp", "/var/tmp/gamepanel-incoming-ab")]
    assert antivirus.audit_steps(LEGACY, ["/opt/game/Mods"]) == [
        quote_command("bash", "-c", antivirus.AUDIT_SCRIPT, "gp", "/opt/game/Mods")]


def test_antivirus_no_modo_helper_instala_pelo_helper_e_verifica_como_steam():
    steps = antivirus.scan_steps(HELPER, "/var/tmp/gamepanel-incoming-ab")
    assert steps[0] == "sudo -n /usr/local/sbin/gp-clamav-ensure"
    assert steps[1].startswith("cd / && sudo -n -u steam -- bash -c ")
    audit = antivirus.audit_steps(HELPER, ["/opt/game/Mods"])
    assert audit[0] == "sudo -n /usr/local/sbin/gp-clamav-ensure"
    assert audit[1].startswith("cd / && sudo -n -u steam -- bash -c ")


@pytest.mark.parametrize("script", [antivirus.SCAN_SCRIPT_AS_STEAM, antivirus.AUDIT_SCRIPT_AS_STEAM])
def test_a_variante_do_steam_nao_instala_nada_e_continua_falhando_fechada(script):
    assert "apt-get" not in script
    assert "freshclam" not in script
    assert 'refuse "ClamAV is not installed on this server" 2' in script
    assert "CLAMSCAN_OPTS" in script


def test_a_variante_do_steam_so_troca_o_bloco_de_instalacao():
    """The scan rule is ONE text: everything but the install block is the same in both modes."""
    assert antivirus.SCAN_SCRIPT_AS_STEAM.replace(antivirus._CHECK, antivirus._ENSURE) == antivirus.SCAN_SCRIPT


def test_pasta_de_espera_e_mover_rodam_como_steam_no_modo_helper():
    assert antivirus.incoming_command(HELPER, "/var/tmp/gamepanel-incoming-ab").startswith(
        "cd / && sudo -n -u steam -- bash -c ")
    assert antivirus.place_command(LEGACY, "/var/tmp/gamepanel-incoming-ab", "/opt/game/Mods") == quote_command(
        "bash", "-c", antivirus.PLACE_SCRIPT, "gp", "/var/tmp/gamepanel-incoming-ab", "/opt/game/Mods")
