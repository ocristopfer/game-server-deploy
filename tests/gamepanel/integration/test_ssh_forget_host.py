"""`SshClient.forget_host` against the real `ssh-keygen`: it is what understands the hashed
line (`HashKnownHosts yes`, the Debian default), which a hand-made edit would not find."""
import shutil
import subprocess

import pytest

from gamepanel.runtime.ssh import SshClient, SshConfig

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="sem ssh-keygen no PATH")

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def client(known_hosts) -> SshClient:
    return SshClient(lambda: SshConfig(key="x", known_hosts=str(known_hosts),
                                       control_dir="x", control_persist="1m"))


def test_apaga_so_a_chave_do_host_pedido(tmp_path):
    known = tmp_path / "known_hosts"
    known.write_text(f"10.0.0.4 {KEY}\n10.0.0.40 {KEY}\n", encoding="utf-8")
    client(known).forget_host("10.0.0.4")
    assert known.read_text(encoding="utf-8") == f"10.0.0.40 {KEY}\n"


def test_apaga_a_linha_com_hash(tmp_path):
    known = tmp_path / "known_hosts"
    known.write_text(f"10.0.0.4 {KEY}\n", encoding="utf-8")
    subprocess.run(["ssh-keygen", "-H", "-f", str(known)], capture_output=True, check=True)
    assert "10.0.0.4" not in known.read_text(encoding="utf-8"), "a linha virou hash"
    client(known).forget_host("10.0.0.4")
    assert KEY.split()[1] not in known.read_text(encoding="utf-8")


def test_sem_arquivo_nao_levanta(tmp_path):
    client(tmp_path / "nao-existe").forget_host("10.0.0.4")
