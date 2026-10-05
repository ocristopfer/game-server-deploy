"""Every text a game adapter puts on the Config screen is a catalog key, in BOTH languages.

The labels, help texts and option labels used to be Portuguese sentences written inside
`games/adapters/*.py`: the English screen showed them in Portuguese and no test noticed,
because `test_i18n.py` only reads the CALLS of `_()`. Now a field carries KEYS
(`game.<adapter>.<field>.label`, `.help`, `.opt.<value>`) and the template translates them.

This is what makes "a new game = one adapter + one registry line + its keys in pt.py/en.py"
hold: forgetting the keys does not raise anything at runtime - the screen just shows
`game.valheim.slots.label` - so the test is the only thing that says so before a person does.
"""
from __future__ import annotations

import re

import pytest

from gamepanel import i18n
from gamepanel.games import config_format, registry
from gamepanel.games.base import FieldSpec

KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


def _texts(spec: FieldSpec) -> list[tuple[str, str]]:
    """(what, text) of every screen text of a field; empty help/unit are allowed."""
    found = [("label", spec.label)]
    if spec.help:
        found.append(("help", spec.help))
    if spec.unit:
        found.append(("unit", spec.unit))
    found += [(f"option {value}", label) for value, label in spec.options.items()]
    return found


def _every_text() -> list[tuple[str, str, str]]:
    return [(f"{adapter.__name__.rsplit('.', 1)[-1]}.{field}", what, text)
            for adapter in registry.ADAPTERS
            for field, spec in adapter.FIELDS.items()
            for what, text in _texts(spec)]


def test_a_varredura_enxerga_os_campos_de_todos_os_jogos():
    """Zero fields would make every assertion below pass without checking anything."""
    assert len(registry.ADAPTERS) >= 6
    assert len(_every_text()) > 200


@pytest.mark.parametrize("language", ["pt", "en"])
def test_todo_texto_de_campo_e_chave_dos_dois_catalogos(language: str):
    missing = sorted(f"{where} {what}: {text!r}" for where, what, text in _every_text()
                     if not KEY.match(text or "") or text not in i18n.CATALOGS[language])
    assert missing == [], (
        f"texto de campo que nao e chave do catalogo {language}; ponha a chave em "
        "i18n/pt.py e en.py (secao 'game config fields'):\n  " + "\n  ".join(missing))


def test_a_chave_do_campo_e_do_proprio_jogo():
    """`game.<adapter>.<field>` keeps two games from sharing a sentence by accident: the same
    "Vagas" in two games is two keys, and rewording one never changes the other. The labels
    shared on purpose (name and passwords) and the units live under `game.common`/`game.unit`.
    """
    wrong = []
    for adapter in registry.ADAPTERS:
        name = adapter.__name__.rsplit(".", 1)[-1]
        for field, spec in adapter.FIELDS.items():
            for what, text in _texts(spec):
                if text.startswith(("game.common.", "game.unit.")):
                    continue
                if not text.startswith(f"game.{name}.{field.lower()}."):
                    wrong.append(f"{name}.{field} {what}: {text}")
    assert wrong == [], "chave fora do prefixo do campo:\n  " + "\n  ".join(wrong)


def test_nenhuma_chave_de_jogo_sobrando_no_catalogo():
    """A key nobody references is a label someone will translate for nothing - or worse,
    edit thinking it is the one on screen, while the field points to another."""
    used = {text for _where, _what, text in _every_text()}
    left_over = sorted(k for k in i18n.CATALOGS["pt"]
                       if k.startswith("game.") and not k.startswith("game.validation.")
                       and k not in used)
    assert left_over == [], "chave de jogo que nenhum campo usa:\n  " + "\n  ".join(left_over)


def test_os_rotulos_de_bloco_e_de_formato_sao_chaves():
    for text in (config_format.NO_SECTION, config_format.ROOT, config_format.ConfigFile.label):
        assert text in i18n.CATALOGS["pt"]
        assert text in i18n.CATALOGS["en"]


def test_o_portugues_continua_o_mesmo_e_o_ingles_e_outro():
    """Spot check of the two sides of one field: the key changed, the Portuguese did not."""
    spec = registry.describe("PalWorldSettings.ini", "ExpRate")
    assert spec is not None
    assert i18n.translate(spec.label, "pt") == "Ganho de XP"
    assert i18n.translate(spec.label, "en") == "EXP rate"
    death = registry.describe("PalWorldSettings.ini", "DeathPenalty")
    assert death is not None
    assert i18n.translate(death.options["All"], "en") == "Everything (Pals included)"


def test_erro_de_validacao_sai_no_idioma_de_quem_le():
    """The validation message is a `Message`: `str` is the deploy language (Portuguese, as
    before), and `translate` rebuilds it - unit included - for the English screen."""
    spec = registry.describe("enshrouded_server.json", "nightTimeDuration")
    assert spec is not None
    problem = spec.validate("1")
    assert str(problem) == "mínimo 2 min"
    assert i18n.translate(problem, "en") == "minimum 2 min"
    assert i18n.translate(spec.validate("abc"), "en") == "must be a number"
    death = registry.describe("PalWorldSettings.ini", "DeathPenalty")
    assert death is not None
    assert i18n.translate(death.validate("Nope"), "en").startswith("invalid value; use one of: ")
