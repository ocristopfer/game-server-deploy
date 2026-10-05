"""SSH installer: what goes into install.env, the order of the commands and the key cleanup."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fake_ssh import BLOB, PUBLIC_KEY, FakeRunner

from gamebroker.runtime.ssh_installer import (
    LIB_FILES,
    REMOTE_DEST,
    ConfigSsh,
    ExecutorReal,
    InstallError,
    SshInstaller,
    SteamAccount,
    build_env,
)
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import validate_dynamic


@pytest.fixture
def lib_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "lib"
    folder.mkdir()
    for name in LIB_FILES:
        (folder / name).write_text("#!/bin/bash\n", encoding="utf-8")
    return folder


@pytest.fixture
def config(tmp_path: Path, lib_dir: Path) -> ConfigSsh:
    return ConfigSsh(private_key=tmp_path / "id_broker", public_key=PUBLIC_KEY, lib_dir=lib_dir)


@pytest.fixture
def game(game_data):
    return validate_dynamic(game_data)


@pytest.fixture
def ports():
    return [AllocatedPort(7777, 7777, "udp", "jogo"), AllocatedPort(27016, 27016, "udp", "query")]


@pytest.fixture
def installer(config):
    executor = FakeRunner()
    return SshInstaller(config, executor, sleep=lambda _s: None), executor


def _install(installer, game, ports, log=None):
    inst, executor = installer
    lines: list[str] = []
    inst.install("10.0.0.30", game, ports, log or lines.append)
    return executor, lines


# --- install.env -------------------------------------------------------------------------------

def _values(env: str) -> dict[str, str]:
    """Read install.env the way the CT reads it: with the `source` of a real bash."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash nao esta no PATH")
    names = [line.split("=", 1)[0] for line in env.splitlines() if "=" in line and line[0].isupper()]
    script = "set -a\nsource /dev/stdin <<'FIM'\n" + env + "FIM\n" + "".join(
        f'printf "%s\\0" "{n}" "${{{n}}}"\n' for n in names)
    output = subprocess.run([bash, "-c", script], capture_output=True, check=True, text=True,
                           encoding="utf-8").stdout.split("\0")
    # `printf` ends each piece with a NUL, so `split` returns an empty piece at the end;
    # without dropping it, `zip` would swallow it silently (it was `zip` without `strict`,
    # and ruff's B905 pointed it out). Explicit here, `strict` right below: if the count
    # turns odd for some other reason, the test BLOWS UP instead of comparing against a
    # dictionary smaller than the real install.env.
    if output and output[-1] == "":
        output.pop()
    return dict(zip(output[0::2], output[1::2], strict=True))


def test_env_completo_de_um_jogo_dinamico(game, ports):
    values = _values(build_env(game, ports))
    assert values["GAME_KEY"] == "meujogo"
    assert values["STEAM_APP_ID"] == "123456"
    assert values["GAME_PORT"] == "7777"
    assert values["QUERY_PORT"] == "27016"
    assert values["GAME_PORTS"] == "7777/udp 27016/udp"
    assert values["START_ARGS"] == "-port={PORT} -queryport={QUERY_PORT}"
    assert values["RECIPES"] == "steamclient-sdk64"
    assert values["WINDOWS_RUNTIME"] == ""
    assert values["PRE_INSTALL_CMD"] == values["POST_INSTALL_CMD"] == ""


def test_credencial_de_conta_steam_nunca_entra(game, ports):
    env = build_env(game, ports)
    assert "STEAM_ANONYMOUS=1" in env
    assert "STEAM_USER" not in env
    assert "STEAM_PASS" not in env


def test_portas_deslocadas_chegam_ao_jogo(game, ports):
    shifted = [AllocatedPort(7777, 7779, "udp", "jogo"), AllocatedPort(27016, 27018, "udp", "query")]
    values = _values(build_env(game, shifted))
    assert (values["GAME_PORT"], values["QUERY_PORT"]) == ("7779", "27018")
    assert values["GAME_PORTS"] == "7779/udp 27018/udp"


def test_jogo_sem_porta_de_consulta(game_data, ports):
    game_data.update(query_port=0, ports=["7777/udp"])
    game = validate_dynamic(game_data)
    assert _values(build_env(game, ports[:1]))["QUERY_PORT"] == "0"


def test_runtime_de_windows_vira_windows_runtime_e_nao_receita(game_data, ports):
    game_data.update(platform="windows", recipes=["wine", "steamclient-sdk64"])
    values = _values(build_env(validate_dynamic(game_data), ports))
    assert values["WINDOWS_RUNTIME"] == "wine"
    assert values["RECIPES"] == "steamclient-sdk64"
    assert values["STEAM_PLATFORM"] == "windows"


def test_xvfb_vira_windows_runtime_xvfb_e_nao_receita(game_data, ports):
    game_data.update(platform="windows", recipes=["proton", "xvfb"])
    values = _values(build_env(validate_dynamic(game_data), ports))
    assert values["WINDOWS_RUNTIME"] == "proton"
    assert values["WINDOWS_RUNTIME_XVFB"] == "1"
    assert values["RECIPES"] == ""


def test_sem_xvfb_o_x_virtual_fica_desligado(game, ports):
    assert _values(build_env(game, ports))["WINDOWS_RUNTIME_XVFB"] == "0"


def test_wine_e_proton_juntos_sao_recusados(game_data, ports):
    game_data.update(platform="windows", recipes=["wine", "proton"])
    with pytest.raises(InstallError, match="OU"):
        build_env(validate_dynamic(game_data), ports)


# Text that, if quoting failed, would execute something or break the `source`.
HARMFUL = ["'; touch /tmp/pwned; '", "$(touch /tmp/pwned)", "`touch /tmp/pwned`", "a\nb\nc", "aspas ' e \" juntas",
           "\\[LOG\\] (?P<name>.+?) joined", "sem-nada", "${HOME}", "; rm -rf /", "espaco  duplo  "]


@pytest.mark.parametrize("text", HARMFUL)
def test_nenhum_valor_e_interpretado_como_shell(game, ports, text, tmp_path):
    """Curated catalog hooks may hold ANY text: what reaches the CT is exactly that text."""
    curated = replace(game, pre_install=text, post_install=text[::-1], source="curado")
    values = _values(build_env(curated, ports))
    assert values["PRE_INSTALL_CMD"] == text
    assert values["POST_INSTALL_CMD"] == text[::-1]
    assert not Path("/tmp/pwned").exists()


# --- flow --------------------------------------------------------------------------------------

def test_ordem_dos_comandos(installer, game, ports):
    executor, _ = _install(installer, game, ports)
    assert executor.commands() == [
        "true",
        f"install -d -m 700 {REMOTE_DEST}",
        "scp",
        f"cd {REMOTE_DEST} && bash ct-install.sh install.env",
        executor.commands()[-1],  # cleanup
    ]
    assert f"rm -rf {REMOTE_DEST}" in executor.commands()[-1]


def test_scp_leva_a_lib_e_o_env_e_o_env_existe_na_hora(installer, game, ports):
    executor, _ = _install(installer, game, ports)
    scp = next(a for a, _ in executor.calls if a[0] == "scp")
    assert [Path(f).name for f in scp[-6:-1]] == ["ct-install.sh", "ct-phases.sh", "ct-firewall.sh",
                                                  "ct-panel-access.sh", "install.env"]
    assert scp[-1] == f"root@10.0.0.30:{REMOTE_DEST}/"
    assert "GAME_KEY=meujogo" in executor.env_visto
    assert not Path(scp[-2]).exists(), "o env temporario nao fica no disco do broker"


def test_todo_comando_e_lista_sem_shell_e_com_as_opcoes_de_seguranca(installer, game, ports):
    executor, _ = _install(installer, game, ports)
    for argv, _ in executor.calls:
        assert isinstance(argv, list)
        assert argv[0] in ("ssh", "scp")
        assert "BatchMode=yes" in argv, "nunca pergunta senha"
        assert "IdentitiesOnly=yes" in argv
    ssh = next(a for a, _ in executor.calls if a[0] == "ssh")
    assert "root@10.0.0.30" in ssh
    assert ssh[ssh.index("-i") + 1].endswith("id_broker")


def test_o_log_recebe_o_progresso_e_a_chave_removida(installer, game, ports):
    _, lines = _install(installer, game, ports)
    text = "\n".join(lines)
    assert "aguardando o SSH de 10.0.0.30" in text
    assert "INSTALACAO CONCLUIDA" in text
    assert lines[-1] == "chave do broker removida do container"


def test_limpeza_remove_a_chave_do_broker_e_confere(installer, game, ports):
    executor, _ = _install(installer, game, ports)
    cleanup = executor.commands()[-1]
    assert f"grep -vF -- {BLOB}" in cleanup
    assert cleanup.rstrip().endswith(f"! grep -qF -- {BLOB} /root/.ssh/authorized_keys"), \
        "o proprio command falha se a chave continuar la"


def test_timeouts_sao_repassados(installer, game, ports, config):
    executor, _ = _install(installer, game, ports)
    install_run = next(t for a, t in executor.calls if a[-1].endswith("bash ct-install.sh install.env"))
    assert install_run == config.install_timeout


# --- failures ----------------------------------------------------------------------------------------

def test_instalador_que_falha_traz_a_cauda_e_ainda_limpa_a_chave(installer, game, ports):
    inst, executor = installer
    executor.outputs["bash ct-install.sh"] = (1, ["baixando", "ERROR: SteamCMD nao conseguiu instalar o app"])
    with pytest.raises(InstallError, match=r"codigo 1.*SteamCMD nao conseguiu"):
        inst.install("10.0.0.30", game, ports, lambda _l: None)
    assert "rm -rf" in executor.commands()[-1], "a chave do broker sai mesmo com a instalacao falha"


def test_exit_zero_sem_a_marca_de_conclusao_nao_vale(installer, game, ports):
    inst, executor = installer
    executor.outputs["bash ct-install.sh"] = (0, ["so isto"])
    with pytest.raises(InstallError, match="sem confirmar"):
        inst.install("10.0.0.30", game, ports, lambda _l: None)
    assert "rm -rf" in executor.commands()[-1]


def test_falha_no_envio_tambem_limpa(installer, game, ports):
    inst, executor = installer
    executor.outputs["scp"] = (1, [])
    with pytest.raises(InstallError, match="enviar o instalador"):
        inst.install("10.0.0.30", game, ports, lambda _l: None)
    assert "rm -rf" in executor.commands()[-1]


def test_chave_que_nao_sai_faz_a_criacao_falhar(installer, game, ports):
    """A new CT must not be born with permanent broker access."""
    inst, executor = installer
    executor.outputs["grep -vF"] = (1, [])
    with pytest.raises(InstallError, match="remover a chave do broker"):
        inst.install("10.0.0.30", game, ports, lambda _l: None)


def test_limpeza_que_falha_nao_esconde_o_erro_da_instalacao(installer, game, ports):
    inst, executor = installer
    executor.outputs["bash ct-install.sh"] = (1, ["deu ruim"])
    executor.outputs["grep -vF"] = (1, [])
    lines: list[str] = []
    with pytest.raises(InstallError, match="a instalacao falhou"):
        inst.install("10.0.0.30", game, ports, lines.append)
    assert any("AVISO" in line and "remover a chave" in line for line in lines)


def test_espera_o_ssh_subir(installer, game, ports):
    inst, executor = installer
    executor.first_ssh_failures = 3
    _install((inst, executor), game, ports)
    assert executor.commands().count("true") == 4


def test_ssh_que_nunca_sobe_e_erro_e_nao_tenta_limpar(config, game, ports):
    clock = iter(range(0, 10_000, 100))
    executor = FakeRunner()
    executor.first_ssh_failures = 10**6
    inst = SshInstaller(config, executor, sleep=lambda _s: None, now=lambda: float(next(clock)))
    with pytest.raises(InstallError, match="nao respondeu"):
        inst.install("10.0.0.30", game, ports, lambda _l: None)
    assert set(executor.commands()) == {"true"}, "nunca entrou: nada a enviar nem a limpar"


@pytest.mark.parametrize("ip", ["10.0.0.300", "nao-e-ip", "10.0.0.30; rm -rf /", "", "::1"])
def test_ip_invalido_nao_gera_comando(installer, game, ports, ip):
    inst, executor = installer
    with pytest.raises(ValueError):
        inst.install(ip, game, ports, lambda _l: None)
    assert executor.calls == []


# --- batched output ---------------------------------------------------------------------------------------

def test_saida_volumosa_vira_poucas_gravacoes_e_linhas_longas_sao_cortadas(installer, game, ports):
    inst, executor = installer
    executor.outputs["bash ct-install.sh"] = (
        0, [f"progresso {i}%" for i in range(100)] + ["", "x" * 5000, "INSTALACAO CONCLUIDA: ok"])
    writes: list[str] = []
    inst.install("10.0.0.30", game, ports, writes.append)
    assert len(writes) < 20, "100+ linhas nao sao 100+ transacoes no banco"
    assert max(len(g) for g in "\n".join(writes).split("\n")) <= 400
    assert "progresso 99%" in "\n".join(writes)


# --- configuration --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["", "ssh-ed25519", "ssh-ed25519 curta", "ssh-ed25519 " + "A" * 30 + "; rm -rf /"])
def test_chave_publica_invalida(tmp_path, lib_dir, key):
    with pytest.raises(ValueError, match="public_key"):
        ConfigSsh(private_key=tmp_path / "k", public_key=key, lib_dir=lib_dir)


def test_usuario_invalido(tmp_path, lib_dir):
    with pytest.raises(ValueError, match="user"):
        ConfigSsh(private_key=tmp_path / "k", public_key=PUBLIC_KEY, lib_dir=lib_dir, user="root; ls")


def test_lib_incompleta_e_recusada(tmp_path):
    (tmp_path / "ct-install.sh").write_text("x")
    cfg = ConfigSsh(private_key=tmp_path / "k", public_key=PUBLIC_KEY, lib_dir=tmp_path)
    with pytest.raises(ValueError, match=r"ct-phases\.sh"):
        SshInstaller(cfg, FakeRunner())


# --- real executor (with Python itself as the "process") -------------------------------------------------------

def test_executor_real_repassa_linhas_e_devolve_o_codigo():
    lines: list[str] = []
    code = ExecutorReal().run(
        [sys.executable, "-c", "print('um'); print('dois'); import sys; sys.exit(3)"], lines.append, 30)
    assert (code, lines) == (3, ["um", "dois"])


def test_executor_real_mata_o_que_passa_do_prazo():
    code = ExecutorReal().run([sys.executable, "-c", "import time; time.sleep(60)"], None, 0.5)
    assert code != 0


def test_executor_real_binario_inexistente_e_erro_claro():
    with pytest.raises(InstallError, match="nao consegui executar"):
        ExecutorReal().run(["/nao/existe/ssh"], None, 5)


def test_executor_real_nao_le_do_teclado():
    """Closed stdin: an ssh asking for a password/confirmation would fail instead of hanging the broker."""
    probe = "import sys; sys.exit(0 if sys.stdin.read() == '' else 1)"
    code = ExecutorReal().run([sys.executable, "-c", probe], None, 30)
    assert code == 0


# --- Steam account (curated game that cannot download anonymously) -------------------------

STEAM = SteamAccount("conta_servidor", "S3nha!forte")


def test_jogo_que_exige_conta_leva_a_conta_do_broker(game, ports):
    values = _values(build_env(replace(game, needs_account=True), ports, STEAM))
    assert values["STEAM_ANONYMOUS"] == "0"
    assert (values["STEAM_USER"], values["STEAM_PASS"]) == ("conta_servidor", "S3nha!forte")


def test_jogo_anonimo_nao_carrega_a_senha_mesmo_com_conta_configurada(game, ports):
    env = build_env(game, ports, STEAM)
    assert "STEAM_ANONYMOUS=1" in env
    assert "S3nha" not in env and "STEAM_USER" not in env


def test_jogo_que_exige_conta_sem_conta_e_recusado(game, ports):
    with pytest.raises(InstallError, match="conta Steam"):
        build_env(replace(game, needs_account=True), ports)


def test_senha_nunca_aparece_no_log_da_operacao(config, game, ports):
    executor = FakeRunner()
    executor.outputs["ct-install.sh"] = (0, ["Logging in user conta_servidor", "echo S3nha!forte vazou",
                                          "INSTALACAO CONCLUIDA: x"])
    inst = SshInstaller(replace(config, steam=STEAM), executor, sleep=lambda _s: None)
    lines: list[str] = []
    inst.install("10.0.0.30", replace(game, needs_account=True), ports, lines.append)
    assert "S3nha!forte" not in "\n".join(lines)
    assert "echo ****** vazou" in "\n".join(lines)


def test_repr_da_conta_nao_mostra_a_senha():
    assert "S3nha" not in repr(STEAM)
    assert "S3nha" not in repr(ConfigSsh(private_key=Path("k"), public_key=PUBLIC_KEY, lib_dir=Path("."), steam=STEAM))


@pytest.mark.parametrize(("user", "password"), [
    ("conta", "com espaco"), ("conta", "aspa'simples"), ("conta", "linha\nnova"), ("conta", ""),
    ("com espaco", "x"), ("c'onta", "x"), ("x", "x"),
])
def test_conta_que_quebraria_a_linha_do_steamcmd_e_recusada_sem_mostrar_o_valor(user, password):
    with pytest.raises(ValueError) as caught:
        SteamAccount(user, password)
    if password not in ("", "x"):
        assert password not in str(caught.value)


def test_cancelar_mata_o_processo_que_esta_calado():
    # SteamCMD goes minutes without writing anything: the request cannot wait for the next line.
    import threading
    import time
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    code = ExecutorReal().run([sys.executable, "-c", "import time; time.sleep(60)"], None, 60, cancel)
    assert code != 0
    assert time.monotonic() - started < 10


def test_quem_pode_abrir_ssh_vai_no_install_env_para_o_firewall_do_ct(game, ports):
    env = build_env(game, ports, None, ("10.20.1.100", "10.20.1.101"))
    assert "FW_MGMT_SOURCES='10.20.1.100 10.20.1.101'" in env


def test_sem_ips_de_administracao_o_install_env_nao_pede_firewall(game, ports):
    # Without the key ct-phases.sh SKIPS the firewall: applying it without knowing who the
    # panel is would lock the panel out of the freshly created server.
    assert "FW_MGMT_SOURCES" not in build_env(game, ports)


def test_a_lib_real_tem_o_script_do_firewall():
    lib = Path(__file__).resolve().parents[3] / "lib"
    assert all((lib / name).is_file() for name in LIB_FILES)


def test_ajuste_do_wine_do_curado_chega_ao_ct(ports):
    """V Rising needs mscoree ENABLED (BepInEx is .NET); the broker's install.env used to not
    carry the .env's WINE_DLL_OVERRIDES, and the CT was born with the default, which disables it."""
    from gamebroker.services.catalog import load_curated
    games, _ = load_curated(Path(__file__).resolve().parents[3] / "games")
    values = _values(build_env(games["vrising"], ports))
    assert values["WINE_DLL_OVERRIDES"] == "mshtml=;winhttp=n,b"


def test_jogo_da_api_nao_escolhe_dll_do_wine(game, ports):
    assert "WINE_DLL_OVERRIDES" not in build_env(game, ports)


# --- panel access: gamepanel instead of root -------------------------------------------------------

PANEL_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainelPainelPainelPainelPainel painel@gp"


@pytest.fixture
def panel_installer(config):
    executor = FakeRunner()
    cfg = replace(config, panel_public_key=PANEL_KEY)
    return SshInstaller(cfg, executor, sleep=lambda _s: None), executor


def test_a_chave_do_painel_vai_no_install_env_para_o_gamepanel(game, ports):
    values = _values(build_env(game, ports, panel_public_key=PANEL_KEY))
    assert values["PANEL_PUBKEY"] == PANEL_KEY


def test_sem_chave_do_painel_o_install_env_nao_cria_o_gamepanel(game, ports):
    assert "PANEL_PUBKEY" not in build_env(game, ports)


def test_root_e_trancado_no_mesmo_comando_que_tira_a_chave_do_broker(panel_installer, game, ports):
    """The cleanup is the last root SSH session: a lock in a later command would have no way in."""
    executor, lines = _install(panel_installer, game, ports)
    cleanup = executor.commands()[-1]
    assert cleanup.index("ct-panel-access.sh lock") < cleanup.index(f"grep -vF -- {BLOB}")
    assert "/usr/local/lib/gamepanel/ct-panel-access.sh" in cleanup
    assert lines[-1] == "chave do broker removida do container"


def test_trava_que_falha_derruba_a_criacao_mas_a_chave_sai(panel_installer, game, ports):
    inst, executor = panel_installer
    executor.outputs["ct-panel-access.sh lock"] = (3, ["ct-panel-access.sh: ERRO: o root NAO foi trancado"])
    lines: list[str] = []
    with pytest.raises(InstallError, match="trancar o root"):
        inst.install("10.0.0.30", game, ports, lines.append)
    assert f"grep -vF -- {BLOB}" in executor.commands()[-1], "a chave do broker sai do mesmo jeito"
    assert any("NAO foi trancado" in line for line in lines), "o motivo vai para o log da operacao"


def test_instalacao_que_falha_nao_tranca_o_root(panel_installer, game, ports):
    """A failed install may not even have created gamepanel: locking would close the only way in."""
    inst, executor = panel_installer
    executor.outputs["bash ct-install.sh"] = (1, ["deu ruim"])
    with pytest.raises(InstallError, match="a instalacao falhou"):
        inst.install("10.0.0.30", game, ports, lambda _l: None)
    assert "ct-panel-access.sh" not in executor.commands()[-1]
    assert f"grep -vF -- {BLOB}" in executor.commands()[-1]


@pytest.mark.parametrize("bad", ["nao e chave", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainel x'y",
                                 "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainel\nssh-rsa AAAA"])
def test_chave_do_painel_torta_e_recusada(tmp_path, lib_dir, bad):
    with pytest.raises(ValueError, match="panel_public_key"):
        ConfigSsh(private_key=tmp_path / "k", public_key=PUBLIC_KEY, lib_dir=lib_dir, panel_public_key=bad)
