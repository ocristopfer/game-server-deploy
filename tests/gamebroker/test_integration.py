"""Servico completo com os backends REAIS (Proxmox e OPNsense) falando com servidores falsos.

E o caminho que roda em producao; so o instalador (SSH) e a rede (ping) continuam falsos ate
as proximas fases.
"""
from __future__ import annotations

import pytest

from gamebroker.domain.exceptions import OutOfResources
from gamebroker.persistence.db import OP_FAILED, OP_OK, STATE_ACTIVE
from gamebroker.runtime.fakes import FakeInstaller, FakeNetwork
from gamebroker.services.allocator import ips_in_range
from gamebroker.services.instance_service import Config, Service


@pytest.fixture
def real(environment, pve, opn):
    """O `ambiente` (banco, catalogo, relogio) com Proxmox e OPNsense reais no lugar dos falsos."""
    installer = FakeInstaller()
    service = Service(environment.db, environment.catalog, pve.backend, opn.backend, installer,
                      FakeNetwork(), Config(ctids=range(300, 310), ips=ips_in_range("10.0.0", 30, 40)),
                      run=lambda task: task(), clock=environment.clock)
    environment.pve, environment.opn, environment.instalador_real, environment.real_service = pve, opn, installer, service
    return environment


def test_criar_de_ponta_a_ponta(real):
    response = real.real_service.create("alfa", "Servidor do Zeca", "zeca")
    operation = real.real_service.operation(response["operation_id"])
    assert operation["state"] == OP_OK
    assert real.db.instance(response["instance_id"])["state"] == STATE_ACTIVE

    ct = real.pve.fake.cts[300]
    assert ct["pool"] == "games"
    assert ct["tags"] == "gamepanel-broker"
    rules = list(real.opn.fake.rules.values())
    assert sorted(r["destination.port"] for r in rules) == ["7001", "7002"]
    assert {r["target"] for r in rules} == {"10.0.0.30"}
    assert real.opn.fake.applies == 1
    assert operation["result"]["host"] == "10.0.0.30"


def test_falha_na_instalacao_desfaz_no_proxmox_e_no_opnsense(real):
    real.instalador_real.failure = True
    response = real.real_service.create("alfa", "x", "zeca")
    assert real.real_service.operation(response["operation_id"])["state"] == OP_FAILED
    assert real.pve.fake.cts == {}, "o CT criado foi destruido"
    assert real.opn.fake.rules == {}
    assert real.db.count_instances() == 0


def test_porta_ocupada_por_alias_do_usuario_barra_a_criacao(real):
    """A regra 'palworld' do user usa alias e esta DESATIVADA - ainda assim ocupa a porta."""
    real.opn.fake.existing_rule("palworld", "JOGO_PALWORLD", alias=["7001", "27015"], disabled=True)
    with pytest.raises(OutOfResources, match="7001/udp"):
        real.real_service.create("alfa", "x", "zeca")
    assert real.pve.fake.cts == {}, "nada foi criado no Proxmox"


def test_regra_que_o_broker_nao_entende_impede_criar(real):
    """Falha fechada de ponta a ponta: sem entender o firewall, nao cria nada."""
    real.opn.fake.existing_rule("misteriosa", "ALIAS_X", summary_text="<strong>?</strong>")
    with pytest.raises(Exception, match="misteriosa"):
        real.real_service.create("alfa", "x", "zeca")
    assert real.pve.fake.cts == {}
    assert real.db.count_instances() == 0


def test_criar_com_o_instalador_ssh_de_verdade(real, tmp_path):
    """Proxmox e OPNsense reais (contra falsos HTTP) + InstaladorSsh real (com executor que
    grava os comandos): e o caminho de criacao inteiro, exceto o SSH em si."""
    from test_ssh_installer import PUBLIC_KEY, FakeRunner

    from gamebroker.runtime.ssh_installer import ConfigSsh, SshInstaller

    lib = tmp_path / "lib"
    lib.mkdir()
    for name in ("ct-install.sh", "ct-phases.sh"):
        (lib / name).write_text("#!/bin/bash\n")
    executor = FakeRunner()
    ssh = SshInstaller(ConfigSsh(private_key=tmp_path / "k", public_key=PUBLIC_KEY, lib_dir=lib),
                        executor, sleep=lambda _s: None)
    service = Service(real.db, real.catalog, real.pve.backend, real.opn.backend, ssh, FakeNetwork(),
                      Config(ctids=range(300, 310), ips=ips_in_range("10.0.0", 30, 40)),
                      run=lambda task: task(), clock=real.clock)

    response = service.create("alfa", "Um", "zeca")

    assert service.operation(response["operation_id"])["state"] == OP_OK
    assert "GAME_PORT=7001" in executor.env_visto
    assert executor.commands()[-1].startswith("rm -rf /root/gamepanel-install"), "a chave do broker saiu por ultimo"
    assert real.opn.fake.applies == 1, "o firewall abriu DEPOIS da instalacao"
    assert real.pve.fake.cts[300]["pool"] == "games"


def test_desativar_e_remover_de_ponta_a_ponta(real):
    created_one = real.real_service.create("alfa", "Um", "zeca")
    real.real_service.deactivate(created_one["instance_id"], "zeca")
    assert real.opn.fake.rules == {}
    assert real.pve.fake.cts[300]["status"] == "stopped"
    real.real_service.remove(created_one["instance_id"], "Um", "zeca")
    assert real.pve.fake.cts == {}
    assert real.db.taken() == (set(), set(), set())


def test_ct_de_fora_do_pool_nunca_e_destruido_pelo_remover(real):
    created_one = real.real_service.create("alfa", "Um", "zeca")
    real.real_service.deactivate(created_one["instance_id"], "zeca")
    # Alguem move o CT para fora do pool do broker (ou o id passa a ser de outro dono).
    real.pve.fake.cts[300]["pool"] = None
    with pytest.raises(Exception, match="nao pertence ao broker"):
        real.real_service.remove(created_one["instance_id"], "Um", "zeca")
    assert 300 in real.pve.fake.cts
