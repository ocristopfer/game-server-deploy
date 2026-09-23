"""Backend Proxmox real contra um Proxmox falso que repete as regras do servidor de verdade."""
from __future__ import annotations

import pytest
from fake_http import FakeServer

from gamebroker.integrations.http_client import Client
from gamebroker.runtime.base import CtSpec
from gamebroker.runtime.proxmox import ConfigProxmox, Proxmox, ProxmoxError

ESPEC = CtSpec(ctid=300, hostname="alfa-300", ip="10.0.0.30", game="alfa",
                          memory_mb=4096, cores=2, disk_gb=20)


def test_criar_envia_o_que_o_proxmox_aceita(pve):
    pve.backend.create_ct(ESPEC)
    ct = pve.fake.cts[300]
    assert ct["features"] == "nesting=1", "sem keyctl: so o root@pam pode"
    assert ct["pool"] == "games"
    assert ct["net0"] == "name=eth0,bridge=vmbr1,ip=10.0.0.30/24,gw=192.168.2.1,type=veth"
    assert ct["rootfs"] == "vm-pool:20"
    assert (ct["memory"], ct["cores"], ct["unprivileged"]) == ("4096", "2", "1")
    assert "AAAAC3Nza-chave-de-teste" in ct["chaves"]


def test_tag_e_gravada_depois_da_criacao_nao_na_criacao(pve):
    pve.backend.create_ct(ESPEC)
    assert pve.fake.cts[300]["tags"] == "gamepanel-broker"
    methods = [(m, c) for m, c, _ in pve.server.requisicoes if m in ("POST", "PUT")]
    assert methods[0][0] == "POST"
    assert methods[1] == ("PUT", "/api2/json/nodes/pve/lxc/300/config")


def test_tag_que_falha_nao_derruba_a_criacao(pve):
    pve.fake.falha_na_tag = True
    pve.backend.create_ct(ESPEC)
    assert 300 in pve.fake.cts
    assert pve.backend.belongs_to_broker(300), "a identidade e o pool, nao a tag"


def test_tarefa_com_warnings_e_sucesso(pve):
    pve.fake.saida_da_criacao = "WARNINGS: 1"
    pve.backend.create_ct(ESPEC)


def test_espera_a_tarefa_terminar(pve):
    pve.fake.rodadas_ate_parar = 3
    pve.backend.create_ct(ESPEC)
    assert len(pve.esperas) == 3
    assert set(pve.esperas) == {2.0}


def test_tarefa_que_nunca_termina_estoura_o_tempo(pve):
    pve.fake.rodadas_ate_parar = 10_000
    with pytest.raises(ProxmoxError, match="excedeu o tempo"):
        pve.backend.create_ct(ESPEC)


def test_tarefa_que_falha_traz_a_causa_e_o_fim_do_log(pve):
    pve.fake.saida_da_criacao = "unable to create CT 300 - storage full"
    with pytest.raises(ProxmoxError) as error:
        pve.backend.create_ct(ESPEC)
    assert "storage full" in str(error.value)
    assert "Systemd 257" in str(error.value)


def test_erro_de_autenticacao_mostra_o_status_e_nao_o_token(pve):
    pve.backend._c = Client(pve.server.url, {"Authorization": "PVEAPIToken=errado"})
    with pytest.raises(ProxmoxError) as error:
        pve.backend.create_ct(ESPEC)
    assert "HTTP 401" in str(error.value)
    assert "errado" not in str(error.value)


def test_ct_ja_existente_nao_e_sobrescrito(pve):
    pve.fake.external(300)
    with pytest.raises(ProxmoxError, match="already exists"):
        pve.backend.create_ct(ESPEC)
    assert pve.fake.cts[300]["hostname"] == "de-fora"


def test_iniciar_e_parar(pve):
    pve.backend.create_ct(ESPEC)
    pve.backend.start(300)
    assert pve.fake.cts[300]["status"] == "running"
    pve.backend.stop(300)
    assert pve.fake.cts[300]["status"] == "stopped"


def test_destruir_ct_ligado_para_antes(pve):
    pve.backend.create_ct(ESPEC)
    pve.backend.start(300)
    pve.backend.destroy(300)
    assert 300 not in pve.fake.cts


def test_destruir_ct_parado(pve):
    pve.backend.create_ct(ESPEC)
    pve.backend.destroy(300)
    assert 300 not in pve.fake.cts


def test_nao_mexe_em_ct_fora_do_pool(pve):
    pve.fake.external(210, net0="name=eth0,ip=192.168.2.20/24")
    for action in (pve.backend.destroy, pve.backend.stop):
        with pytest.raises(ProxmoxError, match="nao esta no pool"):
            action(210)
    assert 210 in pve.fake.cts
    assert not any(m == "DELETE" for m, _, _ in pve.server.requisicoes)


def test_pertence_ao_broker(pve):
    pve.backend.create_ct(ESPEC)
    pve.fake.external(210)
    assert pve.backend.belongs_to_broker(300)
    assert not pve.backend.belongs_to_broker(210)
    assert not pve.backend.belongs_to_broker(999)


def test_ctids_e_ips_do_que_o_token_enxerga(pve):
    pve.backend.create_ct(ESPEC)
    pve.fake.external(210, net0="name=eth0,ip=192.168.2.20/24")
    ctids, ips = pve.backend.ctids_and_ips()
    assert ctids == {300}, "CT fora do pool nao aparece: o token nao o enxerga"
    assert ips == {"10.0.0.30"}


def test_acessivel(pve):
    assert pve.backend.reachable() is True
    pve.server.stop()
    assert pve.backend.reachable() is False


def test_espera_usa_o_upid_codificado(pve):
    pve.backend.create_ct(ESPEC)
    paths = [c for m, c, _ in pve.server.requisicoes if "/tasks/" in c]
    assert paths
    assert all(c.startswith("/api2/json/nodes/pve/tasks/UPID:pve:") for c in paths)


# --- validacao da config ---------------------------------------------------------------

BASE = dict(node="pve", pool="games", storage="vm-pool", bridge="vmbr1", gateway="192.168.2.1",
            template="vm-pool-data:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst",
            chaves_ssh=("ssh-ed25519 AAAA x",))


@pytest.mark.parametrize("campo", ["node", "pool", "storage", "bridge"])
@pytest.mark.parametrize("valor", ["a b", "a/b", "a;b", "", "$(x)"])
def test_config_recusa_nome_perigoso(campo, valor):
    with pytest.raises(ValueError):
        ConfigProxmox(**{**BASE, campo: valor})


@pytest.mark.parametrize("template", ["debian.tar.zst", "s:iso/x.iso", "s:vztmpl/../x", "s:vztmpl/a b"])
def test_config_recusa_template_estranho(template):
    with pytest.raises(ValueError, match="template"):
        ConfigProxmox(**{**BASE, "template": template})


@pytest.mark.parametrize("chaves", [(), ("nao-e-chave",), ("ssh-ed25519 A\nssh-ed25519 B",)])
def test_config_recusa_chaves_ruins(chaves):
    with pytest.raises(ValueError, match="chaves_ssh"):
        ConfigProxmox(**{**BASE, "chaves_ssh": chaves})


def test_backend_sem_servidor_e_erro_de_conexao_nao_excecao_solta():
    server = FakeServer(lambda *_a: (200, {}))
    url = server.url
    server.stop()
    backend = Proxmox(Client(url, {}), ConfigProxmox(**BASE), sleep=lambda _s: None)
    from gamebroker.integrations.http_client import ConnectionFailed
    with pytest.raises(ConnectionFailed):
        backend.ctids_and_ips()


def test_sonda_de_saude_nao_espera_o_prazo_inteiro(monkeypatch):
    """Firewall que descarta o pacote deixaria a sonda esperando 30 s: a saude responderia lenta
    justo quando esta quebrada."""
    import time

    import gamebroker.runtime.proxmox as modulo
    monkeypatch.setattr(modulo, "SONDA_TIMEOUT", 0.3)
    server = FakeServer(lambda *_a: (time.sleep(1.5), (200, {}))[1])
    try:
        backend = Proxmox(Client(server.url, {}, timeout=30), ConfigProxmox(**BASE), sleep=lambda _s: None)
        start_at = time.monotonic()
        assert backend.reachable() is False
        assert time.monotonic() - start_at < 1.2
    finally:
        server.stop()
