"""O antivirus dos mods (games/mods/antivirus.py), rodando os scripts DE VERDADE no bash.

O ClamAV nao esta aqui: `clamscan`, `freshclam` e `apt-get` sao falsos, num PATH proprio.
O que se prova e a DECISAO do script - quando recusa, o que apaga, que nada passa calado -,
e nao a deteccao, que e do ClamAV.
"""
from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from gamepanel.games.mods import antivirus, shroudtopia_remote, thunderstore_remote

pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="script bash; roda no container"),
    pytest.mark.skipif(shutil.which("bash") is None, reason="sem bash"),
]

# O clamscan falso: "MALWARE" no conteudo = achado (codigo 1), arquivo "quebrado" = erro (2).
FAKE_CLAMSCAN = """#!/bin/sh
for last; do :; done
if grep -rl MALWARE -- "$last" >/dev/null 2>&1; then echo "$last/x: Fake.Malware FOUND"; exit 1; fi
if [ -n "$(find "$last" -name 'quebrado*')" ]; then echo "erro de leitura"; exit 2; fi
echo "$*" > "${CLAMSCAN_ARGS:-/dev/null}"
exit 0
"""
FAKE_FRESHCLAM_OK = '#!/bin/sh\ntouch "$CLAMAV_DB_DIR/daily.cvd"\n'
FAKE_FRESHCLAM_FAIL = "#!/bin/sh\nexit 1\n"
FAKE_APT_FAIL = "#!/bin/sh\nexit 100\n"


def _tool(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    db = tmp_path / "clamav"
    db.mkdir()
    _tool(bin_dir, "clamscan", FAKE_CLAMSCAN)
    _tool(bin_dir, "freshclam", FAKE_FRESHCLAM_OK)
    return {"PATH": f"{bin_dir}:/usr/bin:/bin", "CLAMAV_DB_DIR": str(db),
            "CLAMSCAN_ARGS": str(tmp_path / "args"), "bin": bin_dir, "db": db}


@pytest.fixture
def staging():
    """Uma pasta sob o prefixo que o script aceita (/var/tmp/gamepanel-...)."""
    os.makedirs("/var/tmp", exist_ok=True)
    path = tempfile.mkdtemp(prefix="gamepanel-test-", dir="/var/tmp")
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


def _scan(env: dict, target) -> subprocess.CompletedProcess:
    run_env = {k: v for k, v in env.items() if isinstance(v, str)}
    return subprocess.run(["bash", "-c", antivirus.SCAN_SCRIPT, "gp", str(target)],
                          capture_output=True, text=True, env=run_env, check=False)


def test_mod_limpo_passa_e_continua_na_espera(env, staging):
    (staging / "Mod.pak").write_bytes(b"limpo")
    proc = _scan(env, staging)
    assert proc.returncode == 0, proc.stderr
    assert (staging / "Mod.pak").exists(), "quem move para a pasta de mods e o passo seguinte"


def test_achado_recusa_e_apaga_a_espera(env, staging):
    (staging / "Mod.pak").write_bytes(b"MALWARE")
    proc = _scan(env, staging)
    assert proc.returncode == 1
    assert "Fake.Malware FOUND" in proc.stderr
    assert "NAO foi instalado" in proc.stderr
    assert not staging.exists()


def test_verificacao_que_nao_roda_tambem_recusa(env, staging):
    """Falha FECHADA: "nao consegui verificar" nao pode deixar passar."""
    (staging / "quebrado.pak").write_bytes(b"x")
    proc = _scan(env, staging)
    assert proc.returncode == 2
    assert not staging.exists()


def test_arquivo_grande_ou_zip_com_senha_conta_como_achado(env, staging):
    """Sem as duas opcoes o ClamAV PULA o que passa do limite, calado."""
    (staging / "Mod.pak").write_bytes(b"limpo")
    assert _scan(env, staging).returncode == 0
    args = Path(env["CLAMSCAN_ARGS"]).read_text()
    assert "--alert-exceeds-max=yes" in args
    assert "--alert-encrypted=yes" in args


def test_sem_assinatura_recente_e_sem_atualizacao_recusa(env, staging):
    _tool(env["bin"], "freshclam", FAKE_FRESHCLAM_FAIL)
    (staging / "Mod.pak").write_bytes(b"limpo")
    proc = _scan(env, staging)
    assert proc.returncode == 2
    assert "sem assinaturas" in proc.stderr
    assert not staging.exists()


def test_atualizacao_que_falha_ainda_aceita_assinatura_de_poucos_dias(env, staging):
    """O CDN do ClamAV limita pedidos: uma falha de atualizacao nao pode travar todo mod."""
    _tool(env["bin"], "freshclam", FAKE_FRESHCLAM_FAIL)
    db_file = env["db"] / "daily.cld"
    db_file.write_bytes(b"sig")
    three_days = time.time() - 3 * 86400
    os.utime(db_file, (three_days, three_days))
    (staging / "Mod.pak").write_bytes(b"limpo")
    proc = _scan(env, staging)
    assert proc.returncode == 0, proc.stderr
    assert "a atualizacao falhou" in proc.stdout


def test_sem_clamav_instala_e_se_o_apt_falha_recusa(env, staging):
    if shutil.which("clamscan", path="/usr/bin:/bin"):
        pytest.skip("ClamAV de verdade instalado nesta maquina")
    (env["bin"] / "clamscan").unlink()
    _tool(env["bin"], "apt-get", FAKE_APT_FAIL)
    (staging / "Mod.pak").write_bytes(b"limpo")
    proc = _scan(env, staging)
    assert proc.returncode == 2
    assert "nao consegui instalar o ClamAV" in proc.stderr
    assert not staging.exists()


@pytest.mark.parametrize("bad", ["/opt/game", "/var/tmp", "/var/tmp/gamepanel-x/../../../opt/game", "/tmp/gamepanel-x"])
def test_caminho_fora_da_area_de_verificacao_nao_e_tocado(env, tmp_path, bad):
    """O script APAGA o que recusa: um caminho errado nao pode virar rm -rf na pasta do jogo."""
    proc = _scan(env, bad)
    assert proc.returncode == 2
    assert "caminho" in proc.stderr


# ------------------------------------------------------------------ mover para a pasta de mods

def test_espera_verificada_vai_para_a_pasta_com_backup_do_que_existia(tmp_path):
    os.makedirs("/var/tmp", exist_ok=True)
    incoming = Path(antivirus.incoming_dir(os.urandom(16).hex()))
    incoming.mkdir(mode=0o700)
    try:
        dest = tmp_path / "mods"
        dest.mkdir()
        (dest / "Mod.pak").write_bytes(b"velho")
        (incoming / "Mod.pak").write_bytes(b"novo")
        (incoming / "Outro.pak").write_bytes(b"outro")
        proc = subprocess.run(["bash", "-c", antivirus.PLACE_SCRIPT, "gp", str(incoming), str(dest)],
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert (dest / "Mod.pak").read_bytes() == b"novo"
        assert (dest / "Outro.pak").read_bytes() == b"outro"
        assert [p.read_bytes() for p in dest.glob("Mod.pak.*.bak")] == [b"velho"]
        assert not incoming.exists(), "a espera sai depois de mover"
    finally:
        shutil.rmtree(incoming, ignore_errors=True)


@pytest.mark.parametrize("token", ["", "../x", "ABC", "a b"])
def test_token_de_envio_so_hex(token):
    with pytest.raises(ValueError):
        antivirus.incoming_dir(token)


# ------------------------------------------------------------------ os instaladores remotos

def test_os_dois_instaladores_remotos_verificam_do_mesmo_jeito():
    """Eles rodam soltos no CT e nao importam um ao outro: a copia tem de ser igual."""
    assert inspect.getsource(thunderstore_remote.scanner) == inspect.getsource(shroudtopia_remote.scanner)


def test_instalador_remoto_recusa_pacote_com_achado_e_nao_deixa_rastro(env, monkeypatch):
    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setenv("CLAMAV_DB_DIR", env["CLAMAV_DB_DIR"])
    before = set(os.listdir("/var/tmp"))
    scan = thunderstore_remote.scanner(antivirus.SCAN_SCRIPT)
    scan([("deca-Limpo-1.0.0", b"limpo")])
    with pytest.raises(ValueError, match="antivirus recusou"):
        scan([("deca-Limpo-1.0.0", b"limpo"), ("evil-Pacote-6.6.6", b"MALWARE")])
    assert set(os.listdir("/var/tmp")) == before


def test_instalador_remoto_sem_antivirus_nao_instala(tmp_path, capsys):
    """O painel sempre manda --scan; sem ele, instalar e recusado no proprio CT."""
    assert thunderstore_remote.main(["plugin-install", str(tmp_path), "BepInEx", "BepInExPack_V_Rising",
                                     "deca", "VampireCommandFramework"]) == 1
    assert "antivirus" in capsys.readouterr().out
    assert shroudtopia_remote.main(["loader-install", str(tmp_path)]) == 1


# ------------------------------------------------------------------ verificar o que ja esta instalado

def _audit(env: dict, *paths) -> subprocess.CompletedProcess:
    run_env = {k: v for k, v in env.items() if isinstance(v, str)}
    return subprocess.run(["bash", "-c", antivirus.AUDIT_SCRIPT, "gp", *map(str, paths)],
                          capture_output=True, text=True, env=run_env, check=False)


def test_verificar_instalados_acusa_e_nao_apaga_nada(env, tmp_path):
    """So le: apagar sozinho por um falso positivo derrubaria um mod de que o servidor depende."""
    mods = tmp_path / "mods"
    mods.mkdir()
    (mods / "Bom.dll").write_bytes(b"limpo")
    (mods / "Ruim.dll").write_bytes(b"MALWARE")
    proc = _audit(env, mods)
    assert proc.returncode == 1
    assert "FOUND" in proc.stdout
    assert "Nada foi apagado" in proc.stderr
    assert sorted(p.name for p in mods.iterdir()) == ["Bom.dll", "Ruim.dll"]


def test_verificar_instalados_limpo_e_caminho_que_falta_e_pulado(env, tmp_path):
    loader = tmp_path / "winmm.dll"
    loader.write_bytes(b"limpo")
    proc = _audit(env, loader, tmp_path / "nao-existe")
    assert proc.returncode == 0, proc.stderr
    assert "pulado" in proc.stdout
    assert "nada encontrado" in proc.stdout
    args = Path(env["CLAMSCAN_ARGS"]).read_text()
    assert str(loader) in args and "nao-existe" not in args
    assert "--alert-exceeds-max=yes" in args, "a mesma regra da verificacao de envio"


def test_servidor_sem_mod_nenhum_nem_instala_o_clamav(env, tmp_path):
    """Nada para verificar = nada para instalar: servidor sem mod nao paga o ClamAV."""
    (env["bin"] / "clamscan").unlink()
    _tool(env["bin"], "apt-get", "#!/bin/sh\necho apt chamado >&2\nexit 100\n")
    proc = _audit(env, tmp_path / "nao-existe")
    assert proc.returncode == 0
    assert "nenhum mod instalado" in proc.stdout
    assert "apt chamado" not in proc.stderr


def test_verificar_instalados_sem_assinatura_falha_fechado(env, tmp_path):
    _tool(env["bin"], "freshclam", FAKE_FRESHCLAM_FAIL)
    (tmp_path / "Mod.pak").write_bytes(b"limpo")
    proc = _audit(env, tmp_path / "Mod.pak")
    assert proc.returncode == 2
    assert "nada foi verificado" in proc.stderr
