"""Quem esta jogando: de onde sai o numero, e o que da para fazer com essa gente.

Tres fontes possiveis (consulta A2S, API HTTP do proprio jogo, ou o log do servico) e
as acoes que a mesma API aceita (expulsar, banir, avisar) — mesma credencial, mesma
porta, mesmo token com prazo.

Mora em `services/` e nao em `runtime/` por causa do BANCO: o token da API vence, e
renova-lo significa gravar o novo no cadastro do servidor. `runtime/` so fala SSH e
rede, sem persistencia nenhuma — por isso o que depende do banco parava em `app.py`
ate esta camada existir.

Tudo o que este modulo precisa do resto do painel entra por `PlayerDeps` (SSH, banco,
leitura de log, consulta A2S). Sem import de `app.py`: seria circular, e e o que
permite testar a contagem inteira sem Flask, sem SSH e sem container.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple, TypedDict

from gamepanel.runtime import http_probe, log_probe
from gamepanel.runtime.a2s import AuthError, QueryError
from gamepanel.runtime.ssh import RemoteError, ServerLike
from gamepanel.services import parallel

# De onde a contagem de jogadores pode sair. 'none' e o desligado explicito — diferente
# do vazio, que significa "cadastro antigo, deduza pela porta de consulta".
PLAYER_SOURCES = ("a2s", "http", "log", "none")

# Colunas que descrevem a chamada HTTP; viajam juntas entre formulario, assistente e banco.
HTTP_FIELDS = ("http_url", "http_auth", "http_body", "http_list_path", "http_count_path",
               "http_login_url", "http_login_body", "http_token_path")

PLAYER_MSG_MAX = 200
# O valor e chave de catalogo (`gamepanel.i18n`), nao o texto da tela.
PLAYER_ACTION_LABELS = {
    "announce": "player_action.announce",
    "kick": "player_action.kick",
    "ban": "player_action.ban",
}

# Os marcadores do catalogo, como constantes: sao a interface entre a tabela abaixo e
# o `_preenche`, e escreve-los a mao em cada linha e como um deles vira "{mensagen}"
# num jogo so, sem ninguem notar ate alguem tentar expulsar alguem.
MARCA_BASE = "{base}"
MARCA_JOGADOR = "{jogador}"
MARCA_MENSAGEM = "{mensagem}"

class EntradaDeAcoes(TypedDict):
    """Uma linha do catalogo de acoes.

    TypedDict, e nao dict solto: sem ele o `url` vira `object` para quem le tipo, e o
    `.match()` logo abaixo passa a ser um erro que so aparece em tempo de execucao.
    """

    nome: str
    url: re.Pattern[str]
    # acao -> (rota, corpo) com os marcadores por preencher.
    acoes: dict[str, tuple[str, dict[str, str]]]


# Expulsar, banir e avisar saem pela MESMA API que ja conta os jogadores — outra rota,
# mesma credencial. Nao ha padrao entre os jogos, entao vai um catalogo, reconhecido pela
# URL de contagem que o servidor ja tem cadastrada.
#
# Dos jogos que este repo instala, so o Palworld publica essas acoes (o Satisfactory nao
# tem kick na API). Jogo novo entra como mais uma entrada aqui, sem tocar no resto.
API_ACOES: tuple[EntradaDeAcoes, ...] = (
    {
        "nome": "Palworld (REST)",
        "url": re.compile(r"^(?P<base>https?://[^/\s]+/v1/api)/players/?$", re.I),
        # acao -> (rota, corpo).
        "acoes": {
            "announce": (f"{MARCA_BASE}/announce", {"message": MARCA_MENSAGEM}),
            "kick": (f"{MARCA_BASE}/kick",
                     {"userid": MARCA_JOGADOR, "message": MARCA_MENSAGEM}),
            "ban": (f"{MARCA_BASE}/ban",
                    {"userid": MARCA_JOGADOR, "message": MARCA_MENSAGEM}),
        },
    },
)

# (server, url, auth, corpo, exigir_json) -> dado ja interpretado.
HttpJson = Callable[..., Any]
# () -> conexao propria (a contagem roda fora do request, entao nao serve a do Flask).
Connect = Callable[[], sqlite3.Connection]
# (server, limite) -> linhas do log do servico.
ReadLogLines = Callable[..., list[str]]
# (host, porta) -> resposta da consulta A2S.
QueryPlayers = Callable[[str, int], dict]


class PlayerDeps(NamedTuple):
    """O que a contagem precisa do resto do painel.

    Entra por parametro, e nao por import, pelos dois motivos de sempre: `app.py`
    importa este modulo (o contrario seria circular) e o teste troca qualquer uma
    destas pecas por uma falsa sem precisar de SSH nem de container.
    """

    http_json: HttpJson
    connect: Connect
    read_log_lines: ReadLogLines
    query_players: QueryPlayers
    players_ttl: float


def _valor_guardado(server: ServerLike, coluna: str) -> str:
    try:
        return (server[coluna] or "").strip()
    except (IndexError, KeyError):
        # Linha vinda de um SELECT sem as colunas novas (ou banco antes da migracao).
        return ""


def player_source(server: ServerLike) -> str:
    """Como contar os jogadores deste servidor: 'a2s', 'http', 'log' ou '' (desligado)."""
    escolhido = (server["player_source"] or "").strip()
    if escolhido in PLAYER_SOURCES:
        return "" if escolhido == "none" else escolhido
    # Cadastro antigo, anterior ao campo: porta de consulta preenchida = A2S.
    return "a2s" if int(server["query_port"] or 0) else ""


# ------------------------------------------------- contagem pela API do jogo

def _tem_login(server: ServerLike) -> bool:
    """True quando o servidor esta configurado para obter o token sozinho."""
    return bool(_valor_guardado(server, "http_login_url")
                and _valor_guardado(server, "http_token_path"))


def http_login(deps: PlayerDeps, server: ServerLike) -> str:
    """Troca a credencial por um token e guarda no banco. Devolve o token."""
    url = _valor_guardado(server, "http_login_url")
    caminho = _valor_guardado(server, "http_token_path")
    if not url or not caminho:
        raise QueryError("login automatico incompleto (falta URL de login ou caminho do token)")

    # O login vai SEM Authorization: e ele quem produz a credencial.
    dados = deps.http_json(server, url, "", _valor_guardado(server, "http_login_body"))
    token = http_probe._json_walk(dados, caminho)
    if not isinstance(token, str) or not token.strip():
        raise QueryError(f"o login respondeu, mas nao achei um token em '{caminho}'")
    token = token.strip()
    # Conexao propria, e nao a do Flask: a contagem tambem roda fora de request
    # (cache/pollagem em thread). Aqui a escrita e uma linha so.
    con = deps.connect()
    try:
        with con:
            con.execute("UPDATE servers SET http_token = ? WHERE id = ?",
                        (token, int(server["id"])))
    finally:
        con.close()
    return token


def chama_api_do_jogo(deps: PlayerDeps, server: ServerLike, url: str, corpo: str = "",
                      exigir_json: bool = True) -> Any:
    """Chama a API do jogo com a credencial cadastrada, renovando o token se ele venceu.

    Mora aqui, e nao dentro do players_from_http, porque a contagem deixou de ser a unica
    coisa que fala com essa API: expulsar, banir e avisar usam a mesma porta, a mesma
    senha e o mesmo token com prazo.
    """
    com_login = _tem_login(server)
    if com_login:
        token = _valor_guardado(server, "http_token")
        # Sem token guardado (primeira vez, ou depois de trocar a senha) ja entra
        # pelo login em vez de gastar uma chamada que vai falhar.
        auth = f"bearer:{token}" if token else f"bearer:{http_login(deps, server)}"
    else:
        auth = server["http_auth"]

    try:
        return deps.http_json(server, url, auth, corpo, exigir_json)
    except AuthError:
        if not com_login:
            raise
        # Token expirado ou revogado: renova uma vez e repete. Se falhar de novo,
        # o erro sobe - ai o problema e a credencial, nao o prazo do token.
        return deps.http_json(server, url, f"bearer:{http_login(deps, server)}", corpo, exigir_json)


def players_from_http(deps: PlayerDeps, server: ServerLike) -> dict:
    if not (server["http_url"] or "").strip():
        raise QueryError("informe a URL da API do jogo")
    dados = chama_api_do_jogo(deps, server, server["http_url"], server["http_body"])
    return http_probe.read_players_json(dados, server["http_list_path"], server["http_count_path"])


# ----------------------------------------------------- contagem pelo log

def players_from_log(deps: PlayerDeps, server: ServerLike) -> dict:
    entrar = log_probe.compile_pattern(server["join_re"], "entrada")
    if not entrar:
        raise QueryError("informe o padrao da linha de entrada de jogador")
    sair = log_probe.compile_pattern(server["leave_re"], "saida")
    try:
        linhas = deps.read_log_lines(server)
    except RemoteError as exc:
        raise QueryError(str(exc)) from exc

    resultado = log_probe.apply_log_events(linhas, entrar, sair)
    resultado.update({"error": "", "max_players": None, "server_name": "", "map": ""})
    return resultado


# ------------------------------------------- acoes sobre quem esta jogando

def api_de_acoes(server: ServerLike) -> dict[str, Any] | None:
    """A API deste servidor aceita acoes? Devolve a entrada do catalogo, ou None."""
    if player_source(server) != "http":
        return None
    url = (server["http_url"] or "").strip()
    for entrada in API_ACOES:
        casa = entrada["url"].match(url)
        if casa:
            achado: dict[str, Any] = {**entrada, "base": casa.group("base")}
            return achado
    return None


def acoes_de_jogador(server: ServerLike) -> list[str]:
    """Quais acoes a tela pode oferecer neste servidor."""
    api = api_de_acoes(server)
    return sorted(api["acoes"]) if api else []


def _preenche(molde: str, base: str, jogador: str, mensagem: str) -> str:
    """Troca os marcadores do catalogo.

    De proposito NAO usa str.format: a mensagem vem de quem esta digitando, e uma chave
    solta ('{') estouraria o format — ou pior, viraria um caminho para dentro do objeto.
    """
    return (molde.replace(MARCA_BASE, base)
                 .replace(MARCA_JOGADOR, jogador)
                 .replace(MARCA_MENSAGEM, mensagem))


def acao_de_jogador(deps: PlayerDeps, server: ServerLike, acao: str, jogador: str,
                    mensagem: str) -> str:
    """Executa a acao na API do jogo. Devolve a frase que vai para a tela."""
    api = api_de_acoes(server)
    if not api or acao not in api["acoes"]:
        raise QueryError("este servidor nao publica essa acao")
    if acao == "announce":
        if not mensagem:
            raise QueryError("escreva o aviso")
    elif not jogador:
        raise QueryError("nao sei quem expulsar: a API nao publicou o identificador"
                         " deste jogador")

    rota, molde = api["acoes"][acao]
    corpo = {chave: _preenche(valor, api["base"], jogador, mensagem)
             for chave, valor in molde.items()}
    # exigir_json=False: estas rotas respondem 200 com o corpo vazio.
    chama_api_do_jogo(deps, server, _preenche(rota, api["base"], jogador, mensagem),
                      json.dumps(corpo), exigir_json=False)
    return PLAYER_ACTION_LABELS.get(acao, acao)


# ------------------------------------------------------ a contagem em si

# Cache de processo: varias telas e o monitor perguntam a mesma coisa em sequencia, e
# cada consulta custa uma ida ao jogo (ou ao log, por SSH). `app.py` publica este mesmo
# objeto pelo nome antigo, e a fixture `banco` dos testes o limpa entre casos.
_players_cache: dict[int, tuple[float, dict]] = {}
_players_lock = threading.Lock()


def invalidate(server_id: int) -> None:
    """Esquece a contagem guardada — usar depois de mudar COMO o servidor conta."""
    with _players_lock:
        _players_cache.pop(server_id, None)


def _conta_agora(deps: PlayerDeps, server: ServerLike, origem: str) -> dict:
    if origem == "log":
        return players_from_log(deps, server)
    if origem == "http":
        return players_from_http(deps, server)
    porta = int(server["query_port"] or 0)
    if not porta:
        raise QueryError("informe a porta de consulta (query Steam) do servidor")
    return deps.query_players(server["host"], porta)


def server_players(deps: PlayerDeps, server: ServerLike, force: bool = False) -> dict:
    origem = player_source(server)
    if not origem:
        return {"configured": False, "error": "", "players": None, "list": [], "source": ""}

    key = int(server["id"])
    agora = time.monotonic()
    if not force:
        with _players_lock:
            cached = _players_cache.get(key)
        if cached and agora - cached[0] < deps.players_ttl:
            return cached[1]

    try:
        data = _conta_agora(deps, server, origem)
        data["configured"] = True
    except QueryError as exc:
        data = {"configured": True, "error": str(exc), "players": None, "list": []}
    data["source"] = origem

    with _players_lock:
        _players_cache[key] = (agora, data)
    return data


def all_players(conta_um: Callable[[ServerLike], dict], servers: Sequence[ServerLike],
                join_timeout: float, msg_timeout: str) -> dict[int, dict]:
    """Consulta todos em paralelo: sao 3s de espera cada quando um esta fora do ar.

    `conta_um` e recebido pronto (e nao montado aqui a partir de `deps`) porque quem
    chama e `app.py`, e la esse nome pode estar trocado por um falso no teste — montar
    a chamada aqui dentro passaria por cima da troca, em silencio.
    """
    return parallel.por_servidor(
        conta_um, servers, join_timeout,
        {"configured": True, "error": msg_timeout, "players": None, "list": [], "source": ""},
    )
