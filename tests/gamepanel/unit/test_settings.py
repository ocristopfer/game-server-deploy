"""A leitura das `GAMEPANEL_*`: defaults, conversao e o que ela recusa.

Antes de existir um lugar so, um valor invalido derrubava o painel com
`ValueError: invalid literal for int() with base 10: 'abc'` — sem citar QUAL das ~45
variaveis era. Quem estava lendo o journal precisava adivinhar.
"""
from __future__ import annotations

import pytest

from gamepanel import config


def test_ambiente_vazio_da_os_padroes():
    """O painel sobe sem nenhuma variavel definida: e o caso do `docker run` cru."""
    settings = config.load({})
    assert settings.db_path == "/var/lib/gamepanel/panel.db"
    assert settings.job_timeout == 5400
    assert settings.allow_shell is True
    assert settings.allow_broker is False


def test_o_ssh_control_dir_acompanha_o_known_hosts():
    """Os dois sao estado do SSH e vivem no mesmo volume: um deploy que move um move o
    outro junto, sem precisar lembrar de duas variaveis."""
    settings = config.load({"GAMEPANEL_KNOWN_HOSTS": "/dados/known_hosts"})
    assert settings.ssh_control_dir.replace("\\", "/") == "/dados/ssh-control"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_ligado_aceita_as_formas_usuais(value):
    assert config.load({"GAMEPANEL_REQUIRE_2FA": value}).require_2fa is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_desligado_aceita_as_formas_usuais(value):
    assert config.load({"GAMEPANEL_ALLOW_SHELL": value}).allow_shell is False


def test_valor_invalido_diz_qual_variavel_e():
    with pytest.raises(config.ConfigError) as erro:
        config.load({"GAMEPANEL_JOB_TIMEOUT": "abc"})
    assert "GAMEPANEL_JOB_TIMEOUT" in str(erro.value)


def test_todos_os_problemas_saem_de_uma_vez():
    """Parar no primeiro faz quem configura descobrir um erro por deploy."""
    with pytest.raises(config.ConfigError) as erro:
        config.load({
            "GAMEPANEL_JOB_TIMEOUT": "abc",
            "GAMEPANEL_ALLOW_SHELL": "talvez",
            "GAMEPANEL_MONITOR_EVERY": "0",
        })
    message = str(erro.value)
    for name in ("GAMEPANEL_JOB_TIMEOUT", "GAMEPANEL_ALLOW_SHELL", "GAMEPANEL_MONITOR_EVERY"):
        assert name in message


def test_intervalo_zero_e_recusado():
    """`MONITOR_EVERY=0` fazia o monitor girar sem parar, e nada avisava."""
    with pytest.raises(config.ConfigError, match="minimo 1"):
        config.load({"GAMEPANEL_MONITOR_EVERY": "0"})


def test_a_mensagem_nunca_carrega_o_VALOR():
    """Erro de config vai para o journal, e ha segredo entre estas variaveis."""
    with pytest.raises(config.ConfigError) as erro:
        config.load({"GAMEPANEL_WEBHOOK_TIMEOUT": "senha-secreta-no-lugar-errado"})
    assert "senha-secreta" not in str(erro.value)


def test_vazio_vale_como_ausente():
    """Um `.env` com `GAMEPANEL_JOB_TIMEOUT=` nao pode derrubar o painel: linha em branco
    e o jeito normal de comentar uma opcao."""
    assert config.load({"GAMEPANEL_JOB_TIMEOUT": ""}).job_timeout == 5400


def test_a_lista_de_raizes_ignora_espaco_e_vazio():
    settings = config.load({"GAMEPANEL_FILE_ROOTS": "/opt/game, /srv ,,"})
    assert settings.file_roots == ("/opt/game", "/srv")


def test_o_app_le_a_configuracao_uma_vez_so():
    """`app.settings` existe e e o mesmo objeto o tempo todo — ler o ambiente a cada uso
    faria metade do painel enxergar um valor e metade outro."""
    from gamepanel import app as panel

    assert isinstance(panel.settings, config.Settings)
    assert panel.settings.job_timeout == panel.JOB_TIMEOUT


def test_nenhum_modulo_le_o_ambiente_por_fora():
    """Toda `GAMEPANEL_*` passa pelo `config.py`. Uma leitura solta escapa da conferencia
    de faixa e some do lugar onde alguem procuraria a lista de opcoes."""
    from pathlib import Path

    from gamepanel import app as panel

    raiz = Path(panel.__file__).parent
    fora = []
    for path in sorted(raiz.rglob("*.py")):
        if path.name == "config.py" or "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            if "GAMEPANEL_" in line and "environ" in line:
                fora.append(f"{path.relative_to(raiz).as_posix()}:{number}")
    assert fora == [], "GAMEPANEL_* lida fora do config.py:\n  " + "\n  ".join(fora)
