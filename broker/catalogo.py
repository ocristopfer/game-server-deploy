"""Catalogo de jogos que o broker sabe criar.

Duas origens, um so tipo (`Jogo`):

- **curado**: `games/*.env` do repositorio. Voce revisou no git, entao pode trazer
  `PRE/POST_INSTALL_CMD`. E a mesma lista que o `deploy-game.ps1` usa - nao existe um
  segundo catalogo para manter em paralelo.
- **dinamico**: cadastrado pela API. E so dado: cada campo tem uma regex propria e nenhum
  vira comando. Campo que o broker nao conhece e recusado, senao `pre_install_cmd` entraria
  de contrabando.

O `.env` NUNCA passa por `source` aqui. Ele e lido por um parser proprio que nao expande
`$VAR`, `$(...)` nem crase: o que esta no arquivo e o texto, ponto.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .erros import Conflito, ErroDeValidacao, NaoEncontrado

ORIGEM_CURADO = "curado"
ORIGEM_DINAMICO = "dinamico"

# Receitas: lista FECHADA no codigo. Jogo dinamico escolhe daqui, nunca escreve shell.
RECEITAS = ("wine", "proton", "steamclient-sdk64")
RECEITAS_WINDOWS = ("wine", "proton")

# Portas que nunca podem ser expostas por jogo nenhum: painel, Proxmox, API REST e RCON
# (ver PORT_NOTES do palworld.env - o painel fala com eles por dentro do container).
PORTAS_PROIBIDAS = frozenset({22, 80, 443, 8006, 8080, 8212, 25575})

CHAVE_RE = re.compile(r"[a-z][a-z0-9-]{1,23}", re.ASCII)
NOME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}", re.ASCII)
_PORTA_RE = re.compile(r"(\d{1,5})/(tcp|udp)", re.ASCII)
_SCRIPT_RE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", re.ASCII)
_CAMINHO_RE = re.compile(r"/(opt/game|home/steam)(/[A-Za-z0-9._-]+)*", re.ASCII)
# Sem ; | & $ ` ( ) < > \ aspas e quebra de linha: o START_ARGS acaba numa linha de comando
# dentro do CT. {PORT} e {QUERY_PORT} sao os unicos marcadores: as chaves entram no
# charset, e `_args_de_start` recusa qualquer chave que sobre depois de tirar os dois.
_ARGS_RE = re.compile(r"[A-Za-z0-9 ._=:,/+@?{}-]{0,300}", re.ASCII)
_MARCADORES = ("{PORT}", "{QUERY_PORT}", "{EXTRA_PORT}")
_REGEX_TAMANHO_MAX = 200
# (a+)+ , (.*)* , (a|b*)+ : repeticao dentro de grupo que repete. O `re` do Python nao tem
# timeout, entao esse formato e recusado antes de existir. A busca so roda em texto de ate
# _REGEX_TAMANHO_MAX caracteres (checado antes), o que limita o custo do backtracking.
_REPETICAO_ANINHADA = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]")  # NOSONAR
_ATRIB_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$", re.ASCII)

PLAYER_SOURCES_DINAMICO = ("a2s", "log")
PLATAFORMAS = ("", "linux", "windows")


@dataclass(frozen=True)
class Porta:
    numero: int
    proto: str

    def __str__(self) -> str:
        return f"{self.numero}/{self.proto}"


@dataclass(frozen=True)
class Jogo:
    chave: str
    nome: str
    app_id: int
    plataforma: str
    portas: tuple[Porta, ...]
    porta_jogo: int
    porta_query: int
    memoria_mb: int
    cores: int
    disco_gb: int
    start_script: str
    start_args: str
    config_path: str
    config_files: tuple[str, ...]
    backup_paths: tuple[str, ...]
    player_source: str
    join_re: str
    leave_re: str
    log_path: str
    receitas: tuple[str, ...]
    deslocavel: bool
    origem: str
    criavel: bool
    motivo: str
    # Shell revisado por voce (so o catalogo curado tem). Nunca sai pela API.
    pre_install: str = ""
    post_install: str = ""
    # Terceira porta que o jogo aceita pelos argumentos ({EXTRA_PORT}): a "confiavel" do
    # Satisfactory (-ReliablePort), por exemplo. 0 = o jogo nao tem.
    porta_extra: int = 0

    @property
    def tem_hooks(self) -> bool:
        return bool(self.pre_install or self.post_install)

    def publico(self) -> dict:
        """O que a API mostra: nada de comando, nada de caminho de instalador."""
        return {
            "chave": self.chave, "nome": self.nome, "app_id": self.app_id,
            "portas": [str(p) for p in self.portas], "porta_jogo": self.porta_jogo,
            "porta_query": self.porta_query, "porta_extra": self.porta_extra,
            "memoria_mb": self.memoria_mb,
            "cores": self.cores, "disco_gb": self.disco_gb,
            "receitas": list(self.receitas), "deslocavel": self.deslocavel,
            "origem": self.origem, "criavel": self.criavel, "motivo": self.motivo,
        }

    def dados_dinamicos(self) -> dict:
        """Forma gravada em disco; `validar_dinamico` a aceita de volta."""
        return {
            "chave": self.chave, "nome": self.nome, "app_id": self.app_id,
            "plataforma": self.plataforma, "start_script": self.start_script,
            "start_args": self.start_args, "portas": [str(p) for p in self.portas],
            "porta_jogo": self.porta_jogo, "porta_query": self.porta_query,
            "porta_extra": self.porta_extra,
            "memoria_mb": self.memoria_mb, "cores": self.cores, "disco_gb": self.disco_gb,
            "config_path": self.config_path, "config_files": list(self.config_files),
            "backup_paths": list(self.backup_paths), "player_source": self.player_source,
            "join_re": self.join_re, "leave_re": self.leave_re, "log_path": self.log_path,
            "receitas": list(self.receitas), "deslocavel": self.deslocavel,
        }


# ----------------------------------------------------------------------------
# Leitura segura do .env (sem shell)
# ----------------------------------------------------------------------------

def ler_env(texto: str) -> dict[str, str]:
    """Le `CHAVE=valor` sem executar nada. Aspas simples/duplas podem abrir varias linhas."""
    linhas = texto.splitlines()
    saida: dict[str, str] = {}
    i = 0
    while i < len(linhas):
        m = _ATRIB_RE.match(linhas[i])
        i += 1
        if not m:
            continue
        chave, resto = m.group(1), m.group(2).lstrip()
        if resto[:1] in ("'", '"'):
            valor, i = _valor_com_aspas(chave, resto, linhas, i)
        else:
            valor = re.split(r"\s#", resto, maxsplit=1)[0].strip()
        saida[chave] = valor
    return saida


def _valor_com_aspas(chave: str, resto: str, linhas: list[str], inicio: int) -> tuple[str, int]:
    aspas = resto[0]
    corpo = "\n".join([resto[1:], *linhas[inicio:]])
    pedacos: list[str] = []
    k = 0
    while k < len(corpo):
        c = corpo[k]
        if aspas == '"' and c == "\\" and k + 1 < len(corpo):
            prox = corpo[k + 1]
            pedacos.append(prox if prox in '"\\$`' else c + prox)
            k += 2
        elif c == aspas and aspas == "'" and corpo.startswith("\\''", k + 1):
            # 'abc'\''def' : o jeito do shell de escrever um apostrofo dentro de aspas simples.
            pedacos.append("'")
            k += 4
        elif c == aspas:
            return "".join(pedacos), inicio + corpo[:k].count("\n")
        else:
            pedacos.append(c)
            k += 1
    raise ValueError(f"{chave}: aspas sem fechar")


# ----------------------------------------------------------------------------
# Jogo curado (games/*.env)
# ----------------------------------------------------------------------------

def _porta(texto: str) -> Porta:
    m = _PORTA_RE.fullmatch(texto.strip())
    if not m or not 1 <= int(m.group(1)) <= 65535:
        raise ValueError(f"porta invalida: {texto!r}")
    return Porta(int(m.group(1)), m.group(2))


def _partes(valor: str, separador: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in re.split(separador, valor) if p.strip())


def _inteiro_env(dados: dict[str, str], chave: str, padrao: int) -> int:
    bruto = dados.get(chave, "").strip()
    return int(bruto) if bruto else padrao


def problema_de_deslocavel(portas: tuple[Porta, ...], porta_jogo: int, porta_query: int,
                           start_args: str, porta_extra: int = 0) -> str:
    """Um jogo so anda de porta se o broker consegue AVISAR o jogo de todas elas.

    O broker entrega ao jogo ate tres portas ({PORT}, {QUERY_PORT} e {EXTRA_PORT}). Uma
    quarta (DayZ tem 2303/2304) ficaria aberta no firewall num numero que o jogo nao escuta, e
    o cliente conectaria em vazio. Sem o marcador no START_ARGS o jogo ignora o numero sorteado.
    """
    avisaveis = {porta_jogo, porta_query, porta_extra} - {0}
    if any(p.numero not in avisaveis for p in portas):
        return ("so aceita as portas do jogo, da query e uma extra "
                "(o broker nao avisa mais portas ao jogo)")
    if "{PORT}" not in start_args:
        return "start_args precisa de {PORT}: e por ele que o jogo recebe a porta sorteada"
    if porta_query and "{QUERY_PORT}" not in start_args:
        return "start_args precisa de {QUERY_PORT}: e por ele que o jogo recebe a porta de consulta"
    if porta_extra and "{EXTRA_PORT}" not in start_args:
        return "start_args precisa de {EXTRA_PORT}: e por ele que o jogo recebe a porta extra"
    return ""


def problema_de_extra(start_args: str, porta_extra: int) -> str:
    """{EXTRA_PORT} sem porta extra viraria "0" na linha de comando do jogo."""
    if "{EXTRA_PORT}" in start_args and not porta_extra:
        return "start_args usa {EXTRA_PORT}, mas o jogo nao tem porta extra (EXTRA_PORT / porta_extra)"
    return ""


def _motivo_de_nao_criar(dados: dict[str, str], app_id: int, portas: tuple[Porta, ...]) -> str:
    if dados.get("PROVISION_SCRIPT"):
        return "instalador proprio (nao e Steam); use o deploy-game.ps1"
    if dados.get("STEAM_ANONYMOUS", "1") == "0":
        return "exige conta Steam; use o deploy-game.ps1"
    if app_id <= 0:
        return "sem STEAM_APP_ID"
    if not portas:
        return "sem portas em GAME_PORTS"
    return ""


def jogo_de_env(nome_do_arquivo: str, dados: dict[str, str]) -> Jogo:
    chave = dados.get("GAME_KEY", nome_do_arquivo)
    if not CHAVE_RE.fullmatch(chave):
        raise ValueError(f"GAME_KEY invalida: {chave!r}")
    app_id = _inteiro_env(dados, "STEAM_APP_ID", 0)
    portas = tuple(_porta(p) for p in _partes(dados.get("GAME_PORTS", ""), r"\s+"))
    runtime = dados.get("WINDOWS_RUNTIME", "")
    motivo = _motivo_de_nao_criar(dados, app_id, portas)
    deslocavel = dados.get("PORTS_SHIFTABLE", "0") == "1"
    porta_extra = _inteiro_env(dados, "EXTRA_PORT", 0)
    problema = problema_de_extra(dados.get("START_ARGS", ""), porta_extra)
    if problema:
        raise ValueError(problema)
    if deslocavel:
        problema = problema_de_deslocavel(portas, _inteiro_env(dados, "GAME_PORT", 0),
                                          _inteiro_env(dados, "QUERY_PORT", 0), dados.get("START_ARGS", ""),
                                          porta_extra)
        if problema:
            raise ValueError(f"PORTS_SHIFTABLE=1 invalido: {problema}")
    return Jogo(
        chave=chave, nome=dados.get("GAME_DISPLAY_NAME", chave), app_id=app_id,
        plataforma=dados.get("STEAM_PLATFORM", ""), portas=portas,
        porta_jogo=_inteiro_env(dados, "GAME_PORT", 0),
        porta_query=_inteiro_env(dados, "QUERY_PORT", 0), porta_extra=porta_extra,
        memoria_mb=_inteiro_env(dados, "RECOMMENDED_MEMORY", 4096),
        cores=_inteiro_env(dados, "RECOMMENDED_CORES", 2),
        disco_gb=_inteiro_env(dados, "RECOMMENDED_DISK_GB", 20),
        start_script=dados.get("START_SCRIPT", ""), start_args=dados.get("START_ARGS", ""),
        config_path=dados.get("CONFIG_PATH", ""),
        config_files=_partes(dados.get("CONFIG_FILES", ""), ","),
        backup_paths=_partes(dados.get("BACKUP_PATHS", ""), ","),
        player_source=dados.get("PLAYER_SOURCE", "log"),
        join_re=dados.get("JOIN_RE", ""), leave_re=dados.get("LEAVE_RE", ""),
        log_path=dados.get("LOG_PATH", ""),
        receitas=(runtime,) if runtime in RECEITAS_WINDOWS else (),
        deslocavel=deslocavel,
        origem=ORIGEM_CURADO, criavel=not motivo, motivo=motivo,
        pre_install=dados.get("PRE_INSTALL_CMD", ""),
        post_install=dados.get("POST_INSTALL_CMD", ""),
    )


def carregar_curado(diretorio: Path) -> tuple[dict[str, Jogo], list[str]]:
    """Le `games/*.env` (menos os que comecam com `_`). Arquivo ruim vira erro, nao excecao."""
    jogos: dict[str, Jogo] = {}
    erros: list[str] = []
    for arquivo in sorted(Path(diretorio).glob("*.env")):
        if arquivo.name.startswith("_"):
            continue
        try:
            jogo = jogo_de_env(arquivo.stem, ler_env(arquivo.read_text(encoding="utf-8")))
        except (ValueError, OSError) as erro:
            erros.append(f"{arquivo.name}: {erro}")
            continue
        jogos[jogo.chave] = jogo
    return jogos, erros


# ----------------------------------------------------------------------------
# Jogo dinamico (API)
# ----------------------------------------------------------------------------

_CAMPOS_DINAMICOS = frozenset({
    "chave", "nome", "app_id", "plataforma", "start_script", "start_args", "portas",
    "porta_jogo", "porta_query", "porta_extra", "memoria_mb", "cores", "disco_gb", "config_path",
    "config_files", "backup_paths", "player_source", "join_re", "leave_re", "log_path",
    "receitas", "deslocavel",
})
_OBRIGATORIOS = ("chave", "nome", "app_id", "portas", "porta_jogo")


def _inteiro(dados: dict, campo: str, minimo: int, maximo: int, padrao: int | None = None) -> int:
    if campo not in dados:
        if padrao is None:
            raise ErroDeValidacao(campo, "obrigatorio")
        return padrao
    valor = dados[campo]
    # bool e subclasse de int em Python: `true` nao pode passar por 1.
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroDeValidacao(campo, "deve ser um numero inteiro")
    if not minimo <= valor <= maximo:
        raise ErroDeValidacao(campo, f"deve estar entre {minimo} e {maximo}")
    return valor


def _texto(dados: dict, campo: str, regex: re.Pattern[str], padrao: str = "",
           obrigatorio: bool = False) -> str:
    valor = dados.get(campo, padrao)
    if not isinstance(valor, str):
        raise ErroDeValidacao(campo, "deve ser texto")
    # Vazio so vale para campo opcional: chave/nome vazios passariam por "ausente".
    if (valor or obrigatorio) and not regex.fullmatch(valor):
        raise ErroDeValidacao(campo, "formato invalido")
    return valor


def _lista_de_textos(dados: dict, campo: str, maximo: int) -> list[str]:
    valor = dados.get(campo, [])
    if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor):
        raise ErroDeValidacao(campo, "deve ser uma lista de textos")
    if len(valor) > maximo:
        raise ErroDeValidacao(campo, f"no maximo {maximo} itens")
    return valor


def _sem_dois_pontos(caminho: str, campo: str) -> str:
    if ".." in caminho.split("/"):
        raise ErroDeValidacao(campo, "'..' nao e permitido")
    return caminho


def _caminhos(dados: dict, campo: str, maximo: int) -> tuple[str, ...]:
    itens = _lista_de_textos(dados, campo, maximo)
    for item in itens:
        if not _CAMINHO_RE.fullmatch(item):
            raise ErroDeValidacao(campo, "so caminhos absolutos sob /opt/game ou /home/steam")
        _sem_dois_pontos(item, campo)
    return tuple(itens)


def _portas(dados: dict) -> tuple[Porta, ...]:
    itens = _lista_de_textos(dados, "portas", 8)
    portas: list[Porta] = []
    for item in itens:
        try:
            porta = _porta(item)
        except ValueError as erro:
            raise ErroDeValidacao("portas", str(erro)) from None
        if porta.numero < 1024:
            raise ErroDeValidacao("portas", f"{porta}: portas abaixo de 1024 nao sao permitidas")
        if porta.numero in PORTAS_PROIBIDAS:
            raise ErroDeValidacao("portas", f"{porta}: porta reservada (painel, Proxmox, REST ou RCON)")
        portas.append(porta)
    if not portas or len(set(portas)) != len(portas):
        raise ErroDeValidacao("portas", "informe ao menos uma porta, sem repetir")
    return tuple(portas)


def _regex_do_log(dados: dict, campo: str) -> str:
    padrao = dados.get(campo, "")
    if not isinstance(padrao, str):
        raise ErroDeValidacao(campo, "deve ser texto")
    if not padrao:
        return ""
    if len(padrao) > _REGEX_TAMANHO_MAX:
        raise ErroDeValidacao(campo, f"no maximo {_REGEX_TAMANHO_MAX} caracteres")
    if _REPETICAO_ANINHADA.search(padrao):
        raise ErroDeValidacao(campo, "repeticao dentro de repeticao (risco de travar o painel)")
    try:
        re.compile(padrao)
    except re.error as erro:
        raise ErroDeValidacao(campo, f"regex invalida: {erro}") from None
    return padrao


def _args_de_start(dados: dict) -> str:
    args = _texto(dados, "start_args", _ARGS_RE)
    sobra = args
    for marcador in _MARCADORES:
        sobra = sobra.replace(marcador, "")
    if "{" in sobra or "}" in sobra:
        raise ErroDeValidacao("start_args", "so {PORT}, {QUERY_PORT} e {EXTRA_PORT} sao marcadores validos")
    return args


def _script_de_start(dados: dict) -> str:
    script = _texto(dados, "start_script", _SCRIPT_RE)
    return _sem_dois_pontos(script, "start_script")


def _receitas(dados: dict, plataforma: str) -> tuple[str, ...]:
    itens = _lista_de_textos(dados, "receitas", len(RECEITAS))
    desconhecida = next((r for r in itens if r not in RECEITAS), None)
    if desconhecida is not None:
        raise ErroDeValidacao("receitas", f"receita desconhecida: {desconhecida!r}")
    if plataforma == "windows" and not set(itens) & set(RECEITAS_WINDOWS):
        raise ErroDeValidacao("receitas", "jogo de Windows precisa da receita 'wine' ou 'proton'")
    return tuple(dict.fromkeys(itens))


def validar_dinamico(dados: object) -> Jogo:
    """Valida um jogo vindo da API. Qualquer duvida e recusa: aqui nada vira comando."""
    if not isinstance(dados, dict):
        raise ErroDeValidacao("corpo", "esperado um objeto JSON")
    desconhecido = sorted(set(dados) - _CAMPOS_DINAMICOS)
    if desconhecido:
        raise ErroDeValidacao(desconhecido[0], "campo desconhecido (a API so aceita dados, nunca comandos)")
    faltando = [c for c in _OBRIGATORIOS if c not in dados]
    if faltando:
        raise ErroDeValidacao(faltando[0], "obrigatorio")

    portas = _portas(dados)
    porta_jogo = _inteiro(dados, "porta_jogo", 1024, 65535)
    if porta_jogo not in {p.numero for p in portas}:
        raise ErroDeValidacao("porta_jogo", "deve estar entre as portas expostas")
    porta_query = _inteiro(dados, "porta_query", 0, 65535, padrao=0)
    if porta_query and porta_query not in {p.numero for p in portas}:
        raise ErroDeValidacao("porta_query", "deve estar entre as portas expostas (ou 0)")
    porta_extra = _inteiro(dados, "porta_extra", 0, 65535, padrao=0)
    if porta_extra and porta_extra not in {p.numero for p in portas}:
        raise ErroDeValidacao("porta_extra", "deve estar entre as portas expostas (ou 0)")
    if porta_extra and porta_extra in (porta_jogo, porta_query):
        raise ErroDeValidacao("porta_extra", "deve ser diferente da porta do jogo e da de consulta")

    plataforma = _texto(dados, "plataforma", re.compile(r"linux|windows"))
    fonte = dados.get("player_source", "log")
    if fonte not in PLAYER_SOURCES_DINAMICO:
        raise ErroDeValidacao("player_source", f"use {' ou '.join(PLAYER_SOURCES_DINAMICO)}")
    deslocavel = dados.get("deslocavel", False)
    if not isinstance(deslocavel, bool):
        raise ErroDeValidacao("deslocavel", "deve ser verdadeiro ou falso")
    start_args = _args_de_start(dados)
    problema = problema_de_extra(start_args, porta_extra)
    if problema:
        raise ErroDeValidacao("start_args", problema)
    if deslocavel:
        problema = problema_de_deslocavel(portas, porta_jogo, porta_query, start_args, porta_extra)
        if problema:
            raise ErroDeValidacao("deslocavel", problema)

    return Jogo(
        chave=_texto(dados, "chave", CHAVE_RE, obrigatorio=True),
        nome=_texto(dados, "nome", NOME_RE, obrigatorio=True),
        app_id=_inteiro(dados, "app_id", 1, 2**31 - 1),
        plataforma=plataforma, portas=portas, porta_jogo=porta_jogo, porta_query=porta_query,
        porta_extra=porta_extra,
        memoria_mb=_inteiro(dados, "memoria_mb", 512, 65536, padrao=4096),
        cores=_inteiro(dados, "cores", 1, 16, padrao=2),
        disco_gb=_inteiro(dados, "disco_gb", 4, 500, padrao=20),
        start_script=_script_de_start(dados), start_args=start_args,
        config_path=_caminho_unico(dados, "config_path"),
        config_files=_caminhos(dados, "config_files", 8),
        backup_paths=_caminhos(dados, "backup_paths", 8),
        player_source=fonte,
        join_re=_regex_do_log(dados, "join_re"), leave_re=_regex_do_log(dados, "leave_re"),
        log_path=_caminho_unico(dados, "log_path"),
        receitas=_receitas(dados, plataforma), deslocavel=deslocavel,
        origem=ORIGEM_DINAMICO, criavel=True, motivo="",
    )


def _caminho_unico(dados: dict, campo: str) -> str:
    valor = _texto(dados, campo, _CAMINHO_RE)
    return _sem_dois_pontos(valor, campo)


# ----------------------------------------------------------------------------
# Catalogo (curado + dinamico)
# ----------------------------------------------------------------------------

class Catalogo:
    def __init__(self, dir_curado: Path, dir_dinamico: Path):
        self._dir_curado = Path(dir_curado)
        self._dir_dinamico = Path(dir_dinamico)
        self._trava = threading.Lock()
        self._jogos: dict[str, Jogo] = {}
        self.erros: list[str] = []
        self.recarregar()

    def recarregar(self) -> None:
        jogos, erros = carregar_curado(self._dir_curado)
        self._dir_dinamico.mkdir(parents=True, exist_ok=True)
        for arquivo in sorted(self._dir_dinamico.glob("*.json")):
            try:
                # Revalida ao ler: arquivo adulterado em disco nao vira jogo criavel.
                jogo = validar_dinamico(json.loads(arquivo.read_text(encoding="utf-8")))
            except (ValueError, OSError, ErroDeValidacao) as erro:
                erros.append(f"{arquivo.name}: {erro}")
                continue
            if jogo.chave in jogos or arquivo.stem != jogo.chave:
                erros.append(f"{arquivo.name}: chave repetida ou diferente do nome do arquivo")
                continue
            jogos[jogo.chave] = jogo
        with self._trava:
            self._jogos, self.erros = jogos, erros

    def listar(self) -> list[Jogo]:
        with self._trava:
            return sorted(self._jogos.values(), key=lambda j: j.chave)

    def obter(self, chave: str) -> Jogo:
        with self._trava:
            jogo = self._jogos.get(chave)
        if jogo is None:
            raise NaoEncontrado(f"jogo desconhecido: {chave!r}")
        return jogo

    def adicionar_dinamico(self, dados: object) -> Jogo:
        jogo = validar_dinamico(dados)
        with self._trava:
            if jogo.chave in self._jogos:
                raise Conflito(f"ja existe um jogo com a chave {jogo.chave!r}")
            self._gravar(jogo)
            self._jogos[jogo.chave] = jogo
        return jogo

    def _gravar(self, jogo: Jogo) -> None:
        self._dir_dinamico.mkdir(parents=True, exist_ok=True)
        destino = self._dir_dinamico / f"{jogo.chave}.json"
        # Escreve num temporario e troca: um corte de luz nao deixa JSON pela metade.
        fd, temporario = tempfile.mkstemp(dir=self._dir_dinamico, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as saida:
                json.dump(jogo.dados_dinamicos(), saida, ensure_ascii=True, indent=2)
            os.replace(temporario, destino)
        except OSError:
            Path(temporario).unlink(missing_ok=True)
            raise
