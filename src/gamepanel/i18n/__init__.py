"""Screen language: the panel speaks Portuguese by default and can speak another one.

The catalog is a Python dictionary, with no dependency and no build step. The standard
alternative (Flask-Babel + gettext) is in Debian's apt, but it requires compiling `.po` into
`.mo` - and this repo has no build: the production panel just receives files and starts. For
the same reason TOTP and the QR code are our own code here (see CLAUDE.md).

Each phrase has a neutral KEY (`nav.servers`, `action.start`) and one catalog per language.
That keeps the two languages symmetric - `pt.py` is not "the original" with `en.py` as "the
translation", both are data in the same way - and rewording the Portuguese does not force a
change in the English catalog.

Lookup cascades: requested language -> Portuguese -> the key itself. The last step is on
purpose: a key nobody registered shows up on screen as `nav.servers`, and that is noisy enough
to get fixed - better than vanishing silently.

What gets translated is what the PERSON reads. Technical logs, exception names and code
identifiers are English and stay out of here.

A phrase with a NUMBER or NAME in the middle is not split into pieces: `translate` accepts
fields and substitutes them for `{name}` inside the phrase. Splitting was the obvious path and
it is wrong, because word order changes from one language to another - "a cada {n}s" and
"every {n}s" still line up, but that is not always the case, and a loose fragment gives the
translator no context.

For the same reason a phrase may carry MARKUP (`<strong>`, `<code>`): splitting the paragraph
at each `<strong>` would leave half of it in Portuguese on the English screen. The catalog is
code from this repository, not user input, so the phrase is trusted; the FIELDS that go into
it are not, and `translate_html` in `app.py` escapes them.
"""
from __future__ import annotations

from gamepanel.i18n import en, pt

DEFAULT = "pt"

CATALOGS: dict[str, dict[str, str]] = {
    "pt": pt.MESSAGES,
    "en": en.MESSAGES,
}

# What the screen offers, in the order it appears in the selector.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("pt", "Portugues (Brasil)"),
    ("en", "English"),
)

# What goes into `<html>`'s `lang=`, which is NOT the same thing as the catalog key: the
# attribute accepts a region and ours is Brazil's (`pt-BR`), while the key is just `pt`.
# This attribute is read by the screen reader (which picks voice and pronunciation from it)
# and by the browser's automatic translation -- with it hardcoded to `pt-BR`, as it was in
# base.html, the English screen was ANNOUNCED as Portuguese and the screen reader read English
# with Portuguese phonemes. No route test shows it: the page still answers 200.
HTML_LANGS: dict[str, str] = {
    "pt": "pt-BR",
    "en": "en",
}


def html_lang(language: str) -> str:
    """The `<html>` `lang=` for a catalog language."""
    return HTML_LANGS.get(language, HTML_LANGS[DEFAULT])


def valid_language(raw: str | None) -> str:
    """Returns a language that exists; anything else becomes the default."""
    chosen = (raw or "").strip()
    return chosen if chosen in CATALOGS else DEFAULT


class Message(str):
    """A phrase that remembers WHICH KEY it came from.

    It exists for text born far from the screen: the validation error from
    `services/server_service.py`, the `QueryError` from `runtime/a2s.py`. That text ends up in
    three places with different rules - the screen of whoever clicked (that person's language),
    a job's output column (stored, deploy language) and the process log - and a service has no
    way of knowing which one it will land in.

    It is a `str` on purpose, not a separate object. That way `str(exc)`, `f"{erro}"`,
    `"pedaco" in erro` and `logging` keep working exactly as before, without touching any of
    those spots; what changes is that `translate` recognizes the class and rebuilds the phrase
    in the right language when someone asks. Forgetting to translate breaks nothing: it falls
    back to the deploy language, which was the previous behavior.
    """

    key: str
    fields: dict[str, object]

    def __new__(cls, key: str, **fields: object) -> Message:
        obj = super().__new__(cls, translate(key, DEFAULT, **fields))
        obj.key = key
        obj.fields = fields
        return obj

    def __repr__(self) -> str:
        return f"Mensagem({self.key!r}, {self.fields!r})"


def translate(key: str, language: str, **fields: object) -> str:
    """The phrase for that key, falling back to Portuguese and then to the key.

    A field the phrase does not use is ignored, and a `{placeholder}` with no matching field stays
    on screen as is. Phrase and field come from different places (catalog vs route), and taking
    down the whole screen over a `{n}` someone forgot to pass costs far more than the damage:
    the truncated phrase already gives the defect away.
    """
    # A `Message` already carries its original key and fields; translating it again just
    # rebuilds the phrase in the requested language. Without this, its text (already a str)
    # would be treated as an unknown key and come back as is, in the deploy language.
    if isinstance(key, Message):
        return translate(key.key, language, **{**key.fields, **fields})
    # `get(key, default)` and not `get(key) or default`: a phrase translated as EMPTY text
    # is a choice (a label that only exists in Portuguese, for example) and must win over the
    # Portuguese, instead of falling back to it for looking absent.
    wanted = CATALOGS.get(language) or {}
    phrase = wanted.get(key, CATALOGS[DEFAULT].get(key, key))
    if not fields:
        return phrase
    # A field that is ALSO a `Message` goes into the same language as the phrase receiving it.
    # Without this it would go in through `str`, which is always the deploy language, and the
    # phrase would come out half translated: "todo sabado at 03:00" is exactly what showed up.
    ready = {
        name: translate(value, language) if isinstance(value, Message) else value
        for name, value in fields.items()
    }
    try:
        return phrase.format(**ready)
    except (KeyError, IndexError, ValueError):
        return phrase


def from_header(accept_language: str | None) -> str:
    """Reads the browser's Accept-Language. Only for someone who has not chosen anything yet.

    A short implementation on purpose: what matters is whether the browser prefers a language
    the panel SPEAKS, not ranking the whole weighted list. `pt-BR` counts as Portuguese;
    `en-US` counts as English.
    """
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        base = tag.split("-")[0]
        if base in CATALOGS:
            return base
    return DEFAULT


def missing_keys(language: str) -> list[str]:
    """Keys that Portuguese has and this language does not. Used by the test."""
    return sorted(set(CATALOGS[DEFAULT]) - set(CATALOGS.get(language, {})))
