#!/usr/bin/env python3
"""Le e grava os arquivos de configuracao dos jogos campo a campo.

A tela "Arquivos" resolve tudo, mas exige achar o arquivo, achar a linha e nao errar a
virgula. Aqui o arquivo vira uma lista de configuracoes (secao, chave, valor) que a tela
"Config" mostra como formulario — e a gravacao volta mexendo APENAS nas chaves que o
usuario alterou, preservando comentarios, ordem e todo o resto do arquivo.

Formatos (detectados pelo nome + conteudo):
  ini   - .ini/.conf/.properties comuns. Valores no formato da Unreal
          (OptionSettings=(Chave=Valor,...), do Palworld) viram sub-configuracoes.
  json  - Enshrouded (enshrouded_server.json)
  dayz  - serverDZ.cfg: 'chave = valor;' e blocos 'class X { ... };'

Este modulo nao fala SSH nem HTTP: recebe texto, devolve texto. E o que permite testa-lo
sozinho (test_config_format.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# Separa os niveis do identificador de uma configuracao ("secao\x1fchave"). Nao aparece
# em arquivo de config nenhum, entao serve de separador sem escape.
SEP = "\x1f"

# Rotulo do bloco sem nome: chave solta no topo de um .ini, ou o nivel de cima de um
# .json. Vira titulo de secao na tela de Configuracao, e os tres formatos precisam
# dizer a MESMA coisa - nao "(sem secao)" num e "(raiz)" no outro para a mesma ideia.
NO_SECTION = "(sem secao)"
ROOT = "(raiz)"

# Marca de ordem de bytes do UTF-8, ja decodificada: e como ela chega aqui (o texto vem lido).
BOM = "﻿"

VALUE_MAX = 4000
# Nome de chave aceito num arquivo de configuracao de jogo.
#
# O `re.ASCII` nao e detalhe: sem ele, `\w` em Python casa letra acentuada, digito
# arabe-indico e mais uns 900 caracteres Unicode - e este nome vai parar dentro do
# arquivo do jogo, escrito por SSH. Com a flag, `\w` e exatamente `[A-Za-z0-9_]`, que
# era a forma antiga desta expressao.
KEY_RE = re.compile(r"^\w[\w.\- ]{0,79}$", re.ASCII)
BOOL_WORDS = {"true": True, "false": False, "1": True, "0": False,
              "sim": True, "nao": False, "yes": True, "no": False}
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


class ConfigError(ValueError):
    """Erro de forma: arquivo que nao da para interpretar, chave/valor invalido."""


@dataclass
class Setting:
    """Uma linha do formulario: uma chave de configuracao do jogo."""

    id: str                 # identificador estavel, usado para reencontrar a chave
    section: str            # bloco onde ela mora (id opaco)
    key: str
    value: str
    kind: str = "text"      # text | bool | number
    comment: str = ""       # comentario vizinho no arquivo, vira ajuda na tela
    # Preenchidos depois da leitura, pelo catalogo de campos (`games/registry.py`). Ficam
    # aqui e nao no parser de proposito: o parser continua sem saber que jogo e esse.
    spec: object = None     # games.base.FieldSpec, quando o campo e conhecido
    display_value: str = ""  # valor na unidade da tela (minutos em vez de nanossegundos)


@dataclass
class Section:
    """Bloco de configuracoes ([secao] do ini, class do DayZ, objeto do JSON)."""

    id: str
    label: str
    settings: list[Setting] = field(default_factory=list)


@dataclass
class Edit:
    """Uma alteracao vinda do formulario.

    `id` vazio (ou que nao existe mais no arquivo) significa configuracao nova: ela e
    procurada por secao+chave e, se nao existir, acrescentada no fim do bloco.
    """

    section: str
    key: str
    value: str
    id: str = ""


def check_key(key: str) -> str:
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise ConfigError(f"nome de configuracao invalido: {key!r}")
    return key


def check_value(value: str) -> str:
    value = (value or "").replace("\r", "")
    if "\n" in value or "\x00" in value:
        raise ConfigError("o valor nao pode ter quebra de linha")
    if len(value) > VALUE_MAX:
        raise ConfigError(f"valor longo demais (limite de {VALUE_MAX} caracteres)")
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
        raise ConfigError(f"valor booleano invalido: {value!r} (use True ou False)")
    return got


# --------------------------------------------------------------------- base


class ConfigFile:
    """Contrato comum: parse no construtor, `apply` devolve o arquivo novo."""

    format_id = "texto"
    label = "Texto"
    # Como o formato escreve verdadeiro/falso. A tela usa isto no seletor dos campos
    # booleanos: com a grafia certa, abrir e salvar sem mexer em nada nao "altera" nada.
    bool_words = ("True", "False")

    def __init__(self, text: str) -> None:
        # O BOM (U+FEFF no comeco) sai antes de qualquer leitor ver o texto e volta no `apply`.
        # Os padroes do V Rising vem com ele, e o `json.loads` o recusa ("Unexpected UTF-8 BOM"):
        # a tela Config nao abria o ServerHostSettings.json. Devolver ao gravar e para o arquivo
        # sair igual ao que o jogo escreveu, e nao trocar a codificacao de um arquivo alheio.
        self.bom = text.startswith(BOM)
        self.text = text[len(BOM):] if self.bom else text
        self.settings: list[Setting] = []
        self._sections: dict[str, Section] = {}
        self.parse()

    # -- leitura -------------------------------------------------------
    def parse(self) -> None:  # pragma: no cover - implementado nas subclasses
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
        """Blocos com conteudo. Um arquivo sem nenhuma chave devolve o que houver."""
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

    # -- escrita -------------------------------------------------------
    def apply(self, edits: list[Edit]) -> str:
        """O arquivo novo, com o BOM de volta se o original tinha."""
        out = self._apply(edits)
        return BOM + out if self.bom else out

    def _apply(self, edits: list[Edit]) -> str:  # pragma: no cover - subclasses
        raise NotImplementedError

    def _resolve(self, edit: Edit) -> Setting | None:
        """Acha a configuracao que o formulario quer mudar (por id, depois por nome)."""
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
# Corta so no primeiro '='; o espaco em volta e separado no codigo. Grupos "opcionais"
# disputando o mesmo texto (\s* ao lado de [^=]*?) fazem o motor de regex voltar atras
# muitas vezes numa linha longa - e a linha do Palworld tem alguns milhares de bytes.
_PAIR_RE = re.compile(r"^(\s*)([^=\s\[#;][^=]*)=(.*)$")


def _nesting_depth(ch: str, depth: int) -> int:
    """Quanto este caractere mexe no aninhamento de parenteses/colchetes."""
    if ch in "([":
        return depth + 1
    if ch in ")]":
        return depth - 1
    return depth


def _split_tuple(inner: str) -> list[str] | None:
    """Quebra 'A=1,B="x,y",C=(D=2)' nos pares de primeiro nivel.

    Devolve None se o texto nao parecer uma lista de pares (ai o valor fica como texto).
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
            return None  # fechou um parentese que nunca abriu: nao e lista de pares
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
    """Os pares de um valor no formato da Unreal, ou None se nao for um.

    `OptionSettings=(Difficulty=None,ExpRate=1.0)` - onde o Palworld guarda TODA a
    configuracao - nao e um valor: e uma configuracao inteira dentro de uma linha. O
    `=` no meio e o que separa isso de um valor comum entre parenteses.
    """
    inner = value.strip()
    if not (inner.startswith("(") and inner.endswith(")") and "=" in inner):
        return None
    return _split_tuple(inner[1:-1])


_MIN_QUOTED_LENGTH = 2  # abre e fecha aspas: '""' e o menor valor entre aspas possivel


def _unquote(value: str) -> tuple[str, bool]:
    value = value.strip()
    if len(value) >= _MIN_QUOTED_LENGTH and value[0] == '"' and value[-1] == '"':
        return value[1:-1], True
    return value, False


def _requote(value: str, was_quoted: bool) -> str:
    """Devolve o valor no formato do arquivo: com aspas se ja tinha, ou se precisa."""
    if '"' in value:
        raise ConfigError('o valor nao pode conter aspas duplas (")')
    needs_quotes = any(ch in value for ch in ',()= ') or value == ""
    if was_quoted or needs_quotes:
        return f'"{value}"'
    return value


@dataclass
class _Pair:
    """Par de dentro de um valor no formato da Unreal: Chave=Valor."""

    key: str
    value: str
    quoted: bool


@dataclass
class _TupleLine:
    """Linha 'Chave=(A=1,B=2)' de um .ini da Unreal (Palworld)."""

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
    """.ini/.conf/.properties, com ou sem [secoes].

    Valores no formato da Unreal — `OptionSettings=(Difficulty=None,ExpRate=1.0,...)`,
    que e onde o Palworld guarda TODA a configuracao — sao abertos em sub-configuracoes,
    cada par virando um campo do formulario.
    """

    format_id = "ini"
    label = "INI"

    def parse(self) -> None:
        self._lines = self.text.split("\n")
        self._plain: dict[str, tuple[int, str, str, str]] = {}  # id -> (linha, prefixo, nome, sep)
        self._tuples: dict[str, _TupleLine] = {}                # id da secao -> linha
        self._pairs: dict[str, int] = {}                        # id -> posicao dentro da tupla
        self._section_end: dict[str, int] = {}                  # id -> ultima linha util
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
            # Comentario so vale para a linha seguinte: qualquer outra coisa o descarta.
            comment_lines = []

    def _read_pair(self, i: int, pair_match: re.Match[str], section: str,
                    comment_lines: list[str], seen: dict[str, int]) -> None:
        """Uma linha `chave = valor` do .ini vira um campo (ou varios, se for tupla)."""
        prefix, raw_key, rest = pair_match.groups()
        name = raw_key.rstrip()
        value = rest.strip()
        # sep e sufixo guardam o espacamento original: gravar de volta nao pode
        # reformatar uma linha que o usuario nem tocou.
        sep = raw_key[len(name):] + "=" + rest[:len(rest) - len(rest.lstrip())]
        suffix = rest[len(rest.rstrip()):]
        self._section_end[section] = i

        # Ids repetem quando a mesma chave aparece duas vezes na secao (comum na
        # Unreal): o sufixo mantem cada ocorrencia com identidade propria.
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
        target = sid  # a secao das sub-configuracoes e o proprio id da linha
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

    # -- escrita -------------------------------------------------------
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
        """Grava UMA alteracao. Sao quatro destinos possiveis, nesta ordem:

        a linha que ja existe, um par dentro de uma tupla da Unreal, uma chave nova
        dentro dessa tupla, ou uma chave nova no fim da secao (esta ultima fica
        pendente: inserir linha aqui deslocaria tudo o que vem depois).
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
        if edit.section in self._tuples:  # configuracao nova dentro do OptionSettings
            group = self._tuples[edit.section]
            group.pairs.append(_Pair(key=key, value=value, quoted=False))
            changed_tuples.add(edit.section)
            return

        new_by_section.setdefault(edit.section, []).append(f"{key}={value}")

    def _insert_new_settings(self, lines: list[str], new_by_section: dict[str, list[str]]) -> None:
        """Acrescenta as chaves novas no fim de cada secao.

        De tras para frente: inserir no fim de uma secao nao pode deslocar as linhas
        das secoes ainda por inserir.
        """
        pending = sorted(
            new_by_section.items(),
            key=lambda item: self._section_end.get(item[0], len(lines)),
            reverse=True,
        )
        for section, new_lines in pending:
            end = self._section_end.get(section)
            if end is None:
                # Secao que nao existia no arquivo: nasce no fim, com cabecalho.
                if section:
                    lines.append(f"[{section}]")
                lines.extend(new_lines)
                continue
            _insert_after(lines, end, new_lines)


# --------------------------------------------------------------------- json


def _json_text(value: Any) -> str:
    """Valor do JSON como a tela o mostra.

    `null` vira campo vazio, e booleano vira a grafia do JSON ("true"/"false") e nao a
    do Python ("True"): o que sai daqui volta para o arquivo, e `True` quebraria o JSON.
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _json_kind(value: Any) -> str:
    """Que campo o formulario desenha para este valor: caixa, numero ou texto.

    `bool` antes de `(int, float)` de proposito: em Python `True` e um `int`, e na
    ordem contraria toda caixa de marcar viraria um campo de numero.
    """
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


class JsonConfig(ConfigFile):
    """Config em JSON (Enshrouded). Objetos aninhados viram secoes.

    O JSON e reescrito inteiro pelo `json.dumps` — o arquivo sai indentado com 2
    espacos, que e como a Keen Games publica o exemplo. JSON nao tem comentario, entao
    nao ha nada a preservar alem dos valores.
    """

    format_id = "json"
    label = "JSON"
    bool_words = ("true", "false")

    data: dict[str, Any] | list[Any]

    def parse(self) -> None:
        try:
            self.data = json.loads(self.text or "{}")
        except ValueError as exc:
            raise ConfigError(f"JSON invalido: {exc}") from exc
        if not isinstance(self.data, (dict, list)):
            raise ConfigError("JSON precisa ser um objeto ou lista para virar formulario")
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
                    raise ConfigError(f"caminho inexistente no JSON: {path}")
                node = node[int(part)]
                continue
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"caminho inexistente no JSON: {path}")
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
                raise ConfigError(f"{value!r} nao e um numero inteiro") from None
        if isinstance(previous, float):
            try:
                return float(value)
            except ValueError:
                raise ConfigError(f"{value!r} nao e um numero") from None
        if isinstance(previous, str):
            return value
        # Chave nova (ou nula): o tipo sai do proprio texto digitado.
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
                    raise ConfigError("ponto (.) nao e aceito no nome de uma chave JSON")
                parent = self._parent(edit.section)
            if isinstance(parent, list):
                if not key.isdigit() or int(key) >= len(parent):
                    raise ConfigError(f"nao da para acrescentar {key!r} numa lista JSON")
                parent[int(key)] = self._coerce(value, parent[int(key)])
                continue
            if not isinstance(parent, dict):
                raise ConfigError(f"{edit.section} nao e um objeto JSON")
            parent[key] = self._coerce(value, parent.get(key))
        return json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------- dayz


_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M)
# Como no _PAIR_RE: nenhum grupo disputa texto com o vizinho ([^;]* para no primeiro
# ponto-e-virgula e o espaco depois do '=' sai do valor no codigo).
_DZ_PAIR_RE = re.compile(r"^([ \t]*)([A-Za-z_]\w*)([ \t]*=)([^;]*);[ \t]*(//.*)?$", re.M)


class DayzConfig(ConfigFile):
    """serverDZ.cfg: 'chave = valor;' com blocos 'class X { ... };' e comentario '//'.

    Cada class vira uma secao (Missions.DayZ.template), e o comentario no fim da linha
    vira a ajuda do campo — e o unico lugar onde o formato documenta o que cada chave faz.
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
            # Comentario so vale para a linha seguinte: qualquer outra coisa o descarta.
            comment = ""

    def _read_pair(self, i: int, pair_match: re.Match[str], section: str, comment: str) -> None:
        """Uma linha `chave = valor;` do serverDZ.cfg vira um campo."""
        prefix, name, equals, raw, note = pair_match.groups()
        # O espaco depois do '=' fica no separador, para a linha voltar igualzinha.
        sep = equals + raw[:len(raw) - len(raw.lstrip())]
        text, quoted = _unquote(raw.strip())
        self._section_end[section] = i
        sid = f"{section}{SEP}{name}" if section else name
        self._pos[sid] = (i, prefix, name, sep, quoted, note or "")
        self._add(Setting(
            id=sid, section=section, key=name, value=text, kind=_kind_of(text),
            # O comentario no fim da linha ganha do que veio na linha de cima: ele fala
            # desta chave, e e o unico lugar onde o formato documenta o que ela faz.
            comment=(note or "").lstrip("/").strip() or comment,
        ), label=section or ROOT)

    @staticmethod
    def _format(value: str, quoted: bool) -> str:
        if quoted or not NUM_RE.match(value.strip()):
            if '"' in value:
                raise ConfigError('o valor nao pode conter aspas duplas (")')
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
            # O recuo da linha de referencia, sem regex: `^\s*` casa sempre, mas o tipo
            # de `re.match` continua sendo Optional e o analisador tem razao em cobrar.
            reference = lines[end]
            indent = reference[:len(reference) - len(reference.lstrip())]
            _insert_after(lines, end, [f"{indent}{item}" for item in new_lines])

        return "\n".join(lines)


# ------------------------------------------------------------------ deteccao


def load(name: str, text: str) -> ConfigFile:
    """Escolhe o formato pelo nome do arquivo + conteudo e devolve o documento lido."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    # Sem o BOM: `lstrip` nao o tira (nao e espaco), e um JSON com BOM e extensao estranha
    # deixaria de ser reconhecido pelo "{" do comeco.
    start = text.removeprefix(BOM).lstrip()[:1]

    if ext == "json" or (start in ("{", "[") and ext not in ("ini", "cfg", "conf", "properties")):
        return JsonConfig(text)
    if _CLASS_RE.search(text) or (ext == "cfg" and _DZ_PAIR_RE.search(text)):
        return DayzConfig(text)
    return IniConfig(text)
