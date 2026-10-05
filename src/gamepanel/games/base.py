"""What a game configuration field IS: type, limit, unit and label.

There is no game here at all. `config_format.py` knows how to READ and WRITE the files (ini,
json, serverDZ.cfg) without knowing any game - and that is on purpose: a new file stays
editable without touching the code. What is missing there is SEMANTICS: that one field is a
boolean, that another is a percentage, that `dayTimeDuration` is in nanoseconds and has a
2-minute minimum.

This layer adds only that, and each game fills it in under its `adapters/`:

* nothing is mandatory - a field without a description still shows up as free text;
* the catalog never hides a field: if the game gains a new key in an update, it shows up
  on the screen even without being mapped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# One second in nanoseconds. Enshrouded stores durations in this unit, and it is the source
# of the most common mistake in its file: whoever types "120" thinking it is seconds writes
# 120 nanoseconds, and the game silently uses the minimum.
NS = 1_000_000_000

# Labels that show up in several games under different technical names (`ServerName`,
# `SessionName`, `hostname`, `name`). The FIELD name changes from game to game; what the
# person looks for on the screen does not - and that is exactly why it must come out the
# same in all four. Written by hand, one of them would turn into "Nome de servidor" in some
# update and searching by name would stop finding that field in that game.
LABEL_NAME = "Nome do servidor"
# A field label on the screen, not a secret - the analyzer is fooled by the constant name.
LABEL_JOIN_PASSWORD = "Senha de entrada"  # noqa: S105  # NOSONAR
LABEL_ADMIN_PASSWORD = "Senha de admin"  # noqa: S105  # NOSONAR


@dataclass
class FieldSpec:
    """How a field should appear on the screen and what is valid in it."""

    label: str = ""
    help: str = ""
    kind: str = "text"          # text | bool | number | factor | duration | enum | password
    options: dict[str, str] = field(default_factory=dict)   # stored value -> label on screen
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""              # suffix shown next to the field
    # For kind="duration": the file stores nanoseconds, the screen shows minutes.
    scale: int = 1

    def to_display(self, raw: str) -> str:
        """File value -> value shown on the screen."""
        text = (raw or "").strip()
        if self.kind != "duration" or not text:
            return text
        try:
            minutes = float(text) / self.scale
        except ValueError:
            return text
        return f"{minutes:g}"

    def from_display(self, text: str) -> str:
        """Value typed on the screen -> value stored in the file."""
        text = (text or "").strip()
        if self.kind != "duration" or not text:
            return text
        return str(round(float(text) * self.scale))

    def validate(self, text: str) -> str:
        """Return an error message, or an empty string when the value is fine.

        The check is done in the SCREEN unit (minutes, multiplier), which is where the
        person makes mistakes - reporting a limit in nanoseconds would help nobody.

        An empty field is never an error: the game has a default for a missing key, and
        clearing the value is a legitimate way to go back to it.
        """
        text = (text or "").strip()
        if not text:
            return ""
        if self.kind == "enum" and self.options:
            return self._validate_enum(text)
        if self.kind in ("number", "factor", "duration"):
            return self._validate_number(text)
        return ""

    def _validate_enum(self, text: str) -> str:
        if text in self.options:
            return ""
        return f"valor invalido; use um de: {', '.join(sorted(self.options))}"

    def _validate_number(self, text: str) -> str:
        try:
            value = float(text)
        except ValueError:
            return "precisa ser um número"
        if self.minimum is not None and value < self.minimum:
            return f"minimo {self._with_unit(self.minimum)}"
        if self.maximum is not None and value > self.maximum:
            return f"maximo {self._with_unit(self.maximum)}"
        return ""

    def _with_unit(self, value: float) -> str:
        """"2 min", "0.25 x", or just "16" when the field has no unit."""
        return f"{value:g}{self.unit and ' ' + self.unit}"


def factor(label: str, help_text: str, minimum: float = 0.25, maximum: float = 4.0) -> FieldSpec:
    """Multiplier: 1 = game default, 0.5 = half, 2 = double."""
    return FieldSpec(label=label, help=help_text, kind="factor", minimum=minimum,
                     maximum=maximum, step=0.05, unit="x")


def duration(label: str, help_text: str, min_minutes: float, max_minutes: float) -> FieldSpec:
    """Duration stored in nanoseconds, edited in minutes."""
    return FieldSpec(label=label, help=help_text, kind="duration", scale=60 * NS,
                     minimum=min_minutes, maximum=max_minutes, step=1, unit="min")


def enum_of(label: str, help_text: str, options: dict[str, str]) -> FieldSpec:
    return FieldSpec(label=label, help=help_text, kind="enum", options=options)


def flag(label: str, help_text: str) -> FieldSpec:
    return FieldSpec(label=label, help=help_text, kind="bool")
