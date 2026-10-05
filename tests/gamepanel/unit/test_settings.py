"""Reading the `GAMEPANEL_*` variables: defaults, conversion and what gets refused.

Before there was a single place, an invalid value brought the panel down with
`ValueError: invalid literal for int() with base 10: 'abc'` - without saying WHICH of the
~45 variables it was. Whoever was reading the journal had to guess.
"""
from __future__ import annotations

import pytest

from gamepanel import config


def test_ambiente_vazio_da_os_padroes():
    """The panel starts with no variable set at all: the case of a bare `docker run`."""
    settings = config.load({})
    assert settings.db_path == "/var/lib/gamepanel/panel.db"
    assert settings.job_timeout == 5400
    assert settings.allow_shell is True
    assert settings.allow_broker is False


def test_o_ssh_control_dir_acompanha_o_known_hosts():
    """Both are SSH state and live on the same volume: a deploy that moves one moves the
    other along, without having to remember two variables."""
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
    """Stopping at the first one makes whoever configures it discover one error per deploy."""
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
    """`MONITOR_EVERY=0` made the monitor spin nonstop, and nothing warned about it."""
    with pytest.raises(config.ConfigError, match="minimo 1"):
        config.load({"GAMEPANEL_MONITOR_EVERY": "0"})


def test_a_mensagem_nunca_carrega_o_VALOR():
    """Config errors go to the journal, and there are secrets among these variables."""
    with pytest.raises(config.ConfigError) as erro:
        config.load({"GAMEPANEL_WEBHOOK_TIMEOUT": "senha-secreta-no-lugar-errado"})
    assert "senha-secreta" not in str(erro.value)


def test_vazio_vale_como_ausente():
    """A `.env` with `GAMEPANEL_JOB_TIMEOUT=` must not bring the panel down: an empty value
    is the normal way to comment an option out."""
    assert config.load({"GAMEPANEL_JOB_TIMEOUT": ""}).job_timeout == 5400


def test_a_lista_de_raizes_ignora_espaco_e_vazio():
    settings = config.load({"GAMEPANEL_FILE_ROOTS": "/opt/game, /srv ,,"})
    assert settings.file_roots == ("/opt/game", "/srv")


def test_o_app_le_a_configuracao_uma_vez_so():
    """`app.settings` exists and is the same object all the time - reading the environment on
    every use would make half the panel see one value and half another."""
    from gamepanel import app as panel

    assert isinstance(panel.settings, config.Settings)
    assert panel.settings.job_timeout == panel.JOB_TIMEOUT


def test_nenhum_modulo_le_o_ambiente_por_fora():
    """Every `GAMEPANEL_*` goes through `config.py`. A stray read escapes the range check and
    disappears from the place where someone would look for the list of options."""
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
