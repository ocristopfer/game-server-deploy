"""Instalador por SSH: o que vai no install.env, a ordem dos comandos e a limpeza da chave."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from broker.alocador import PortaAlocada
from broker.catalogo import validar_dinamico
from broker.ssh_install import (DESTINO_REMOTO, ConfigSsh, ErroDeInstalacao, ExecutorReal,
                                InstaladorSsh, montar_env)

BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIExemploExemploExemploExemplo"
CHAVE_PUBLICA = f"ssh-ed25519 {BLOB} broker@teste"


class ExecutorFalso:
    """Registra cada comando. `saidas` mapeia um trecho do comando remoto a (codigo, linhas)."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[list[str], float]] = []
        self.saidas: dict[str, tuple[int, list[str]]] = {}
        self.falhas_no_ssh_inicial = 0
        self.env_visto = ""

    def rodar(self, argv, on_linha, timeout):
        self.chamadas.append((list(argv), timeout))
        if argv[0] == "scp":
            self.env_visto = Path(argv[-2]).read_text(encoding="utf-8")  # o arquivo existe AGORA
        comando = argv[-1] if argv[0] == "ssh" else " ".join(argv)
        if argv[0] == "ssh" and comando == "true" and self.falhas_no_ssh_inicial > 0:
            self.falhas_no_ssh_inicial -= 1
            return 255
        for trecho, (codigo, linhas) in self.saidas.items():
            if trecho in comando:
                for linha in linhas:
                    if on_linha is not None:
                        on_linha(linha)
                return codigo
        if on_linha is not None and "ct-install.sh" in comando:
            for linha in ("[10:00:00] instalando", "[10:00:09] INSTALACAO CONCLUIDA: Meu Jogo"):
                on_linha(linha)
        return 0

    def comandos(self) -> list[str]:
        return [a[-1] if a[0] == "ssh" else "scp" for a, _ in self.chamadas]


@pytest.fixture
def pasta_lib(tmp_path: Path) -> Path:
    pasta = tmp_path / "lib"
    pasta.mkdir()
    for nome in ("ct-install.sh", "ct-fases.sh"):
        (pasta / nome).write_text("#!/bin/bash\n", encoding="utf-8")
    return pasta


@pytest.fixture
def config(tmp_path: Path, pasta_lib: Path) -> ConfigSsh:
    return ConfigSsh(chave_privada=tmp_path / "id_broker", chave_publica=CHAVE_PUBLICA, pasta_lib=pasta_lib)


@pytest.fixture
def jogo(dados_de_jogo):
    return validar_dinamico(dados_de_jogo)


@pytest.fixture
def portas():
    return [PortaAlocada(7777, 7777, "udp", "jogo"), PortaAlocada(27016, 27016, "udp", "query")]


@pytest.fixture
def instalador(config):
    executor = ExecutorFalso()
    return InstaladorSsh(config, executor, dormir=lambda _s: None), executor


def _instalar(instalador, jogo, portas, log=None):
    inst, executor = instalador
    linhas: list[str] = []
    inst.instalar("10.0.0.30", jogo, portas, log or linhas.append)
    return executor, linhas


# --- install.env -------------------------------------------------------------------------------

def _valores(env: str) -> dict[str, str]:
    """Le o install.env do jeito que o CT le: com o `source` de um bash de verdade."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash nao esta no PATH")
    nomes = [linha.split("=", 1)[0] for linha in env.splitlines() if "=" in linha and linha[0].isupper()]
    script = "set -a\nsource /dev/stdin <<'FIM'\n" + env + "FIM\n" + "".join(
        f'printf "%s\\0" "{n}" "${{{n}}}"\n' for n in nomes)
    saida = subprocess.run([bash, "-c", script], capture_output=True, check=True, text=True,
                           encoding="utf-8").stdout.split("\0")
    return dict(zip(saida[0::2], saida[1::2]))


def test_env_completo_de_um_jogo_dinamico(jogo, portas):
    valores = _valores(montar_env(jogo, portas))
    assert valores["GAME_KEY"] == "meujogo"
    assert valores["STEAM_APP_ID"] == "123456"
    assert valores["GAME_PORT"] == "7777"
    assert valores["QUERY_PORT"] == "27016"
    assert valores["GAME_PORTS"] == "7777/udp 27016/udp"
    assert valores["START_ARGS"] == "-port={PORT} -queryport={QUERY_PORT}"
    assert valores["RECIPES"] == "steamclient-sdk64"
    assert valores["WINDOWS_RUNTIME"] == ""
    assert valores["PRE_INSTALL_CMD"] == valores["POST_INSTALL_CMD"] == ""


def test_credencial_de_conta_steam_nunca_entra(jogo, portas):
    env = montar_env(jogo, portas)
    assert "STEAM_ANONYMOUS=1" in env
    assert "STEAM_USER" not in env
    assert "STEAM_PASS" not in env


def test_portas_deslocadas_chegam_ao_jogo(jogo, portas):
    deslocadas = [PortaAlocada(7777, 7779, "udp", "jogo"), PortaAlocada(27016, 27018, "udp", "query")]
    valores = _valores(montar_env(jogo, deslocadas))
    assert (valores["GAME_PORT"], valores["QUERY_PORT"]) == ("7779", "27018")
    assert valores["GAME_PORTS"] == "7779/udp 27018/udp"


def test_jogo_sem_porta_de_consulta(dados_de_jogo, portas):
    dados_de_jogo.update(porta_query=0, portas=["7777/udp"])
    jogo = validar_dinamico(dados_de_jogo)
    assert _valores(montar_env(jogo, portas[:1]))["QUERY_PORT"] == "0"


def test_runtime_de_windows_vira_windows_runtime_e_nao_receita(dados_de_jogo, portas):
    dados_de_jogo.update(plataforma="windows", receitas=["wine", "steamclient-sdk64"])
    valores = _valores(montar_env(validar_dinamico(dados_de_jogo), portas))
    assert valores["WINDOWS_RUNTIME"] == "wine"
    assert valores["RECIPES"] == "steamclient-sdk64"
    assert valores["STEAM_PLATFORM"] == "windows"


def test_wine_e_proton_juntos_sao_recusados(dados_de_jogo, portas):
    dados_de_jogo.update(plataforma="windows", receitas=["wine", "proton"])
    with pytest.raises(ErroDeInstalacao, match="OU"):
        montar_env(validar_dinamico(dados_de_jogo), portas)


# Texto que, se o quoting falhasse, executaria algo ou quebraria o `source`.
NOCIVOS = ["'; touch /tmp/pwned; '", "$(touch /tmp/pwned)", "`touch /tmp/pwned`", "a\nb\nc", "aspas ' e \" juntas",
           "\\[LOG\\] (?P<name>.+?) joined", "sem-nada", "${HOME}", "; rm -rf /", "espaco  duplo  "]


@pytest.mark.parametrize("texto", NOCIVOS)
def test_nenhum_valor_e_interpretado_como_shell(jogo, portas, texto, tmp_path):
    """Hooks do catalogo curado podem ter QUALQUER texto: o que chega ao CT e exatamente ele."""
    curado = replace(jogo, pre_install=texto, post_install=texto[::-1], origem="curado")
    valores = _valores(montar_env(curado, portas))
    assert valores["PRE_INSTALL_CMD"] == texto
    assert valores["POST_INSTALL_CMD"] == texto[::-1]
    assert not Path("/tmp/pwned").exists()


# --- fluxo -------------------------------------------------------------------------------------

def test_ordem_dos_comandos(instalador, jogo, portas):
    executor, _ = _instalar(instalador, jogo, portas)
    assert executor.comandos() == [
        "true",
        f"install -d -m 700 {DESTINO_REMOTO}",
        "scp",
        f"cd {DESTINO_REMOTO} && bash ct-install.sh install.env",
        executor.comandos()[-1],  # limpeza
    ]
    assert f"rm -rf {DESTINO_REMOTO}" in executor.comandos()[-1]


def test_scp_leva_a_lib_e_o_env_e_o_env_existe_na_hora(instalador, jogo, portas):
    executor, _ = _instalar(instalador, jogo, portas)
    scp = next(a for a, _ in executor.chamadas if a[0] == "scp")
    assert [Path(f).name for f in scp[-4:-1]] == ["ct-install.sh", "ct-fases.sh", "install.env"]
    assert scp[-1] == f"root@10.0.0.30:{DESTINO_REMOTO}/"
    assert "GAME_KEY=meujogo" in executor.env_visto
    assert not Path(scp[-2]).exists(), "o env temporario nao fica no disco do broker"


def test_todo_comando_e_lista_sem_shell_e_com_as_opcoes_de_seguranca(instalador, jogo, portas):
    executor, _ = _instalar(instalador, jogo, portas)
    for argv, _ in executor.chamadas:
        assert isinstance(argv, list)
        assert argv[0] in ("ssh", "scp")
        assert "BatchMode=yes" in argv, "nunca pergunta senha"
        assert "IdentitiesOnly=yes" in argv
    ssh = next(a for a, _ in executor.chamadas if a[0] == "ssh")
    assert "root@10.0.0.30" in ssh
    assert ssh[ssh.index("-i") + 1].endswith("id_broker")


def test_o_log_recebe_o_progresso_e_a_chave_removida(instalador, jogo, portas):
    _, linhas = _instalar(instalador, jogo, portas)
    texto = "\n".join(linhas)
    assert "aguardando o SSH de 10.0.0.30" in texto
    assert "INSTALACAO CONCLUIDA" in texto
    assert linhas[-1] == "chave do broker removida do container"


def test_limpeza_remove_a_chave_do_broker_e_confere(instalador, jogo, portas):
    executor, _ = _instalar(instalador, jogo, portas)
    limpeza = executor.comandos()[-1]
    assert f"grep -vF -- {BLOB}" in limpeza
    assert limpeza.rstrip().endswith(f"! grep -qF -- {BLOB} /root/.ssh/authorized_keys"), \
        "o proprio comando falha se a chave continuar la"


def test_timeouts_sao_repassados(instalador, jogo, portas, config):
    executor, _ = _instalar(instalador, jogo, portas)
    instalacao = next(t for a, t in executor.chamadas if a[-1].endswith("bash ct-install.sh install.env"))
    assert instalacao == config.timeout_instalacao


# --- falhas ------------------------------------------------------------------------------------------

def test_instalador_que_falha_traz_a_cauda_e_ainda_limpa_a_chave(instalador, jogo, portas):
    inst, executor = instalador
    executor.saidas["bash ct-install.sh"] = (1, ["baixando", "ERROR: SteamCMD nao conseguiu instalar o app"])
    with pytest.raises(ErroDeInstalacao, match=r"codigo 1.*SteamCMD nao conseguiu"):
        inst.instalar("10.0.0.30", jogo, portas, lambda _l: None)
    assert "rm -rf" in executor.comandos()[-1], "a chave do broker sai mesmo com a instalacao falha"


def test_exit_zero_sem_a_marca_de_conclusao_nao_vale(instalador, jogo, portas):
    inst, executor = instalador
    executor.saidas["bash ct-install.sh"] = (0, ["so isto"])
    with pytest.raises(ErroDeInstalacao, match="sem confirmar"):
        inst.instalar("10.0.0.30", jogo, portas, lambda _l: None)
    assert "rm -rf" in executor.comandos()[-1]


def test_falha_no_envio_tambem_limpa(instalador, jogo, portas):
    inst, executor = instalador
    executor.saidas["scp"] = (1, [])
    with pytest.raises(ErroDeInstalacao, match="enviar o instalador"):
        inst.instalar("10.0.0.30", jogo, portas, lambda _l: None)
    assert "rm -rf" in executor.comandos()[-1]


def test_chave_que_nao_sai_faz_a_criacao_falhar(instalador, jogo, portas):
    """Um CT novo nao pode nascer com acesso permanente do broker."""
    inst, executor = instalador
    executor.saidas["grep -vF"] = (1, [])
    with pytest.raises(ErroDeInstalacao, match="remover a chave do broker"):
        inst.instalar("10.0.0.30", jogo, portas, lambda _l: None)


def test_limpeza_que_falha_nao_esconde_o_erro_da_instalacao(instalador, jogo, portas):
    inst, executor = instalador
    executor.saidas["bash ct-install.sh"] = (1, ["deu ruim"])
    executor.saidas["grep -vF"] = (1, [])
    linhas: list[str] = []
    with pytest.raises(ErroDeInstalacao, match="a instalacao falhou"):
        inst.instalar("10.0.0.30", jogo, portas, linhas.append)
    assert any("AVISO" in linha and "remover a chave" in linha for linha in linhas)


def test_espera_o_ssh_subir(instalador, jogo, portas):
    inst, executor = instalador
    executor.falhas_no_ssh_inicial = 3
    _instalar((inst, executor), jogo, portas)
    assert executor.comandos().count("true") == 4


def test_ssh_que_nunca_sobe_e_erro_e_nao_tenta_limpar(config, jogo, portas):
    relogio = iter(range(0, 10_000, 100))
    executor = ExecutorFalso()
    executor.falhas_no_ssh_inicial = 10**6
    inst = InstaladorSsh(config, executor, dormir=lambda _s: None, agora=lambda: float(next(relogio)))
    with pytest.raises(ErroDeInstalacao, match="nao respondeu"):
        inst.instalar("10.0.0.30", jogo, portas, lambda _l: None)
    assert set(executor.comandos()) == {"true"}, "nunca entrou: nada a enviar nem a limpar"


@pytest.mark.parametrize("ip", ["10.0.0.300", "nao-e-ip", "10.0.0.30; rm -rf /", "", "::1"])
def test_ip_invalido_nao_gera_comando(instalador, jogo, portas, ip):
    inst, executor = instalador
    with pytest.raises(ValueError):
        inst.instalar(ip, jogo, portas, lambda _l: None)
    assert executor.chamadas == []


# --- saida em lote ----------------------------------------------------------------------------------------

def test_saida_volumosa_vira_poucas_gravacoes_e_linhas_longas_sao_cortadas(instalador, jogo, portas):
    inst, executor = instalador
    executor.saidas["bash ct-install.sh"] = (
        0, [f"progresso {i}%" for i in range(100)] + ["", "x" * 5000, "INSTALACAO CONCLUIDA: ok"])
    gravacoes: list[str] = []
    inst.instalar("10.0.0.30", jogo, portas, gravacoes.append)
    assert len(gravacoes) < 20, "100+ linhas nao sao 100+ transacoes no banco"
    assert max(len(g) for g in "\n".join(gravacoes).split("\n")) <= 400
    assert "progresso 99%" in "\n".join(gravacoes)


# --- configuracao --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("chave", ["", "ssh-ed25519", "ssh-ed25519 curta", "ssh-ed25519 " + "A" * 30 + "; rm -rf /"])
def test_chave_publica_invalida(tmp_path, pasta_lib, chave):
    with pytest.raises(ValueError, match="chave_publica"):
        ConfigSsh(chave_privada=tmp_path / "k", chave_publica=chave, pasta_lib=pasta_lib)


def test_usuario_invalido(tmp_path, pasta_lib):
    with pytest.raises(ValueError, match="usuario"):
        ConfigSsh(chave_privada=tmp_path / "k", chave_publica=CHAVE_PUBLICA, pasta_lib=pasta_lib, usuario="root; ls")


def test_lib_incompleta_e_recusada(tmp_path):
    (tmp_path / "ct-install.sh").write_text("x")
    cfg = ConfigSsh(chave_privada=tmp_path / "k", chave_publica=CHAVE_PUBLICA, pasta_lib=tmp_path)
    with pytest.raises(ValueError, match="ct-fases.sh"):
        InstaladorSsh(cfg, ExecutorFalso())


# --- executor real (com o proprio Python como "processo") ------------------------------------------------------

def test_executor_real_repassa_linhas_e_devolve_o_codigo():
    linhas: list[str] = []
    codigo = ExecutorReal().rodar(
        [sys.executable, "-c", "print('um'); print('dois'); import sys; sys.exit(3)"], linhas.append, 30)
    assert (codigo, linhas) == (3, ["um", "dois"])


def test_executor_real_mata_o_que_passa_do_prazo():
    codigo = ExecutorReal().rodar([sys.executable, "-c", "import time; time.sleep(60)"], None, 0.5)
    assert codigo != 0


def test_executor_real_binario_inexistente_e_erro_claro():
    with pytest.raises(ErroDeInstalacao, match="nao consegui executar"):
        ExecutorReal().rodar(["/nao/existe/ssh"], None, 5)


def test_executor_real_nao_le_do_teclado():
    """stdin fechado: um ssh que pedisse senha/confirmacao falharia em vez de travar o broker."""
    codigo = ExecutorReal().rodar([sys.executable, "-c", "import sys; sys.exit(0 if sys.stdin.read() == '' else 1)"], None, 30)
    assert codigo == 0
