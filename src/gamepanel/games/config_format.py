#!/usr/bin/env python3
"""Reads and writes game configuration files field by field.

The "Files" screen handles everything, but it requires finding the file, finding the line and
not getting a comma wrong. Here the file becomes a list of settings (section, key, value) that
the "Config" screen shows as a form - and saving touches ONLY the keys the user changed,
preserving comments, order and everything else in the file.

Formats (detected by name + content):
  ini   - common .ini/.conf/.properties. Values in the Unreal format
          (OptionSettings=(Key=Value,...), from Palworld) become sub-settings.
  json  - Enshrouded (enshrouded_server.json)
  dayz  - serverDZ.cfg: 'key = value;' and 'class X { ... };' blocks
  sii   - ETS2/ATS server_config.sii: 'SiiNunit { class : name { key: value } }'

This module speaks neither SSH nor HTTP: it takes text and returns text. That is what allows
testing it on its own (test_config_format.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from gamepanel.i18n import Message

# Separates the levels of a setting's identifier ("section\x1fkey"). It does not appear in
# any config file, so it works as a separator without escaping.
SEP = "\x1f"

# Label of the unnamed block: a loose key at the top of an .ini, or the top level of a
# .json. It becomes a section title on the Configuration screen, and the three formats must
# say the SAME thing - not "(sem secao)" in one and "(raiz)" in another for the same idea.
# Both are i18n KEYS, like the field labels of `base.FieldSpec`: the template passes every
# section label through `_()`, and a real section name ("[ServerSettings]") is not a catalog
# key, so it comes back unchanged.
NO_SECTION = "config.no_section"
ROOT = "config.root"

# UTF-8 byte order mark, already decoded: that is how it arrives here (the text comes in already read).
BOM = "﻿"

VALUE_MAX = 4000
# Key name accepted in a game configuration file.
#
# The `re.ASCII` is not a detail: without it, `\w` in Python matches accented letters,
# Arabic-Indic digits and some 900 more Unicode characters - and this name ends up inside
# the game file, written over SSH. With the flag, `\w` is exactly `[A-Za-z0-9_]`, which
# was the old form of this expression.
KEY_RE = re.compile(r"^\w[\w.\- ]{0,79}$", re.ASCII)
BOOL_WORDS = {"true": True, "false": False, "1": True, "0": False,
              "sim": True, "nao": False, "yes": True, "no": False}
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


class ConfigError(ValueError):
    """Shape error: a file that cannot be interpreted, an invalid key/value."""


@dataclass
class Setting:
    """One line of the form: one game configuration key."""

    id: str                 # stable identifier, used to find the key again
    section: str            # block where it lives (opaque id)
    key: str
    value: str
    kind: str = "text"      # text | bool | number
    comment: str = ""       # neighboring comment in the file, becomes help on the screen
    # Filled in after reading, by the field catalog (`games/registry.py`). They live here
    # and not in the parser on purpose: the parser still does not know which game this is.
    spec: object = None     # games.base.FieldSpec, when the field is known
    display_value: str = ""  # value in the screen unit (minutes instead of nanoseconds)


@dataclass
class Section:
    """Block of settings ([section] of the ini, DayZ class, JSON object)."""

    id: str
    label: str
    settings: list[Setting] = field(default_factory=list)


@dataclass
class Edit:
    """A change coming from the form.

    An empty `id` (or one that no longer exists in the file) means a new setting: it is
    looked up by section+key and, if it does not exist, appended at the end of the block.
    """

    section: str
    key: str
    value: str
    id: str = ""


def check_key(key: str) -> str:
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise ConfigError(Message("config.error.invalid_name", name=repr(key)))
    return key


def check_value(value: str) -> str:
    value = (value or "").replace("\r", "")
    if "\n" in value or "\x00" in value:
        raise ConfigError(Message("config.error.value_newline"))
    if len(value) > VALUE_MAX:
        raise ConfigError(Message("config.error.value_too_long", n=VALUE_MAX))
    return value.strip()


def _kind_of(value: str) -> str:
    if value.strip().lower() in ("true", "false"):
        return "bool"
    if NUM_RE.match(value.strip()):
        return "number"
    return "text"


def _as_bool(value: str) -> bool:
    got = BOOL_WORDS.get(value.strip().lower())
    if got is None:
        raise ConfigError(Message("config.error.invalid_bool", value=repr(value)))
    return got


# --------------------------------------------------------------------- base


class ConfigFile:
    """Common contract: parse in the constructor, `apply` returns the new file."""

    format_id = "texto"
    label = "config.format_text"  # i18n key; the other formats' names need no translation
    # How the format writes true/false. The screen uses this in the selector of boolean
    # fields: with the right spelling, opening and saving without touching anything "changes" nothing.
    bool_words = ("True", "False")

    def __init__(self, text: str) -> None:
        # The BOM (U+FEFF at the start) is removed before any reader sees the text and comes back
        # in `apply`. The V Rising defaults ship with it, and `json.loads` rejects it ("Unexpected
        # UTF-8 BOM"): the Config screen would not open ServerHostSettings.json. Putting it back on
        # save makes the file come out the same as the game wrote it, without changing the
        # encoding of someone else's file.
        self.bom = text.startswith(BOM)
        self.text = text[len(BOM):] if self.bom else text
        self.settings: list[Setting] = []
        self._sections: dict[str, Section] = {}
        self.parse()

    # -- reading -------------------------------------------------------
    def parse(self) -> None:  # pragma: no cover - implemented in subclasses
        raise NotImplementedError

    def _section(self, sid: str, label: str) -> Section:
        sec = self._sections.get(sid)
        if sec is None:
            sec = Section(id=sid, label=label)
            self._sections[sid] = sec
        return sec

    def _add(self, setting: Setting, label: str = "") -> None:
        self._section(setting.section, label or setting.section or NO_SECTION)
        self._sections[setting.section].settings.append(setting)
        self.settings.append(setting)

    @property
    def sections(self) -> list[Section]:
        """Blocks with content. A file without any key returns whatever there is."""
        non_empty = [s for s in self._sections.values() if s.settings]
        return non_empty or list(self._sections.values())

    def get(self, sid: str) -> Setting | None:
        for s in self.settings:
            if s.id == sid:
                return s
        return None

    def find(self, section: str, key: str) -> Setting | None:
        target = key.strip().lower()
        for s in self.settings:
            if s.section == section and s.key.strip().lower() == target:
                return s
        return None

    # -- writing -------------------------------------------------------
    def apply(self, edits: list[Edit]) -> str:
        """The new file, with the BOM back if the original had it."""
        out = self._apply(edits)
        return BOM + out if self.bom else out

    def _apply(self, edits: list[Edit]) -> str:  # pragma: no cover - subclasses
        raise NotImplementedError

    def _resolve(self, edit: Edit) -> Setting | None:
        """Find the setting the form wants to change (by id, then by name)."""
        if edit.id:
            found = self.get(edit.id)
            if found is not None:
                return found
        return self.find(edit.section, edit.key)


def _insert_after(lines: list[str], index: int, new_lines: list[str]) -> None:
    lines[index + 1:index + 1] = new_lines


# ---------------------------------------------------------------------- ini


_SECTION_RE = re.compile(r"^\s*\[([^\]]*)\]\s*$")
_COMMENT_RE = re.compile(r"^\s*[#;]")
# Split only at the first '='; the surrounding whitespace is separated in code. "Optional"
# groups competing for the same text (\s* next to [^=]*?) make the regex engine backtrack
# many times on a long line - and the Palworld line has a few thousand bytes.
_PAIR_RE = re.compile(r"^(\s*)([^=\s\[#;][^=]*)=(.*)$")


def _nesting_depth(ch: str, depth: int) -> int:
    """How much this character changes the parenthesis/bracket nesting."""
    if ch in "([":
        return depth + 1
    if ch in ")]":
        return depth - 1
    return depth


def _split_tuple(inner: str) -> list[str] | None:
    """Split 'A=1,B="x,y",C=(D=2)' into its top-level pairs.

    Return None if the text does not look like a list of pairs (then the value stays as text).
    """
    parts: list[str] = []
    buf = ""
    depth = 0
    in_quotes = False
    for ch in inner:
        if in_quotes:
            buf += ch
            in_quotes = ch != '"'
            continue
        if ch == '"':
            in_quotes = True
            buf += ch
            continue
        depth = _nesting_depth(ch, depth)
        if depth < 0:
            return None  # closed a parenthesis that was never opened: not a list of pairs
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
            continue
        buf += ch
    if in_quotes or depth != 0:
        return None
    if buf.strip():
        parts.append(buf)
    return parts


def _tuple_pairs(value: str) -> list[str] | None:
    """The pairs of a value in the Unreal format, or None if it is not one.

    `OptionSettings=(Difficulty=None,ExpRate=1.0)` - where Palworld keeps ALL of its
    configuration - is not a value: it is a whole configuration inside one line. The
    `=` in the middle is what sets it apart from a regular value in parentheses.
    """
    inner = value.strip()
    if not (inner.startswith("(") and inner.endswith(")") and "=" in inner):
        return None
    return _split_tuple(inner[1:-1])


_MIN_QUOTED_LENGTH = 2  # opening and closing quotes: '""' is the shortest possible quoted value


def _unquote(value: str) -> tuple[str, bool]:
    value = value.strip()
    if len(value) >= _MIN_QUOTED_LENGTH and value[0] == '"' and value[-1] == '"':
        return value[1:-1], True
    return value, False


def _requote(value: str, was_quoted: bool) -> str:
    """Return the value in the file format: quoted if it already was, or if it needs to be."""
    if '"' in value:
        raise ConfigError(Message("config.error.value_double_quote"))
    needs_quotes = any(ch in value for ch in ',()= ') or value == ""
    if was_quoted or needs_quotes:
        return f'"{value}"'
    return value


@dataclass
class _Pair:
    """A pair inside a value in the Unreal format: Key=Value."""

    key: str
    value: str
    quoted: bool


@dataclass
class _TupleLine:
    """A 'Key=(A=1,B=2)' line of an Unreal .ini (Palworld)."""

    line: int
    prefix: str
    name: str
    sep: str
    pairs: list[_Pair]
    suffix: str = ""

    def render(self) -> str:
        joined = ",".join(f"{p.key}={_requote(p.value, p.quoted)}" for p in self.pairs)
        return f"{self.prefix}{self.name}{self.sep}({joined}){self.suffix}"


class IniConfig(ConfigFile):
    """.ini/.conf/.properties, with or without [sections].

    Values in the Unreal format - `OptionSettings=(Difficulty=None,ExpRate=1.0,...)`,
    which is where Palworld keeps ALL of its configuration - are opened into sub-settings,
    each pair becoming a form field.
    """

    format_id = "ini"
    label = "INI"

    def parse(self) -> None:
        self._lines = self.text.split("\n")
        self._plain: dict[str, tuple[int, str, str, str]] = {}  # id -> (line, prefix, name, sep)
        self._tuples: dict[str, _TupleLine] = {}                # section id -> line
        self._pairs: dict[str, int] = {}                        # id -> position inside the tuple
        self._section_end: dict[str, int] = {}                  # id -> last useful line
        section = ""
        self._section(section, NO_SECTION)
        comment_lines: list[str] = []
        seen: dict[str, int] = {}

        for i, line in enumerate(self._lines):
            section_match = _SECTION_RE.match(line)
            if section_match:
                section = section_match.group(1).strip()
                self._section(section, f"[{section}]")
                self._section_end[section] = i
                comment_lines = []
                continue
            if not line.strip():
                comment_lines = []
                continue
            if _COMMENT_RE.match(line):
                comment_lines.append(line.strip().lstrip("#;").strip())
                continue

            pair_match = _PAIR_RE.match(line)
            if pair_match:
                self._read_pair(i, pair_match, section, comment_lines, seen)
            # A comment only applies to the next line: anything else discards it.
            comment_lines = []

    def _read_pair(self, i: int, pair_match: re.Match[str], section: str,
                    comment_lines: list[str], seen: dict[str, int]) -> None:
        """A `key = value` line of the .ini becomes a field (or several, if it is a tuple)."""
        prefix, raw_key, rest = pair_match.groups()
        name = raw_key.rstrip()
        value = rest.strip()
        # sep and suffix keep the original spacing: writing back must not reformat
        # a line the user did not even touch.
        sep = raw_key[len(name):] + "=" + rest[:len(rest) - len(rest.lstrip())]
        suffix = rest[len(rest.rstrip()):]
        self._section_end[section] = i

        # Ids repeat when the same key shows up twice in the section (common in
        # Unreal): the suffix gives each occurrence its own identity.
        base = f"{section}{SEP}{name}"
        seen[base] = seen.get(base, 0) + 1
        sid = base if seen[base] == 1 else f"{base}{SEP}#{seen[base]}"

        pairs = _tuple_pairs(value)
        if pairs is not None:
            self._parse_tuple(sid, section, name, i, prefix, sep, suffix, pairs)
            return

        self._plain[sid] = (i, prefix, name, sep)
        self._add(Setting(
            id=sid, section=section, key=name, value=value,
            kind=_kind_of(value), comment=" ".join(comment_lines),
        ), label=f"[{section}]" if section else NO_SECTION)

    def _parse_tuple(self, sid: str, section: str, name: str, line: int, prefix: str,
                      sep: str, suffix: str, pairs: list[str]) -> None:
        target = sid  # the section of the sub-settings is the line's own id
        self._section(target, f"[{section}] {name}" if section else name)
        items: list[_Pair] = []
        seen: dict[str, int] = {}
        for raw_pair in pairs:
            key, has_equals, value = raw_pair.partition("=")
            if not has_equals:
                continue
            key = key.strip()
            text, quoted = _unquote(value)
            seen[key] = seen.get(key, 0) + 1
            suffix_id = "" if seen[key] == 1 else f"{SEP}#{seen[key]}"
            pid = f"{target}{SEP}{key}{suffix_id}"
            self._pairs[pid] = len(items)
            items.append(_Pair(key=key, value=text, quoted=quoted))
            self._add(Setting(
                id=pid, section=target, key=key, value=text, kind=_kind_of(text),
            ))
        self._tuples[target] = _TupleLine(
            line=line, prefix=prefix, name=name, sep=sep, pairs=items, suffix=suffix,
        )
        if not items:
            self._section(target, f"[{section}] {name}" if section else name)

    # -- writing -------------------------------------------------------
    def _apply(self, edits: list[Edit]) -> str:
        lines = list(self._lines)
        new_by_section: dict[str, list[str]] = {}
        changed_tuples: set[str] = set()

        for edit in edits:
            self._apply_edit(edit, lines, new_by_section, changed_tuples)

        for sid in changed_tuples:
            group = self._tuples[sid]
            lines[group.line] = group.render()

        self._insert_new_settings(lines, new_by_section)
        return "\n".join(lines)

    def _apply_edit(self, edit: Edit, lines: list[str],
                     new_by_section: dict[str, list[str]],
                     changed_tuples: set[str]) -> None:
        """Write ONE change. There are four possible destinations, in this order:

        the existing line, a pair inside an Unreal tuple, a new key inside that tuple,
        or a new key at the end of the section (this last one stays pending: inserting a
        line here would shift everything that comes after).
        """
        value = check_value(edit.value)
        current = self._resolve(edit)

        if current is not None and current.id in self._plain:
            i, prefix, name, sep = self._plain[current.id]
            lines[i] = f"{prefix}{name}{sep}{value}"
            return

        if current is not None and current.id in self._pairs:
            group = self._tuples[current.section]
            group.pairs[self._pairs[current.id]].value = value
            changed_tuples.add(current.section)
            return

        key = check_key(edit.key)
        if edit.section in self._tuples:  # new setting inside OptionSettings
            group = self._tuples[edit.section]
            group.pairs.append(_Pair(key=key, value=value, quoted=False))
            changed_tuples.add(edit.section)
            return

        new_by_section.setdefault(edit.section, []).append(f"{key}={value}")

    def _insert_new_settings(self, lines: list[str], new_by_section: dict[str, list[str]]) -> None:
        """Append the new keys at the end of each section.

        Back to front: inserting at the end of one section must not shift the lines of
        the sections still to be inserted.
        """
        pending = sorted(
            new_by_section.items(),
            key=lambda item: self._section_end.get(item[0], len(lines)),
            reverse=True,
        )
        for section, new_lines in pending:
            end = self._section_end.get(section)
            if end is None:
                # A section that did not exist in the file: created at the end, with a header.
                if section:
                    lines.append(f"[{section}]")
                lines.extend(new_lines)
                continue
            _insert_after(lines, end, new_lines)


# --------------------------------------------------------------------- json


def _json_text(value: Any) -> str:
    """A JSON value as the screen shows it.

    `null` becomes an empty field, and a boolean becomes the JSON spelling ("true"/"false"),
    not Python's ("True"): what comes out of here goes back to the file, and `True` would break the JSON.
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _json_kind(value: Any) -> str:
    """Which field the form draws for this value: checkbox, number or text.

    `bool` before `(int, float)` on purpose: in Python `True` is an `int`, and in the
    opposite order every checkbox would become a number field.
    """
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


class JsonConfig(ConfigFile):
    """JSON config (Enshrouded). Nested objects become sections.

    The JSON is rewritten whole by `json.dumps` - the file comes out indented with 2
    spaces, which is how Keen Games publishes the example. JSON has no comments, so
    there is nothing to preserve besides the values.
    """

    format_id = "json"
    label = "JSON"
    bool_words = ("true", "false")

    data: dict[str, Any] | list[Any]

    def parse(self) -> None:
        try:
            self.data = json.loads(self.text or "{}")
        except ValueError as exc:
            raise ConfigError(Message("config.error.invalid_json", reason=str(exc))) from exc
        if not isinstance(self.data, (dict, list)):
            raise ConfigError(Message("config.error.json_not_container"))
        self._section("", ROOT)
        self._walk(self.data, "")

    def _walk(self, node: dict[str, Any] | list[Any], path: str) -> None:
        items = node.items() if isinstance(node, dict) else enumerate(node)
        for key, value in items:
            key = str(key)
            child = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                self._section(child, child)
                self._walk(value, child)
                continue
            self._add(Setting(
                id=child, section=path, key=key,
                value=_json_text(value), kind=_json_kind(value),
            ), label=path or ROOT)

    def _parent(self, path: str) -> Any:
        node: Any = self.data
        if not path:
            return node
        for part in path.split("."):
            if isinstance(node, list):
                if not part.isdigit() or int(part) >= len(node):
                    raise ConfigError(Message("config.error.json_missing_path", path=path))
                node = node[int(part)]
                continue
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(Message("config.error.json_missing_path", path=path))
            node = node[part]
        return node

    @staticmethod
    def _coerce(value: str, previous: Any) -> Any:
        if isinstance(previous, bool):
            return _as_bool(value)
        if isinstance(previous, int):
            try:
                return int(value)
            except ValueError:
                raise ConfigError(Message("config.error.not_an_integer", value=repr(value))) from None
        if isinstance(previous, float):
            try:
                return float(value)
            except ValueError:
                raise ConfigError(Message("config.error.not_a_number", value=repr(value))) from None
        if isinstance(previous, str):
            return value
        # New (or null) key: the type comes from the typed text itself.
        text = value.strip()
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        if NUM_RE.match(text):
            return float(text) if "." in text else int(text)
        return value

    def _apply(self, edits: list[Edit]) -> str:
        for edit in edits:
            value = check_value(edit.value)
            current = self._resolve(edit)
            if current is not None:
                parent = self._parent(current.section)
                key = current.key
            else:
                key = check_key(edit.key)
                if "." in key:
                    raise ConfigError(Message("config.error.json_dot_in_key"))
                parent = self._parent(edit.section)
            if isinstance(parent, list):
                if not key.isdigit() or int(key) >= len(parent):
                    raise ConfigError(Message("config.error.json_add_to_list", name=repr(key)))
                parent[int(key)] = self._coerce(value, parent[int(key)])
                continue
            if not isinstance(parent, dict):
                raise ConfigError(Message("config.error.json_not_object", section=edit.section))
            parent[key] = self._coerce(value, parent.get(key))
        return json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------- dayz


_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M)
# As in _PAIR_RE: no group competes for text with its neighbor ([^;]* stops at the first
# semicolon and the space after '=' is taken out of the value in code).
_DZ_PAIR_RE = re.compile(r"^([ \t]*)([A-Za-z_]\w*)([ \t]*=)([^;]*);[ \t]*(//.*)?$", re.M)


class DayzConfig(ConfigFile):
    """serverDZ.cfg: 'key = value;' with 'class X { ... };' blocks and '//' comments.

    Each class becomes a section (Missions.DayZ.template), and the end-of-line comment
    becomes the field help - it is the only place where the format documents what each key does.
    """

    format_id = "dayz"
    label = "serverDZ.cfg"

    def parse(self) -> None:
        self._lines = self.text.split("\n")
        self._pos: dict[str, tuple[int, str, str, str, bool, str]] = {}
        self._section_end: dict[str, int] = {}
        stack: list[str] = []
        self._section("", ROOT)
        comment = ""

        for i, line in enumerate(self._lines):
            class_match = _CLASS_RE.match(line)
            if class_match:
                stack.append(class_match.group(1))
                path = ".".join(stack)
                self._section(path, path)
                self._section_end[path] = i
                continue
            if line.strip().startswith("}"):
                if stack:
                    stack.pop()
                continue
            if line.strip().startswith("//"):
                comment = line.strip().lstrip("/").strip()
                continue

            pair_match = _DZ_PAIR_RE.match(line)
            if pair_match:
                self._read_pair(i, pair_match, ".".join(stack), comment)
            # A comment only applies to the next line: anything else discards it.
            comment = ""

    def _read_pair(self, i: int, pair_match: re.Match[str], section: str, comment: str) -> None:
        """A `key = value;` line of serverDZ.cfg becomes a field."""
        prefix, name, equals, raw, note = pair_match.groups()
        # The space after '=' stays in the separator, so the line comes back exactly the same.
        sep = equals + raw[:len(raw) - len(raw.lstrip())]
        text, quoted = _unquote(raw.strip())
        self._section_end[section] = i
        sid = f"{section}{SEP}{name}" if section else name
        self._pos[sid] = (i, prefix, name, sep, quoted, note or "")
        self._add(Setting(
            id=sid, section=section, key=name, value=text, kind=_kind_of(text),
            # The end-of-line comment wins over the one from the line above: it talks about
            # this key, and it is the only place where the format documents what it does.
            comment=(note or "").lstrip("/").strip() or comment,
        ), label=section or ROOT)

    @staticmethod
    def _format(value: str, quoted: bool) -> str:
        if quoted or not NUM_RE.match(value.strip()):
            if '"' in value:
                raise ConfigError(Message("config.error.value_double_quote"))
            return f'"{value}"'
        return value.strip()

    def _apply(self, edits: list[Edit]) -> str:
        lines = list(self._lines)
        new_by_section: dict[str, list[str]] = {}

        for edit in edits:
            value = check_value(edit.value)
            current = self._resolve(edit)
            if current is not None and current.id in self._pos:
                i, prefix, name, sep, quoted, note = self._pos[current.id]
                end_note = f"  {note}" if note else ""
                lines[i] = f"{prefix}{name}{sep}{self._format(value, quoted)};{end_note}"
                continue
            key = check_key(edit.key)
            text = self._format(value, quoted=not NUM_RE.match(value.strip()))
            new_by_section.setdefault(edit.section, []).append(f"{key} = {text};")

        pending = sorted(
            new_by_section.items(),
            key=lambda item: self._section_end.get(item[0], len(lines)),
            reverse=True,
        )
        for section, new_lines in pending:
            end = self._section_end.get(section)
            if end is None:
                lines.extend(new_lines)
                continue
            # The indentation of the reference line, without regex: `^\s*` always matches, but the
            # type of `re.match` is still Optional and the analyzer is right to complain.
            reference = lines[end]
            indent = reference[:len(reference) - len(reference.lstrip())]
            _insert_after(lines, end, [f"{indent}{item}" for item in new_lines])

        return "\n".join(lines)


# ---------------------------------------------------------------------- sii


# `server_config : _nameless.39bc.86a0 {` - class, unit name and the opening brace.
_SII_UNIT_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*:\s*([\w.]+)\s*\{\s*$", re.ASCII)
# ` lobby_name: "x"` / ` moderator_list[0]: 7656...` - a list carries the index in the name.
_SII_PAIR_RE = re.compile(r"^([ \t]*)([A-Za-z_]\w*(?:\[\d*\])?)(:[ \t]*)(.*?)[ \t]*$", re.ASCII)
# A value the format accepts without quotes: word, number, true/false.
_SII_BARE_RE = re.compile(r"^[\w.\-]+$", re.ASCII)


class SiiConfig(ConfigFile):
    """ETS2/ATS server_config.sii: 'SiiNunit { class : name { key: value } }'.

    Each unit becomes a section by its CLASS name (`server_config`), and not by the unit
    name: `_nameless.39bc.86a0` is random, and the server rewrites the file on startup.
    With it in the id, an edit made with the screen open during a restart would no longer
    find the key and would append it as a duplicate.
    """

    format_id = "sii"
    label = "SiiNunit (.sii)"
    bool_words = ("true", "false")

    def parse(self) -> None:
        self._lines = self.text.split("\n")
        self._pos: dict[str, tuple[int, str, str, str, bool]] = {}
        self._section_end: dict[str, int] = {}
        current = ""
        seen: dict[str, int] = {}

        for i, line in enumerate(self._lines):
            unit_match = _SII_UNIT_RE.match(line)
            if unit_match:
                cls = unit_match.group(1)
                seen[cls] = seen.get(cls, 0) + 1
                current = cls if seen[cls] == 1 else f"{cls}#{seen[cls]}"
                self._section(current, current)
                self._section_end[current] = i
                continue
            if line.strip().startswith("}"):
                current = ""
                continue
            if not current:
                continue
            pair_match = _SII_PAIR_RE.match(line)
            if pair_match:
                self._read_pair(i, pair_match, current)

    def _read_pair(self, i: int, pair_match: re.Match[str], section: str) -> None:
        prefix, name, sep, raw = pair_match.groups()
        text, quoted = _unquote(raw)
        self._section_end[section] = i
        sid = f"{section}{SEP}{name}"
        self._pos[sid] = (i, prefix, name, sep, quoted)
        self._add(Setting(id=sid, section=section, key=name, value=text, kind=_kind_of(text)),
                  label=section)

    @staticmethod
    def _format(value: str, quoted: bool) -> str:
        # Quotes and backslashes are escapes in .sii; refusing is safer than guessing the
        # escape rule of the SCS reader and leaving the server unable to start.
        if '"' in value or "\\" in value:
            raise ConfigError(Message("config.error.sii_value_quote"))
        # A single word may go without quotes (the server writes `description: discordia`
        # like that), but a phrase with spaces or an empty value without quotes the SCS reader does not understand.
        if quoted or not _SII_BARE_RE.match(value):
            return f'"{value}"'
        return value

    def _apply(self, edits: list[Edit]) -> str:
        lines = list(self._lines)
        new_by_section: dict[str, list[str]] = {}

        for edit in edits:
            value = check_value(edit.value)
            current = self._resolve(edit)
            if current is not None and current.id in self._pos:
                i, prefix, name, sep, quoted = self._pos[current.id]
                lines[i] = f"{prefix}{name}{sep}{self._format(value, quoted)}"
                continue
            if edit.section not in self._section_end:
                raise ConfigError(Message("config.error.sii_needs_block"))
            key = check_key(edit.key)
            if " " in key or "." in key or "-" in key:
                raise ConfigError(Message("config.error.sii_invalid_name", name=repr(key)))
            new_by_section.setdefault(edit.section, []).append(
                f"{key}: {self._format(value, quoted=False)}")

        # Bottom up: inserting into a block does not shift the position of the ones above.
        for section, new_lines in sorted(new_by_section.items(),
                                         key=lambda item: self._section_end[item[0]], reverse=True):
            end = self._section_end[section]
            reference = lines[end]
            indent = reference[:len(reference) - len(reference.lstrip())] or " "
            _insert_after(lines, end, [f"{indent}{item}" for item in new_lines])

        return "\n".join(lines)


# ------------------------------------------------------------------ detection


def load(name: str, text: str) -> ConfigFile:
    """Pick the format by file name + content and return the parsed document."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    # Without the BOM: `lstrip` does not remove it (it is not whitespace), and a JSON with a BOM
    # and an odd extension would no longer be recognized by the leading "{".
    start = text.removeprefix(BOM).lstrip()[:1]

    # Before ini: .sii used to fall into the ini reader, which finds no `=` at all and showed an
    # empty form ("Configuracoes (0)") for the ETS2 server_config.sii.
    if ext == "sii" or text.removeprefix(BOM).lstrip().startswith("SiiNunit"):
        return SiiConfig(text)
    if ext == "json" or (start in ("{", "[") and ext not in ("ini", "cfg", "conf", "properties")):
        return JsonConfig(text)
    if _CLASS_RE.search(text) or (ext == "cfg" and _DZ_PAIR_RE.search(text)):
        return DayzConfig(text)
    return IniConfig(text)
