"""Configuracao de producao (env -> ConfigBroker), montagem do servico real e ping."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fake_http import KEY_OPN, SECRET_OPN, TOKEN_PVE
from fake_ssh import BLOB, PUBLIC_KEY, FakeRunner

import gamebroker.wsgi as prod
from gamebroker.config import ConfigError, load
from gamebroker.runtime.fakes import FakeNetwork
from gamebroker.runtime.network import RealNetwork

TOKEN_BROKER = "b" * 48
PANEL_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainelPainelPainelPainelPainel painel@gp"
SECRETS = (TOKEN_BROKER, TOKEN_PVE, SECRET_OPN)


@pytest.fixture
def env(tmp_path: Path, games_dir: Path) -> dict[str, str]:
    """Um ambiente COMPLETO e valido (Proxmox/OPNsense em https com impressao)."""
    ssh = tmp_path / "ssh"
    ssh.mkdir()
    (ssh / "id_ed25519.pub").write_text(PUBLIC_KEY + "\n", encoding="utf-8")
    lib = tmp_path / "lib"
    lib.mkdir()
    for name in ("ct-install.sh", "ct-phases.sh"):
        (lib / name).write_text("#!/bin/bash\n")
    return {
        "BROKER_TOKEN": TOKEN_BROKER, "BROKER_ALLOW_IPS": "192.168.2.19",
        "BROKER_STATE_DIR": str(tmp_path / "state"), "BROKER_GAMES_DIR": str(games_dir),
        "BROKER_LIB_DIR": str(lib), "BROKER_SSH_KEY": str(ssh / "id_ed25519"),
        "BROKER_PANEL_PUBKEY": PANEL_KEY, "BROKER_GATEWAY": "192.168.2.1",
        "BROKER_IP_PREFIX": "192.168.2", "BROKER_IP_INICIO": "30", "BROKER_IP_FIM": "40",
        "PROXMOX_URL": "https://192.168.1.254:8006", "PROXMOX_TOKEN": TOKEN_PVE,
        "PROXMOX_CERT_SHA256": ":".join(["9F"] * 32), "PROXMOX_NODE": "pve", "PROXMOX_POOL": "games",
        "PROXMOX_STORAGE": "vm-pool", "PROXMOX_BRIDGE": "vmbr1",
        "PROXMOX_TEMPLATE": "vm-pool-data:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst",
        "OPNSENSE_URL": "https://192.168.1.1:8443", "OPNSENSE_KEY": KEY_OPN, "OPNSENSE_SECRET": SECRET_OPN,
        "OPNSENSE_CERT_SHA256": "ab" * 32, "OPNSENSE_WAN": "wan",
    }


# --- carregar ------------------------------------------------------------------------------

def test_ambiente_completo_carrega(env):
    cfg = load(env)
    assert cfg.token == TOKEN_BROKER
    assert cfg.allowed_ips == ("192.168.2.19",)
    assert cfg.ips[0] == "192.168.2.30"
    assert cfg.ips[-1] == "192.168.2.40"
    assert (cfg.ctids.start, cfg.ctids.stop - 1) == (300, 399)
    assert cfg.proxmox_fingerprint == "9f" * 32, "normalizada (sem dois-pontos, minuscula)"
    assert cfg.proxmox.ssh_keys == (PUBLIC_KEY, PANEL_KEY), "as DUAS chaves entram no CT novo"
    assert cfg.ssh.blob == BLOB
    assert (cfg.max_instances, cfg.max_creations_per_hour) == (8, 10)
    assert cfg.opnsense_wan == "wan"


def test_valores_opcionais_sobrescrevem_os_padroes(env):
    env.update(BROKER_CTID_INICIO="500", BROKER_CTID_FIM="510", BROKER_MAX_INSTANCIAS="3",
               BROKER_MAX_CREATIONS_PER_HOUR="1", OPNSENSE_WAN="opt1")
    cfg = load(env)
    assert (cfg.ctids.start, cfg.ctids.stop - 1, cfg.max_instances, cfg.max_creations_per_hour) == (500, 510, 3, 1)
    assert cfg.opnsense_wan == "opt1"


def test_padroes_da_faixa_de_portas_e_do_ctid(env):
    cfg = load(env)
    assert (cfg.ports.start, cfg.ports.stop - 1) == (31000, 31999)
    assert cfg.ctid_base == 0, "sem BROKER_CTID_BASE o CTID continua sendo escolhido a parte"


def test_ctid_base_e_faixa_de_portas_configuraveis(env):
    env.update(BROKER_CTID_BASE="200", BROKER_IP_INICIO="102", BROKER_IP_FIM="110",
               BROKER_PORT_INICIO="40000", BROKER_PORT_FIM="40099")
    cfg = load(env)
    assert cfg.ctid_base == 200
    assert (cfg.ports.start, cfg.ports.stop - 1) == (40000, 40099)
    assert (cfg.ips[0], cfg.ips[-1]) == ("192.168.2.102", "192.168.2.110")


@pytest.mark.parametrize(("name", "value"), [
    ("BROKER_PORT_INICIO", "80"), ("BROKER_PORT_INICIO", "abc"), ("BROKER_PORT_FIM", "70000"),
    ("BROKER_CTID_BASE", "-1"), ("BROKER_CTID_BASE", "abc"),
])
def test_faixa_de_portas_e_base_invalidas(env, name, value):
    env[name] = value
    with pytest.raises(ConfigError, match=name):
        load(env)


def test_faixa_de_portas_invertida(env):
    env.update(BROKER_PORT_INICIO="32000", BROKER_PORT_FIM="31000")
    with pytest.raises(ConfigError, match="BROKER_PORT_FIM"):
        load(env)


def test_ctid_base_pequena_demais_deixaria_o_ctid_abaixo_de_100(env):
    # Base 10 + primeiro IP .30 = CTID 40: o Proxmox nao aceita CTID abaixo de 100.
    env["BROKER_CTID_BASE"] = "10"
    with pytest.raises(ConfigError, match="BROKER_CTID_BASE"):
        load(env)


REQUIRED = ["BROKER_TOKEN", "BROKER_PANEL_PUBKEY", "BROKER_GATEWAY", "BROKER_IP_PREFIX", "PROXMOX_URL",
                "PROXMOX_TOKEN", "PROXMOX_NODE", "PROXMOX_STORAGE", "PROXMOX_TEMPLATE", "PROXMOX_BRIDGE",
                "OPNSENSE_URL", "OPNSENSE_KEY", "OPNSENSE_SECRET"]


@pytest.mark.parametrize("name", REQUIRED)
def test_variavel_obrigatoria_ausente_e_nomeada(env, name):
    del env[name]
    with pytest.raises(ConfigError) as error:
        load(env)
    assert any(p.startswith(f"{name}:") for p in error.value.problems)


def test_todos_os_problemas_de_uma_vez_sem_duplicar(env):
    for name in ("PROXMOX_NODE", "BROKER_GATEWAY", "OPNSENSE_KEY", "BROKER_TOKEN"):
        del env[name]
    with pytest.raises(ConfigError) as error:
        load(env)
    names = [p.split(":")[0] for p in error.value.problems]
    assert sorted(names) == ["BROKER_GATEWAY", "BROKER_TOKEN", "OPNSENSE_KEY",
                             "PROXMOX_NODE"], "cada falta aparece UMA vez"


@pytest.mark.parametrize(("name", "value", "chunk"), [
    ("BROKER_TOKEN", "curto", "ao menos 32"),
    ("BROKER_ALLOW_IPS", "192.168.2.19, nao-e-ip", "nao e um IPv4"),
    ("BROKER_IP_INICIO", "abc", "inteiro"),
    ("BROKER_IP_INICIO", "0", "inteiro"),
    ("BROKER_IP_FIM", "255", "inteiro"),
    ("BROKER_MAX_INSTANCIAS", "0", "inteiro"),
    ("BROKER_MAX_INSTANCIAS", "-1", "inteiro"),
    ("BROKER_CTID_INICIO", "50", "inteiro"),
    ("PROXMOX_CERT_SHA256", "isto-nao-e-hex", "invalida"),
    ("OPNSENSE_CERT_SHA256", "9F:92", "invalida"),
    ("PROXMOX_URL", "ftp://x", r"http\(s\)://"),
    ("PROXMOX_URL", "http://192.168.1.254:8006", "so em loopback"),
    ("OPNSENSE_URL", "http://192.168.1.1", "so em loopback"),
    ("PROXMOX_POOL", "pool com espaco", "PROXMOX_*"),
    ("PROXMOX_TEMPLATE", "debian.tar.zst", "template"),
    ("BROKER_PANEL_PUBKEY", "nao-e-chave", "PROXMOX_*"),
])
def test_valor_invalido(env, name, value, chunk):
    env[name] = value
    with pytest.raises(ConfigError, match=chunk):
        load(env)


def test_faixas_invertidas(env):
    env.update(BROKER_IP_INICIO="50", BROKER_IP_FIM="40", BROKER_CTID_INICIO="400", BROKER_CTID_FIM="300")
    with pytest.raises(ConfigError) as error:
        load(env)
    text = str(error.value)
    assert "BROKER_CTID_FIM" in text
    assert "BROKER_IP_PREFIX/INICIO/FIM" in text


@pytest.mark.parametrize("name", ["PROXMOX_CERT_SHA256", "OPNSENSE_CERT_SHA256"])
def test_https_exige_impressao_do_certificado(env, name):
    del env[name]
    with pytest.raises(ConfigError, match=f"{name}: obrigatoria com https"):
        load(env)


def test_loopback_http_nao_exige_impressao(env):
    env.update(PROXMOX_URL="http://127.0.0.1:9999", OPNSENSE_URL="http://127.0.0.1:9998")
    del env["PROXMOX_CERT_SHA256"], env["OPNSENSE_CERT_SHA256"]
    assert load(env).proxmox_url == "http://127.0.0.1:9999"


def test_chave_publica_do_broker_ausente_e_problema(env):
    Path(env["BROKER_SSH_KEY"] + ".pub").unlink()
    with pytest.raises(ConfigError, match=r"BROKER_SSH_KEY\.pub"):
        load(env)


def test_pasta_lib_incompleta(env):
    (Path(env["BROKER_LIB_DIR"]) / "ct-phases.sh").unlink()
    with pytest.raises(ConfigError, match=r"BROKER_LIB_DIR: .*ct-phases.sh"):
        load(env)


@pytest.mark.parametrize("name", ["BROKER_TOKEN", "PROXMOX_TOKEN", "OPNSENSE_SECRET", "OPNSENSE_KEY"])
def test_nenhuma_mensagem_de_erro_carrega_segredo(env, name):
    """Erro de config vai para o journal: o NOME da variavel pode aparecer, o VALOR nunca."""
    env[name] = "curto"
    env["BROKER_IP_INICIO"] = "abc"
    env["PROXMOX_CERT_SHA256"] = "lixo"
    with pytest.raises(ConfigError) as error:
        load(env)
    for secret in SECRETS:
        assert secret not in str(error.value)


# --- montagem do servico real (contra os falsos HTTP) ---------------------------------------------

@pytest.fixture
def env_local(env, pve, opn):
    """O mesmo ambiente, mas com Proxmox e OPNsense apontando para os falsos em 127.0.0.1."""
    env.update(PROXMOX_URL=pve.server.url, OPNSENSE_URL=opn.server.url,
               BROKER_ALLOW_IPS="127.0.0.1")  # o test_client do Flask chega de 127.0.0.1
    del env["PROXMOX_CERT_SHA256"], env["OPNSENSE_CERT_SHA256"]
    return env


def test_criar_de_ponta_a_ponta_pela_api_de_producao(env_local, pve, opn):
    executor = FakeRunner()
    app = prod.create_app_from_config(load(env_local), executor=executor, network=FakeNetwork(),
                                   run=lambda task: task())
    http = app.test_client()
    auth = {"Authorization": f"Bearer {TOKEN_BROKER}", "X-Actor": "zeca"}

    response = http.post("/v1/instances", headers=auth, json={"game": "alfa", "name": "Um"})

    assert response.status_code == 202
    operation = http.get(f"/v1/operations/{response.get_json()['operation_id']}", headers=auth).get_json()
    assert operation["state"] == "ok"
    ct = pve.fake.cts[300]
    assert PUBLIC_KEY in ct["keys"], "chave do broker: para instalar"
    assert PANEL_KEY in ct["keys"], "chave do painel: para operar depois"
    assert ct["net0"].endswith("ip=192.168.2.30/24,gw=192.168.2.1,type=veth")
    assert sorted(r["destination.port"] for r in opn.fake.rules.values()) == ["7001", "7002"]
    assert any("bash ct-install.sh" in c for c in executor.commands())
    assert (Path(env_local["BROKER_STATE_DIR"]) / "broker.db").exists()


def test_a_api_de_producao_recusa_quem_nao_esta_na_lista_de_ips(env_local):
    env_local["BROKER_ALLOW_IPS"] = "10.9.9.9"
    app = prod.create_app_from_config(load(env_local), executor=FakeRunner(), network=FakeNetwork())
    response = app.test_client().get("/v1/health", headers={"Authorization": f"Bearer {TOKEN_BROKER}"})
    assert response.status_code == 403


def test_ambiente_ruim_derruba_o_start_com_a_lista_e_sem_segredo(env, capsys):
    del env["PROXMOX_NODE"]
    env["BROKER_IP_INICIO"] = "abc"
    with pytest.raises(SystemExit) as output:
        prod.create_app_from_env(env)
    assert output.value.code == 2
    error = capsys.readouterr().err
    assert "NAO SUBIU" in error
    assert "PROXMOX_NODE" in error
    assert "BROKER_IP_INICIO" in error
    for secret in SECRETS:
        assert secret not in error


# --- ping -----------------------------------------------------------------------------------------------

def _ping(monkeypatch, retorno=None, error=None):
    calls: list[list[str]] = []

    def fake(argv, **_kw):
        calls.append(argv)
        if error is not None:
            raise error
        return subprocess.CompletedProcess(argv, retorno)

    monkeypatch.setattr(subprocess, "run", fake)
    return calls


def test_ping_que_responde_significa_ip_em_uso(monkeypatch):
    calls = _ping(monkeypatch, retorno=0)
    assert RealNetwork().answers("192.168.2.30") is True
    assert calls[0][:4] == ["ping", "-c", "1", "-W"]
    assert calls[0][-1] == "192.168.2.30"


def test_ping_sem_resposta_significa_livre(monkeypatch):
    _ping(monkeypatch, retorno=1)
    assert RealNetwork().answers("192.168.2.30") is False


@pytest.mark.parametrize("error", [OSError("sem ping"), subprocess.TimeoutExpired("ping", 4)])
def test_ping_que_nao_roda_nao_derruba_a_criacao(monkeypatch, error):
    _ping(monkeypatch, error=error)
    assert RealNetwork().answers("192.168.2.30") is False


@pytest.mark.parametrize("ip", ["10.0.0.300", "nao-e-ip", "10.0.0.30; rm -rf /", "-f", ""])
def test_ip_estranho_nunca_chega_ao_ping(monkeypatch, ip):
    calls = _ping(monkeypatch, retorno=0)
    with pytest.raises(ValueError):
        RealNetwork().answers(ip)
    assert calls == []


# --- conta Steam (opcional) -----------------------------------------------------------------

def test_sem_conta_steam_o_jogo_que_exige_conta_fica_manual(env):
    cfg = load(env)
    assert cfg.ssh.steam is None
    catalog = prod.build_service(cfg).catalog
    assert not catalog.get("conta").creatable


def test_com_conta_steam_o_jogo_que_exige_conta_vira_criavel(env):
    env.update(STEAM_USER="conta_servidor", STEAM_PASS="S3nha!forte")
    cfg = load(env)
    assert cfg.ssh.steam is not None and cfg.ssh.steam.user == "conta_servidor"
    assert prod.build_service(cfg).catalog.get("conta").creatable


@pytest.mark.parametrize("missing", ["STEAM_USER", "STEAM_PASS"])
def test_so_metade_da_conta_e_erro_e_nao_conta_desligada(env, missing):
    env.update(STEAM_USER="conta_servidor", STEAM_PASS="S3nha!forte")
    del env[missing]
    with pytest.raises(ConfigError, match="STEAM_USER/STEAM_PASS"):
        load(env)


def test_senha_invalida_e_nomeada_sem_o_valor(env):
    env.update(STEAM_USER="conta_servidor", STEAM_PASS="tem'aspa")
    with pytest.raises(ConfigError) as caught:
        load(env)
    assert "STEAM_USER/STEAM_PASS" in str(caught.value)
    assert "tem'aspa" not in str(caught.value)
