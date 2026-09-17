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
sozinho (test_gameconf.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Separa os niveis do identificador de uma configuracao ("secao\x1fchave"). Nao aparece
# em arquivo de config nenhum, entao serve de separador sem escape.
SEP = "\x1f"

# Rotulo do bloco sem nome: chave solta no topo de um .ini, ou o nivel de cima de um
# .json. Vira titulo de secao na tela de Configuracao, e os tres formatos precisam
# dizer a MESMA coisa - nao "(sem secao)" num e "(raiz)" no outro para a mesma ideia.
SEM_SECAO = "(sem secao)"
RAIZ = "(raiz)"

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
    # Preenchidos depois da leitura, pelo catalogo de campos (gamefields.py). Ficam
    # aqui e nao no parser de proposito: o parser continua sem saber que jogo e esse.
    spec: object = None     # gamefields.FieldSpec, quando o campo e conhecido
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

    formato = "texto"
    rotulo = "Texto"
    # Como o formato escreve verdadeiro/falso. A tela usa isto no seletor dos campos
    # booleanos: com a grafia certa, abrir e salvar sem mexer em nada nao "altera" nada.
    bool_words = ("True", "False")

    def __init__(self, text: str) -> None:
        self.text = text
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
        self._section(setting.section, label or setting.section or SEM_SECAO)
        self._sections[setting.section].settings.append(setting)
        self.settings.append(setting)

    @property
    def sections(self) -> list[Section]:
        """Blocos com conteudo. Um arquivo sem nenhuma chave devolve o que houver."""
        cheias = [s for s in self._sections.values() if s.settings]
        return cheias or list(self._sections.values())

    def get(self, sid: str) -> Setting | None:
        for s in self.settings:
            if s.id == sid:
                return s
        return None

    def find(self, section: str, key: str) -> Setting | None:
        alvo = key.strip().lower()
        for s in self.settings:
            if s.section == section and s.key.strip().lower() == alvo:
                return s
        return None

    # -- escrita -------------------------------------------------------
    def apply(self, edits: list[Edit]) -> str:  # pragma: no cover - subclasses
        raise NotImplementedError

    def _resolve(self, edit: Edit) -> Setting | None:
        """Acha a configuracao que o formulario quer mudar (por id, depois por nome)."""
        if edit.id:
            achado = self.get(edit.id)
            if achado is not None:
                return achado
        return self.find(edit.section, edit.key)


def _insert_after(lines: list[str], index: int, novas: list[str]) -> None:
    lines[index + 1:index + 1] = novas


# ---------------------------------------------------------------------- ini


_SECTION_RE = re.compile(r"^\s*\[([^\]]*)\]\s*$")
_COMMENT_RE = re.compile(r"^\s*[#;]")
# Corta so no primeiro '='; o espaco em volta e separado no codigo. Grupos "opcionais"
# disputando o mesmo texto (\s* ao lado de [^=]*?) fazem o motor de regex voltar atras
# muitas vezes numa linha longa - e a linha do Palworld tem alguns milhares de bytes.
_PAIR_RE = re.compile(r"^(\s*)([^=\s\[#;][^=]*)=(.*)$")


def _profundidade(ch: str, atual: int) -> int:
    """Quanto este caractere mexe no aninhamento de parenteses/colchetes."""
    if ch in "([":
        return atual + 1
    if ch in ")]":
        return atual - 1
    return atual


def _split_tuple(inner: str) -> list[str] | None:
    """Quebra 'A=1,B="x,y",C=(D=2)' nos pares de primeiro nivel.

    Devolve None se o texto nao parecer uma lista de pares (ai o valor fica como texto).
    """
    partes: list[str] = []
    buf = ""
    depth = 0
    aspas = False
    for ch in inner:
        if aspas:
            buf += ch
            aspas = ch != '"'
            continue
        if ch == '"':
            aspas = True
            buf += ch
            continue
        depth = _profundidade(ch, depth)
        if depth < 0:
            return None  # fechou um parentese que nunca abriu: nao e lista de pares
        if ch == "," and depth == 0:
            partes.append(buf)
            buf = ""
            continue
        buf += ch
    if aspas or depth != 0:
        return None
    if buf.strip():
        partes.append(buf)
    return partes


def _pares_da_tupla(valor: str) -> list[str] | None:
    """Os pares de um valor no formato da Unreal, ou None se nao for um.

    `OptionSettings=(Difficulty=None,ExpRate=1.0)` - onde o Palworld guarda TODA a
    configuracao - nao e um valor: e uma configuracao inteira dentro de uma linha. O
    `=` no meio e o que separa isso de um valor comum entre parenteses.
    """
    miolo = valor.strip()
    if not (miolo.startswith("(") and miolo.endswith(")") and "=" in miolo):
        return None
    return _split_tuple(miolo[1:-1])


def _unquote(value: str) -> tuple[str, bool]:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1], True
    return value, False


def _requote(value: str, era_aspas: bool) -> str:
    """Devolve o valor no formato do arquivo: com aspas se ja tinha, ou se precisa."""
    if '"' in value:
        raise ConfigError('o valor nao pode conter aspas duplas (")')
    precisa = any(ch in value for ch in ',()= ') or value == ""
    if era_aspas or precisa:
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
        corpo = ",".join(f"{p.key}={_requote(p.value, p.quoted)}" for p in self.pairs)
        return f"{self.prefix}{self.name}{self.sep}({corpo}){self.suffix}"


class IniConfig(ConfigFile):
    """.ini/.conf/.properties, com ou sem [secoes].

    Valores no formato da Unreal — `OptionSettings=(Difficulty=None,ExpRate=1.0,...)`,
    que e onde o Palworld guarda TODA a configuracao — sao abertos em sub-configuracoes,
    cada par virando um campo do formulario.
    """

    formato = "ini"
    rotulo = "INI"

    def parse(self) -> None:
        self._lines = self.text.split("\n")
        self._plain: dict[str, tuple[int, str, str, str]] = {}  # id -> (linha, prefixo, nome, sep)
        self._tuples: dict[str, _TupleLine] = {}                # id da secao -> linha
        self._pairs: dict[str, int] = {}                        # id -> posicao dentro da tupla
        self._section_end: dict[str, int] = {}                  # id -> ultima linha util
        secao = ""
        self._section(secao, SEM_SECAO)
        comentario: list[str] = []
        vistos: dict[str, int] = {}

        for i, linha in enumerate(self._lines):
            achou = _SECTION_RE.match(linha)
            if achou:
                secao = achou.group(1).strip()
                self._section(secao, f"[{secao}]")
                self._section_end[secao] = i
                comentario = []
                continue
            if not linha.strip():
                comentario = []
                continue
            if _COMMENT_RE.match(linha):
                comentario.append(linha.strip().lstrip("#;").strip())
                continue

            par = _PAIR_RE.match(linha)
            if par:
                self._le_par(i, par, secao, comentario, vistos)
            # Comentario so vale para a linha seguinte: qualquer outra coisa o descarta.
            comentario = []

    def _le_par(self, i: int, par, secao: str, comentario: list[str],
                vistos: dict[str, int]) -> None:
        """Uma linha `chave = valor` do .ini vira um campo (ou varios, se for tupla)."""
        prefixo, chave_bruta, resto = par.groups()
        nome = chave_bruta.rstrip()
        valor = resto.strip()
        # sep e sufixo guardam o espacamento original: gravar de volta nao pode
        # reformatar uma linha que o usuario nem tocou.
        sep = chave_bruta[len(nome):] + "=" + resto[:len(resto) - len(resto.lstrip())]
        sufixo = resto[len(resto.rstrip()):]
        self._section_end[secao] = i

        # Ids repetem quando a mesma chave aparece duas vezes na secao (comum na
        # Unreal): o sufixo mantem cada ocorrencia com identidade propria.
        base = f"{secao}{SEP}{nome}"
        vistos[base] = vistos.get(base, 0) + 1
        sid = base if vistos[base] == 1 else f"{base}{SEP}#{vistos[base]}"

        pares = _pares_da_tupla(valor)
        if pares is not None:
            self._parse_tuple(sid, secao, nome, i, prefixo, sep, sufixo, pares)
            return

        self._plain[sid] = (i, prefixo, nome, sep)
        self._add(Setting(
            id=sid, section=secao, key=nome, value=valor,
            kind=_kind_of(valor), comment=" ".join(comentario),
        ), label=f"[{secao}]" if secao else SEM_SECAO)

    def _parse_tuple(self, sid, secao, nome, linha, prefixo, sep, sufixo, pares) -> None:
        alvo = sid  # a secao das sub-configuracoes e o proprio id da linha
        self._section(alvo, f"[{secao}] {nome}" if secao else nome)
        objetos: list[_Pair] = []
        vistos: dict[str, int] = {}
        for bruto in pares:
            chave, igual, valor = bruto.partition("=")
            if not igual:
                continue
            chave = chave.strip()
            texto, aspas = _unquote(valor)
            vistos[chave] = vistos.get(chave, 0) + 1
            sufixo_id = "" if vistos[chave] == 1 else f"{SEP}#{vistos[chave]}"
            pid = f"{alvo}{SEP}{chave}{sufixo_id}"
            self._pairs[pid] = len(objetos)
            objetos.append(_Pair(key=chave, value=texto, quoted=aspas))
            self._add(Setting(
                id=pid, section=alvo, key=chave, value=texto, kind=_kind_of(texto),
            ))
        self._tuples[alvo] = _TupleLine(
            line=linha, prefix=prefixo, name=nome, sep=sep, pairs=objetos, suffix=sufixo,
        )
        if not objetos:
            self._section(alvo, f"[{secao}] {nome}" if secao else nome)

    # -- escrita -------------------------------------------------------
    def apply(self, edits: list[Edit]) -> str:
        linhas = list(self._lines)
        novas_por_secao: dict[str, list[str]] = {}
        tuplas_mexidas: set[str] = set()

        for edit in edits:
            self._aplica_edit(edit, linhas, novas_por_secao, tuplas_mexidas)

        for sid in tuplas_mexidas:
            grupo = self._tuples[sid]
            linhas[grupo.line] = grupo.render()

        self._insere_novas(linhas, novas_por_secao)
        return "\n".join(linhas)

    def _aplica_edit(self, edit: Edit, linhas: list[str],
                     novas_por_secao: dict[str, list[str]],
                     tuplas_mexidas: set[str]) -> None:
        """Grava UMA alteracao. Sao quatro destinos possiveis, nesta ordem:

        a linha que ja existe, um par dentro de uma tupla da Unreal, uma chave nova
        dentro dessa tupla, ou uma chave nova no fim da secao (esta ultima fica
        pendente: inserir linha aqui deslocaria tudo o que vem depois).
        """
        valor = check_value(edit.value)
        atual = self._resolve(edit)

        if atual is not None and atual.id in self._plain:
            i, prefixo, nome, sep = self._plain[atual.id]
            linhas[i] = f"{prefixo}{nome}{sep}{valor}"
            return

        if atual is not None and atual.id in self._pairs:
            grupo = self._tuples[atual.section]
            grupo.pairs[self._pairs[atual.id]].value = valor
            tuplas_mexidas.add(atual.section)
            return

        chave = check_key(edit.key)
        if edit.section in self._tuples:  # configuracao nova dentro do OptionSettings
            grupo = self._tuples[edit.section]
            grupo.pairs.append(_Pair(key=chave, value=valor, quoted=False))
            tuplas_mexidas.add(edit.section)
            return

        novas_por_secao.setdefault(edit.section, []).append(f"{chave}={valor}")

    def _insere_novas(self, linhas: list[str], novas_por_secao: dict[str, list[str]]) -> None:
        """Acrescenta as chaves novas no fim de cada secao.

        De tras para frente: inserir no fim de uma secao nao pode deslocar as linhas
        das secoes ainda por inserir.
        """
        pendentes = sorted(
            novas_por_secao.items(),
            key=lambda item: self._section_end.get(item[0], len(linhas)),
            reverse=True,
        )
        for secao, novas in pendentes:
            fim = self._section_end.get(secao)
            if fim is None:
                # Secao que nao existia no arquivo: nasce no fim, com cabecalho.
                if secao:
                    linhas.append(f"[{secao}]")
                linhas.extend(novas)
                continue
            _insert_after(linhas, fim, novas)


# --------------------------------------------------------------------- json


def _texto_json(valor) -> str:
    """Valor do JSON como a tela o mostra.

    `null` vira campo vazio, e booleano vira a grafia do JSON ("true"/"false") e nao a
    do Python ("True"): o que sai daqui volta para o arquivo, e `True` quebraria o JSON.
    """
    if valor is None:
        return ""
    if valor is True:
        return "true"
    if valor is False:
        return "false"
    return str(valor)


def _tipo_json(valor) -> str:
    """Que campo o formulario desenha para este valor: caixa, numero ou texto.

    `bool` antes de `(int, float)` de proposito: em Python `True` e um `int`, e na
    ordem contraria toda caixa de marcar viraria um campo de numero.
    """
    if isinstance(valor, bool):
        return "bool"
    if isinstance(valor, (int, float)):
        return "number"
    return "text"


class JsonConfig(ConfigFile):
    """Config em JSON (Enshrouded). Objetos aninhados viram secoes.

    O JSON e reescrito inteiro pelo `json.dumps` — o arquivo sai indentado com 2
    espacos, que e como a Keen Games publica o exemplo. JSON nao tem comentario, entao
    nao ha nada a preservar alem dos valores.
    """

    formato = "json"
    rotulo = "JSON"
    bool_words = ("true", "false")

    def parse(self) -> None:
        try:
            self.data = json.loads(self.text or "{}")
        except ValueError as exc:
            raise ConfigError(f"JSON invalido: {exc}")
        if not isinstance(self.data, (dict, list)):
            raise ConfigError("JSON precisa ser um objeto ou lista para virar formulario")
        self._section("", RAIZ)
        self._walk(self.data, "")

    def _walk(self, node, caminho: str) -> None:
        itens = node.items() if isinstance(node, dict) else enumerate(node)
        for chave, valor in itens:
            chave = str(chave)
            filho = f"{caminho}.{chave}" if caminho else chave
            if isinstance(valor, (dict, list)):
                self._section(filho, filho)
                self._walk(valor, filho)
                continue
            self._add(Setting(
                id=filho, section=caminho, key=chave,
                value=_texto_json(valor), kind=_tipo_json(valor),
            ), label=caminho or RAIZ)

    def _parent(self, caminho: str):
        node = self.data
        if not caminho:
            return node
        for parte in caminho.split("."):
            if isinstance(node, list):
                if not parte.isdigit() or int(parte) >= len(node):
                    raise ConfigError(f"caminho inexistente no JSON: {caminho}")
                node = node[int(parte)]
                continue
            if not isinstance(node, dict) or parte not in node:
                raise ConfigError(f"caminho inexistente no JSON: {caminho}")
            node = node[parte]
        return node

    @staticmethod
    def _coerce(valor: str, anterior):
        if isinstance(anterior, bool):
            return _as_bool(valor)
        if isinstance(anterior, int):
            try:
                return int(valor)
            except ValueError:
                raise ConfigError(f"{valor!r} nao e um numero inteiro")
        if isinstance(anterior, float):
            try:
                return float(valor)
            except ValueError:
                raise ConfigError(f"{valor!r} nao e um numero")
        if isinstance(anterior, str):
            return valor
        # Chave nova (ou nula): o tipo sai do proprio texto digitado.
        texto = valor.strip()
        if texto.lower() in ("true", "false"):
            return texto.lower() == "true"
        if NUM_RE.match(texto):
            return float(texto) if "." in texto else int(texto)
        return valor

    def apply(self, edits: list[Edit]) -> str:
        for edit in edits:
            valor = check_value(edit.value)
            atual = self._resolve(edit)
            if atual is not None:
                pai = self._parent(atual.section)
                chave = atual.key
            else:
                chave = check_key(edit.key)
                if "." in chave:
                    raise ConfigError("ponto (.) nao e aceito no nome de uma chave JSON")
                pai = self._parent(edit.section)
            if isinstance(pai, list):
                if not chave.isdigit() or int(chave) >= len(pai):
                    raise ConfigError(f"nao da para acrescentar {chave!r} numa lista JSON")
                pai[int(chave)] = self._coerce(valor, pai[int(chave)])
                continue
            if not isinstance(pai, dict):
                raise ConfigError(f"{edit.section} nao e um objeto JSON")
            pai[chave] = self._coerce(valor, pai.get(chave))
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

    formato = "dayz"
    rotulo = "serverDZ.cfg"

    def parse(self) -> None:
        self._lines = self.text.split("\n")
        self._pos: dict[str, tuple[int, str, str, str, bool, str]] = {}
        self._section_end: dict[str, int] = {}
        pilha: list[str] = []
        self._section("", RAIZ)
        comentario = ""

        for i, linha in enumerate(self._lines):
            aberto = _CLASS_RE.match(linha)
            if aberto:
                pilha.append(aberto.group(1))
                caminho = ".".join(pilha)
                self._section(caminho, caminho)
                self._section_end[caminho] = i
                continue
            if linha.strip().startswith("}"):
                if pilha:
                    pilha.pop()
                continue
            if linha.strip().startswith("//"):
                comentario = linha.strip().lstrip("/").strip()
                continue

            par = _DZ_PAIR_RE.match(linha)
            if par:
                self._le_par(i, par, ".".join(pilha), comentario)
            # Comentario so vale para a linha seguinte: qualquer outra coisa o descarta.
            comentario = ""

    def _le_par(self, i: int, par, secao: str, comentario: str) -> None:
        """Uma linha `chave = valor;` do serverDZ.cfg vira um campo."""
        prefixo, nome, igual, bruto, nota = par.groups()
        # O espaco depois do '=' fica no separador, para a linha voltar igualzinha.
        sep = igual + bruto[:len(bruto) - len(bruto.lstrip())]
        texto, aspas = _unquote(bruto.strip())
        self._section_end[secao] = i
        sid = f"{secao}{SEP}{nome}" if secao else nome
        self._pos[sid] = (i, prefixo, nome, sep, aspas, nota or "")
        self._add(Setting(
            id=sid, section=secao, key=nome, value=texto, kind=_kind_of(texto),
            # O comentario no fim da linha ganha do que veio na linha de cima: ele fala
            # desta chave, e e o unico lugar onde o formato documenta o que ela faz.
            comment=(nota or "").lstrip("/").strip() or comentario,
        ), label=secao or RAIZ)

    @staticmethod
    def _formata(valor: str, aspas: bool) -> str:
        if aspas or not NUM_RE.match(valor.strip()):
            if '"' in valor:
                raise ConfigError('o valor nao pode conter aspas duplas (")')
            return f'"{valor}"'
        return valor.strip()

    def apply(self, edits: list[Edit]) -> str:
        linhas = list(self._lines)
        novas_por_secao: dict[str, list[str]] = {}

        for edit in edits:
            valor = check_value(edit.value)
            atual = self._resolve(edit)
            if atual is not None and atual.id in self._pos:
                i, prefixo, nome, sep, aspas, nota = self._pos[atual.id]
                fim = f"  {nota}" if nota else ""
                linhas[i] = f"{prefixo}{nome}{sep}{self._formata(valor, aspas)};{fim}"
                continue
            chave = check_key(edit.key)
            texto = self._formata(valor, aspas=not NUM_RE.match(valor.strip()))
            novas_por_secao.setdefault(edit.section, []).append(f"{chave} = {texto};")

        pendentes = sorted(
            novas_por_secao.items(),
            key=lambda item: self._section_end.get(item[0], len(linhas)),
            reverse=True,
        )
        for secao, novas in pendentes:
            fim = self._section_end.get(secao)
            if fim is None:
                linhas.extend(novas)
                continue
            # O recuo da linha de referencia, sem regex: `^\s*` casa sempre, mas o tipo
            # de `re.match` continua sendo Optional e o analisador tem razao em cobrar.
            referencia = linhas[fim]
            recuo = referencia[:len(referencia) - len(referencia.lstrip())]
            _insert_after(linhas, fim, [f"{recuo}{nova}" for nova in novas])

        return "\n".join(linhas)


# ------------------------------------------------------------------ deteccao


def load(nome: str, texto: str) -> ConfigFile:
    """Escolhe o formato pelo nome do arquivo + conteudo e devolve o documento lido."""
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    inicio = texto.lstrip()[:1]

    if ext == "json" or (inicio in ("{", "[") and ext not in ("ini", "cfg", "conf", "properties")):
        return JsonConfig(texto)
    if _CLASS_RE.search(texto) or (ext == "cfg" and _DZ_PAIR_RE.search(texto)):
        return DayzConfig(texto)
    return IniConfig(texto)
