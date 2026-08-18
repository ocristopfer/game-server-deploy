#!/usr/bin/env python3
"""Painel administrativo dos servidores de jogos.

Roda num container proprio e fala SSH *direto* com cada container de jogo — o host
Proxmox nao entra no caminho, o painel nao tem acesso a ele nem conhece `pct`.

Cada servidor cadastrado e um destino SSH (host/porta/usuario). Para o painel alcancar
um container, aquele container precisa ter sshd e a chave publica do painel autorizada
(veja a pagina "Acesso SSH" do painel).

Dependencias: python3-flask (apt). Hash de senha e sessao usam apenas a stdlib.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import socket
import sqlite3
import struct
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from functools import wraps

# O terminal interativo depende de PTY (so existe em POSIX). Em outros sistemas o
# resto do painel continua funcionando e a tela do terminal responde 503.
try:
    import fcntl
    import pty
    import signal
    import termios

    HAVE_PTY = True
except ImportError:  # pragma: no cover - Windows
    HAVE_PTY = False

import gameconf
import gamefields
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)

# ---------------------------------------------------------------- configuracao

DB_PATH = os.environ.get("GAMEPANEL_DB", "/var/lib/gamepanel/panel.db")
SECRET_FILE = os.environ.get("GAMEPANEL_SECRET_FILE", "/etc/gamepanel/secret_key")
SSH_KEY = os.environ.get("GAMEPANEL_SSH_KEY", "/etc/gamepanel/id_ed25519")
# Gravavel: as host keys dos containers sao aprendidas no primeiro acesso (accept-new).
KNOWN_HOSTS = os.environ.get("GAMEPANEL_KNOWN_HOSTS", "/var/lib/gamepanel/known_hosts")

# Comandos rapidos (status, logs) x comandos longos (update baixa o jogo inteiro).
QUICK_TIMEOUT = 20
JOB_TIMEOUT = int(os.environ.get("GAMEPANEL_JOB_TIMEOUT", "5400"))
STATUS_TTL = 8.0
# Medidores de CPU/memoria/disco/rede: cada leitura custa uma ida de SSH de ~1s.
METRICS_TTL = float(os.environ.get("GAMEPANEL_METRICS_TTL", "4"))

# Console web: executa comandos como root DENTRO do container de jogo escolhido.
# E a funcionalidade mais poderosa do painel — desligue com GAMEPANEL_ALLOW_SHELL=0.
ALLOW_SHELL = os.environ.get("GAMEPANEL_ALLOW_SHELL", "1") == "1"
SHELL_TIMEOUT = int(os.environ.get("GAMEPANEL_SHELL_TIMEOUT", "600"))
SHELL_MAX_LEN = 4000

# Terminal interativo: sessao SSH viva com PTY, teclado ligado no shell do container.
# Herda o ALLOW_SHELL (e o mesmo poder do console, so que interativo).
TERM_MAX_SESSIONS = int(os.environ.get("GAMEPANEL_TERM_MAX", "4"))
TERM_IDLE_TIMEOUT = int(os.environ.get("GAMEPANEL_TERM_IDLE", "900"))
TERM_BUFFER_BYTES = 512 * 1024
TERM_POLL_WAIT = 20.0  # long-poll: segura a resposta ate chegar saida nova

# Editor de arquivos: le/grava arquivos de configuracao do jogo pelo mesmo SSH.
ALLOW_FILES = os.environ.get("GAMEPANEL_ALLOW_FILES", "1") == "1"
# Limite para EDITAR (o arquivo inteiro vai para um textarea e volta num POST).
FILE_MAX_BYTES = int(os.environ.get("GAMEPANEL_FILE_MAX", str(4 * 1024 * 1024)))
# Acima do limite de edicao o painel ainda mostra o fim do arquivo, so para leitura.
FILE_PREVIEW_BYTES = int(os.environ.get("GAMEPANEL_FILE_PREVIEW", str(256 * 1024)))
# Download nao passa por memoria (vai em streaming), entao o teto e bem maior.
# 0 = sem limite.
FILE_DOWNLOAD_MAX = int(os.environ.get("GAMEPANEL_FILE_DOWNLOAD_MAX", str(2 * 1024 * 1024 * 1024)))
DOWNLOAD_CHUNK = 256 * 1024
# Teto do corpo de um request: o arquivo editado sobe percent-encoded (ate 3x) + folga.
REQUEST_LIMIT = max(4 * 1024 * 1024, FILE_MAX_BYTES * 4 + 65536)
# Raizes onde o navegador de arquivos pode entrar. "/" = sem restricao.
FILE_ROOTS = tuple(
    p for p in os.environ.get("GAMEPANEL_FILE_ROOTS", "/").split(",") if p.strip()
)
FILE_DEFAULT_PATH = os.environ.get("GAMEPANEL_FILE_DEFAULT", "/opt/game")
FILE_LIST_MAX = 800
# Padroes usados pelo botao "procurar arquivos de config".
CONFIG_GLOBS = ("*.ini", "*.cfg", "*.conf", "*.json", "*.yaml", "*.yml", "*.properties", "*.txt")
# Quantos arquivos de configuracao um servidor pode ter registrados para a tela "Config".
CONFIG_FILES_MAX = 8
# Teto de campos no formulario da tela "Config": acima disso o arquivo quase certamente
# nao e configuracao (um log casa com "chave=valor" em varias linhas).
CONFIG_SETTINGS_MAX = 600

SQL_SERVER_BY_ID = "SELECT * FROM servers WHERE id = ?"
SQL_ALL_SERVERS = "SELECT * FROM servers ORDER BY name"
TPL_ERROR = "error.html"
TPL_LOGIN = "login.html"
MSG_TIMEOUT = "tempo esgotado"

UNIT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,80}\.service$")
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# Papeis do painel. A divisao segue o que da poder de root no container: shell, editor
# de arquivos e cadastro de servidor sao de admin; operar quem ja esta cadastrado
# (start/stop/update, configuracao do jogo, log, jogadores) e de operador.
ROLE_ADMIN = "admin"
ROLE_OPERADOR = "operador"
ROLES = (ROLE_ADMIN, ROLE_OPERADOR)
ROLE_LABELS = {
    ROLE_ADMIN: "Administrador",
    ROLE_OPERADOR: "Operador",
}
PASSWORD_MIN = 8

app = Flask(__name__)


def _load_secret_key() -> bytes:
    """Le a chave de assinatura do cookie; gera na primeira execucao."""
    try:
        with open(SECRET_FILE, "rb") as fh:
            data = fh.read().strip()
        if data:
            return data
    except FileNotFoundError:
        pass
    data = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
    fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return data


app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
    # O editor posta o arquivo como formulario: no pior caso cada byte vira %XX (3x),
    # entao o limite do request tem de ser bem maior que o do arquivo em si.
    MAX_CONTENT_LENGTH=REQUEST_LIMIT,
    # O Werkzeug 3.1 passou a cortar campo de formulario em 500 KB por padrao. Sem
    # subir isto tambem, salvar um arquivo grande morre com 413 antes de chegar na view.
    MAX_FORM_MEMORY_SIZE=REQUEST_LIMIT,
)

# Modo desenvolvimento (docker compose): recarrega os templates sem reiniciar.
if os.environ.get("GAMEPANEL_DEV") == "1":
    app.jinja_env.auto_reload = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True

# ------------------------------------------------------------------- banco

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  -- 'admin' (tudo, inclusive cadastrar servidor, shell e arquivos) ou 'operador'
  -- (opera os servidores ja cadastrados). Veja ROLES logo abaixo.
  role          TEXT NOT NULL DEFAULT 'operador',
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS servers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  host       TEXT NOT NULL,
  ssh_port   INTEGER NOT NULL DEFAULT 22,
  ssh_user   TEXT NOT NULL DEFAULT 'root',
  service    TEXT NOT NULL,
  game_port  TEXT NOT NULL DEFAULT '',
  notes      TEXT NOT NULL DEFAULT '',
  config_path TEXT NOT NULL DEFAULT '',
  -- Arquivos (um por linha) que a tela "Config" abre direto, sem navegar por pastas.
  config_files TEXT NOT NULL DEFAULT '',
  query_port INTEGER NOT NULL DEFAULT 0,
  player_source TEXT NOT NULL DEFAULT '',
  join_re    TEXT NOT NULL DEFAULT '',
  leave_re   TEXT NOT NULL DEFAULT '',
  -- Contagem por API HTTP do proprio jogo (Palworld, Satisfactory, ...).
  http_url   TEXT NOT NULL DEFAULT '',
  -- 'basic:usuario:senha', 'bearer:token' ou um cabecalho Authorization ja pronto.
  http_auth  TEXT NOT NULL DEFAULT '',
  -- Corpo JSON: vazio faz GET, preenchido faz POST.
  http_body  TEXT NOT NULL DEFAULT '',
  -- Caminhos dentro do JSON (ex.: 'data.players'); vazios = descobrir sozinho.
  http_list_path  TEXT NOT NULL DEFAULT '',
  http_count_path TEXT NOT NULL DEFAULT '',
  -- Login automatico (APIs cujo token expira, como a do Satisfactory): o painel
  -- posta http_login_body em http_login_url, tira o token de http_token_path e
  -- guarda em http_token. Quando a API responde 401/403, ele refaz o login.
  http_login_url  TEXT NOT NULL DEFAULT '',
  http_login_body TEXT NOT NULL DEFAULT '',
  http_token_path TEXT NOT NULL DEFAULT '',
  http_token      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (host, ssh_port)
);

CREATE TABLE IF NOT EXISTS jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id   INTEGER REFERENCES servers(id) ON DELETE SET NULL,
  target      TEXT NOT NULL DEFAULT '',
  action      TEXT NOT NULL,
  status      TEXT NOT NULL,             -- running | ok | error
  exit_code   INTEGER,
  output      TEXT NOT NULL DEFAULT '',
  command     TEXT NOT NULL DEFAULT '',  -- preenchido apenas pelo console
  username    TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_server ON jobs(server_id, id DESC);
"""


def db() -> sqlite3.Connection:
    """Conexao por request. WAL para o job em background nao travar a leitura da tela."""
    conn = getattr(g, "_db", None)
    if conn is None:
        conn = _connect()
        g._db = conn
    return conn


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@app.teardown_appcontext
def _close_db(_exc) -> None:
    conn = getattr(g, "_db", None)
    if conn is not None:
        conn.close()


# Colunas acrescentadas depois da primeira versao: CREATE TABLE IF NOT EXISTS nao
# altera tabelas que ja existem, entao cada uma precisa do seu ALTER aqui.
# O terceiro item e um comando SQL ou uma tupla deles (o ALTER mais o conserto das
# linhas antigas, quando o valor padrao da coluna nao serve para quem ja existia).
MIGRATIONS = (
    # Papeis: antes desta coluna todo mundo que logava podia tudo, e o unico usuario
    # era o criado pelo deploy. Logo, quem ja existe vira admin — o padrao 'operador'
    # da coluna vale so para quem for criado dali em diante.
    ("users", "role", (
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'operador'",
        "UPDATE users SET role = 'admin'",
    )),
    ("servers", "config_path", "ALTER TABLE servers ADD COLUMN config_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "query_port", "ALTER TABLE servers ADD COLUMN query_port INTEGER NOT NULL DEFAULT 0"),
    ("servers", "player_source", "ALTER TABLE servers ADD COLUMN player_source TEXT NOT NULL DEFAULT ''"),
    ("servers", "join_re", "ALTER TABLE servers ADD COLUMN join_re TEXT NOT NULL DEFAULT ''"),
    ("servers", "leave_re", "ALTER TABLE servers ADD COLUMN leave_re TEXT NOT NULL DEFAULT ''"),
    ("servers", "config_files", "ALTER TABLE servers ADD COLUMN config_files TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_url", "ALTER TABLE servers ADD COLUMN http_url TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_auth", "ALTER TABLE servers ADD COLUMN http_auth TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_body", "ALTER TABLE servers ADD COLUMN http_body TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_list_path", "ALTER TABLE servers ADD COLUMN http_list_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_count_path", "ALTER TABLE servers ADD COLUMN http_count_path TEXT NOT NULL DEFAULT ''"),
    # Login automatico: APIs que emitem token com prazo (Satisfactory) quebram a
    # contagem quando ele expira. Com estes campos o painel troca senha por token
    # sozinho e renova quando a API responde 401/403.
    ("servers", "http_login_url", "ALTER TABLE servers ADD COLUMN http_login_url TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_login_body", "ALTER TABLE servers ADD COLUMN http_login_body TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_token_path", "ALTER TABLE servers ADD COLUMN http_token_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_token", "ALTER TABLE servers ADD COLUMN http_token TEXT NOT NULL DEFAULT ''"),
)


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _connect()
    with conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                for comando in (ddl if isinstance(ddl, tuple) else (ddl,)):
                    conn.execute(comando)
    conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------- senhas


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(digest_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ------------------------------------------------------- auth / csrf / brute force

_login_fails: dict[str, list[float]] = {}
_login_lock = threading.Lock()
LOCKOUT_TRIES = 5
LOCKOUT_WINDOW = 300.0


def _lockout_remaining(key: str) -> int:
    with _login_lock:
        fails = [t for t in _login_fails.get(key, []) if time.time() - t < LOCKOUT_WINDOW]
        _login_fails[key] = fails
        if len(fails) < LOCKOUT_TRIES:
            return 0
        return int(LOCKOUT_WINDOW - (time.time() - fails[0])) + 1


def _record_fail(key: str) -> None:
    with _login_lock:
        _login_fails.setdefault(key, []).append(time.time())


def _clear_fails(key: str) -> None:
    with _login_lock:
        _login_fails.pop(key, None)


def usuario_logado() -> sqlite3.Row | None:
    """Linha do usuario da sessao, lida do banco uma vez por request.

    O papel NAO fica no cookie: tirar o admin de alguem tem de valer no proximo clique,
    e nao so quando a sessao dele expirar. Uma consulta por id em SQLite local custa
    menos que qualquer coisa que este painel faca em seguida.
    """
    cached = getattr(g, "_user", False)
    if cached is not False:
        return cached
    uid = session.get("uid")
    row = None
    if uid:
        row = db().execute(
            "SELECT id, username, role, created_at FROM users WHERE id = ?", (uid,)
        ).fetchone()
    g._user = row
    return row


def is_admin() -> bool:
    row = usuario_logado()
    return bool(row) and row["role"] == ROLE_ADMIN


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if usuario_logado() is None:
            # Conta apagada com a sessao ainda aberta: o cookie continua assinado e
            # valido, entao sem conferir o banco ela seguiria funcionando ate expirar.
            session.clear()
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    """Rotas que dao poder de root no container ou mexem em quem tem acesso."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            abort(403, "Esta tela e restrita a administradores do painel.")
        return view(*args, **kwargs)

    return login_required(wrapper)


def csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


@app.before_request
def _check_csrf():
    if request.method != "POST":
        return None
    # O terminal e o editor postam JSON (sem formulario), entao mandam o mesmo token
    # pelo cabecalho X-CSRF-Token.
    sent = request.form.get("csrf", "") or request.headers.get("X-CSRF-Token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, "token CSRF invalido ou expirado - recarregue a pagina")
    return None


@app.context_processor
def _inject():
    usuario = usuario_logado()
    return {
        "csrf_token": csrf_token,
        "current_user": usuario["username"] if usuario else None,
        # As telas escondem o que o operador nao pode abrir. Quem manda e o
        # @admin_required na rota; isto aqui e so para nao mostrar botao que da 403.
        "is_admin": bool(usuario) and usuario["role"] == ROLE_ADMIN,
        "role_label": ROLE_LABELS.get(usuario["role"], usuario["role"]) if usuario else "",
        "job_label": job_label,
        "allow_shell": ALLOW_SHELL,
        "allow_term": ALLOW_SHELL and HAVE_PTY,
        "allow_files": ALLOW_FILES,
        # A tela precisa saber se a contagem esta ligada, e ela pode vir da porta de
        # consulta OU do log — nao da para olhar so o query_port.
        "player_source": player_source,
    }


# ------------------------------------------------------------------- ssh


class RemoteError(RuntimeError):
    pass


def ssh_argv(server, connect_timeout: int = 10, extra: tuple[str, ...] = ()) -> list[str]:
    """Argumentos comuns do cliente ssh (usados pelos comandos e pelo terminal)."""
    return [
        "ssh",
        "-i", SSH_KEY,
        "-p", str(server["ssh_port"]),
        "-o", "BatchMode=yes",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        # accept-new: aprende a host key no primeiro acesso, mas alerta se ela mudar.
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={connect_timeout}",
        *extra,
        f"{server['ssh_user']}@{server['host']}",
    ]


def ssh_run(
    server: sqlite3.Row,
    remote_cmd: str,
    timeout: int = QUICK_TIMEOUT,
    stdin_data: bytes | None = None,
) -> subprocess.CompletedProcess:
    """Executa um comando no container de jogo via SSH.

    `remote_cmd` ja vem montado com shlex.quote pelos helpers abaixo; o SSH o entrega
    inteiro para o shell do destino, entao nada aqui pode vir cru de um formulario.
    `stdin_data` alimenta a entrada do comando remoto (usado para gravar arquivos).
    """
    cmd = ssh_argv(server, connect_timeout=min(timeout, 10)) + [remote_cmd]
    try:
        if stdin_data is not None:
            proc = subprocess.run(
                cmd, input=stdin_data, capture_output=True, timeout=timeout, check=False
            )
            # Binario na entrada, texto na saida: as mensagens de erro sao sempre texto.
            return subprocess.CompletedProcess(
                proc.args,
                proc.returncode,
                proc.stdout.decode("utf-8", "replace"),
                proc.stderr.decode("utf-8", "replace"),
            )
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise RemoteError(f"tempo esgotado ({timeout}s) executando no host {server['host']}")
    except OSError as exc:
        raise RemoteError(f"falha ao executar ssh: {exc}")


def ssh_output(server: sqlite3.Row, remote_cmd: str, timeout: int = QUICK_TIMEOUT) -> str:
    proc = ssh_run(server, remote_cmd, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RemoteError(detail or f"comando falhou (exit {proc.returncode})")
    return proc.stdout.strip()


def q(*parts: str) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def public_key() -> str:
    try:
        with open(f"{SSH_KEY}.pub", "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


# ------------------------------------------------------------- jogadores (A2S)

# Consulta o servidor pelo protocolo A2S da Steam — o mesmo que a lista de servidores
# do cliente usa. Vai por UDP direto do painel para a porta de query do jogo: nao passa
# por SSH, nao precisa de senha e nao exige nada instalado no container.
QUERY_TIMEOUT = float(os.environ.get("GAMEPANEL_QUERY_TIMEOUT", "3"))
PLAYERS_TTL = float(os.environ.get("GAMEPANEL_PLAYERS_TTL", "5"))

# De onde a contagem de jogadores pode sair. 'none' e o desligado explicito — diferente
# do vazio, que significa "cadastro antigo, deduza pela porta de consulta".
PLAYER_SOURCES = ("a2s", "http", "log", "none")

A2S_HEADER = b"\xff\xff\xff\xff"
A2S_SPLIT = b"\xff\xff\xff\xfe"
A2S_INFO_REQ = A2S_HEADER + b"TSource Engine Query\x00"


class QueryError(RuntimeError):
    pass


class AuthError(QueryError):
    """A API recusou a credencial (401/403).

    Separada de QueryError para o caminho HTTP saber quando vale a pena refazer o
    login: token expirado e o caso comum em API de jogo (a do Satisfactory emite
    token com prazo), e ai o certo e renovar sozinho em vez de exigir que alguem
    cole um token novo na mao.
    """


class _Buffer:
    """Leitor sequencial do corpo da resposta (tudo little-endian)."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise QueryError("resposta do servidor terminou antes do esperado")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def byte(self) -> int:
        return self._take(1)[0]

    def short(self) -> int:
        return struct.unpack("<h", self._take(2))[0]

    def long(self) -> int:
        return struct.unpack("<l", self._take(4))[0]

    def float(self) -> float:
        return struct.unpack("<f", self._take(4))[0]

    def string(self) -> str:
        fim = self.data.find(b"\x00", self.pos)
        if fim < 0:
            raise QueryError("texto sem terminador na resposta")
        out = self.data[self.pos:fim]
        self.pos = fim + 1
        # Nome de servidor costuma vir com emoji e cor; nada disso pode derrubar a tela.
        return out.decode("utf-8", "replace")


def _udp_receive(sock: socket.socket) -> bytes:
    """Le uma resposta, remontando quando o servidor divide em varios pacotes."""
    data, _ = sock.recvfrom(8192)
    if data[:4] != A2S_SPLIT:
        return data

    partes: dict[int, bytes] = {}
    total = 1
    while True:
        _pid, total, numero, _tam = struct.unpack_from("<lBBh", data, 4)
        partes[numero] = data[12:]
        if len(partes) >= total:
            break
        data, _ = sock.recvfrom(8192)
        if data[:4] != A2S_SPLIT:
            raise QueryError("resposta dividida veio incompleta")
    inteiro = b"".join(partes[i] for i in sorted(partes))
    if inteiro[:4] == A2S_HEADER:
        return inteiro
    raise QueryError("resposta dividida em formato desconhecido (compactada?)")


def _a2s_ask(sock: socket.socket, addr, pedido: bytes, resposta: bytes) -> _Buffer:
    """Manda o pedido e trata o desafio (challenge) que o servidor pode exigir."""
    sock.sendto(pedido, addr)
    data = _udp_receive(sock)
    if data[4:5] == b"A":  # S2C_CHALLENGE: repete o pedido carregando o desafio
        desafio = data[5:9]
        if pedido == A2S_INFO_REQ:
            sock.sendto(pedido + desafio, addr)
        else:
            sock.sendto(pedido[:5] + desafio, addr)
        data = _udp_receive(sock)
    if data[4:5] != resposta:
        raise QueryError(f"resposta inesperada do servidor (tipo {data[4:5]!r})")
    buf = _Buffer(data)
    buf.pos = 5
    return buf


def query_players(host: str, port: int) -> dict:
    """Numero de jogadores (A2S_INFO) e, quando o jogo publica, a lista (A2S_PLAYER)."""
    addr = (host, port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(QUERY_TIMEOUT)
        try:
            buf = _a2s_ask(sock, addr, A2S_INFO_REQ, b"I")
            buf.byte()  # versao do protocolo
            info = {
                "server_name": buf.string(),
                "map": buf.string(),
                "folder": buf.string(),
                "game": buf.string(),
            }
            buf.short()  # steam appid
            info["players"] = buf.byte()
            info["max_players"] = buf.byte()
            info["bots"] = buf.byte()
        except socket.timeout:
            raise QueryError(f"sem resposta em {QUERY_TIMEOUT:g}s na porta {port}/udp")
        except (OSError, struct.error) as exc:
            raise QueryError(f"falha ao consultar {host}:{port} - {exc}")

        # A lista de nomes e opcional: varios servidores Unreal so respondem a contagem.
        lista: list[dict] = []
        try:
            buf = _a2s_ask(sock, addr, A2S_HEADER + b"U" + b"\xff\xff\xff\xff", b"D")
            quantos = buf.byte()
            for _ in range(min(quantos, 128)):
                buf.byte()  # indice, que os servidores costumam zerar
                lista.append({
                    "name": buf.string(),
                    "score": buf.long(),
                    "seconds": max(0.0, buf.float()),
                })
        except (QueryError, OSError, struct.error):  # socket.timeout ja e um OSError
            lista = []

    info["list"] = [p for p in lista if p["name"]]
    info["error"] = ""
    return info


# ------------------------------------------- jogadores (API HTTP do proprio jogo)

# Cada vez mais jogo publica uma API HTTP de administracao em vez de (ou alem de) uma
# query UDP: Palworld (REST em 8212/tcp), Satisfactory (HTTPS em 7777/tcp), Minecraft
# com plugin, Factorio... E a melhor fonte de todas, porque devolve os NOMES e nao so
# a contagem. Nada aqui e especifico de um jogo: o painel busca uma URL, le o JSON e
# acha a lista/contagem sozinho — ou pelo caminho que voce apontar.
#
# A chamada sai de DENTRO do container, por SSH, e nao do painel: essas APIs sao feitas
# para escutar em localhost (a documentacao do Palworld pede explicitamente para NAO
# expor a porta na internet) e assim continuam fechadas para fora.
HTTP_TIMEOUT = float(os.environ.get("GAMEPANEL_HTTP_TIMEOUT", "6"))
HTTP_MAX_BYTES = 256 * 1024
HTTP_URL_MAX = 400
HTTP_BODY_MAX = 2000
HTTP_PATH_MAX = 120
# Colunas que descrevem a chamada; viajam juntas entre formulario, assistente e banco.
HTTP_FIELDS = ("http_url", "http_auth", "http_body", "http_list_path", "http_count_path",
               "http_login_url", "http_login_body", "http_token_path")
URL_RE = re.compile(r"^https?://[A-Za-z0-9._\-]{1,253}(:\d{1,5})?(/[^\s]*)?$")
STATUS_MARK = "__HTTP_STATUS__"

# curl e a primeira opcao; python3 cobre os containers que so tem o interpretador
# (a nossa imagem de teste, por exemplo, nao traz curl).
HTTP_FETCH_SCRIPT = r"""
set -u
url=$1
auth=$2
corpo=$3
tmo=$4

if command -v curl >/dev/null 2>&1; then
  # -k: essas APIs usam certificado autoassinado (o Satisfactory, por exemplo).
  if [ -n "$corpo" ] && [ -n "$auth" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H "Authorization: $auth" -H 'Content-Type: application/json' \
      --data-binary "$corpo" "$url"
  elif [ -n "$corpo" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H 'Content-Type: application/json' --data-binary "$corpo" "$url"
  elif [ -n "$auth" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H "Authorization: $auth" "$url"
  else
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" "$url"
  fi
  exit $?
fi

if command -v python3 >/dev/null 2>&1; then
  python3 - "$url" "$auth" "$corpo" "$tmo" <<'PY'
import sys
import urllib.error
import urllib.request

url, auth, corpo, tmo = sys.argv[1:5]
req = urllib.request.Request(url, data=corpo.encode() if corpo else None)
if corpo:
    req.add_header("Content-Type", "application/json")
if auth:
    req.add_header("Authorization", auth)
ctx = None
if url.startswith("https"):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
try:
    resp = urllib.request.urlopen(req, timeout=float(tmo), context=ctx)
    dados, codigo = resp.read(), resp.getcode()
except urllib.error.HTTPError as exc:
    # 401/404/500 sao respostas, nao falhas: o painel quer ver o codigo.
    dados, codigo = exc.read(), exc.code
except Exception as exc:
    # Porta fechada, DNS, timeout: uma linha para o painel mostrar, nao um traceback.
    sys.stderr.write("nao consegui chamar %s: %s\n" % (url, exc))
    raise SystemExit(1)
sys.stdout.write(dados.decode("utf-8", "replace"))
sys.stdout.write("\n__HTTP_STATUS__%d" % codigo)
PY
  exit $?
fi

echo "o container nao tem curl nem python3 para falar HTTP" >&2
exit 127
"""


def auth_header(guardado: str) -> str:
    """Transforma o que esta no banco no cabecalho Authorization.

    Formatos: 'basic:usuario:senha', 'bearer:token' ou o cabecalho ja pronto.
    """
    texto = (guardado or "").strip()
    if not texto:
        return ""
    tipo, _, resto = texto.partition(":")
    if tipo.lower() == "basic":
        return "Basic " + base64.b64encode(resto.encode()).decode()
    if tipo.lower() == "bearer":
        return "Bearer " + resto
    return texto


def _split_status(bruto: str) -> tuple[str, int]:
    """Separa o corpo do marcador de status que o script anexa no fim."""
    pos = bruto.rfind(STATUS_MARK)
    if pos < 0:
        return bruto, 0
    try:
        status = int(bruto[pos + len(STATUS_MARK):].strip() or 0)
    except ValueError:
        status = 0
    return bruto[:pos].rstrip("\n"), status


def http_json(server: sqlite3.Row, url: str, auth: str, corpo: str):
    """Busca a URL de dentro do container e devolve o JSON ja interpretado."""
    url = (url or "").strip()
    if len(url) > HTTP_URL_MAX or not URL_RE.match(url):
        raise QueryError("URL invalida (ex.: http://127.0.0.1:8212/v1/api/players)")
    try:
        bruto = ssh_output(
            server,
            q("bash", "-lc", HTTP_FETCH_SCRIPT, "gp", url,
              auth_header(auth), (corpo or "").strip(), f"{HTTP_TIMEOUT:g}"),
            timeout=int(HTTP_TIMEOUT) + 15,
        )
    except RemoteError as exc:
        raise QueryError(str(exc))

    texto, status = _split_status(bruto)
    if status in (401, 403):
        # AuthError e uma QueryError especializada: quem tem login configurado usa
        # isso como gatilho para renovar o token em vez de so reportar o erro.
        raise AuthError(f"a API respondeu {status} - confira o usuario/senha de admin")
    if status >= 400:
        raise QueryError(f"a API respondeu HTTP {status}")
    if len(texto) > HTTP_MAX_BYTES:
        raise QueryError("resposta da API grande demais para ser lida aqui")
    try:
        return json.loads(texto)
    except ValueError:
        amostra = texto.strip()[:120] or "(vazia)"
        raise QueryError(f"a resposta nao e JSON: {amostra}")


# Chaves que os jogos costumam usar. Comparadas sem maiusculas nem separadores, entao
# 'numConnectedPlayers', 'num_connected_players' e 'NUMCONNECTEDPLAYERS' sao a mesma.
LIST_KEYS = {"players", "playerlist", "onlineplayers", "connectedplayers", "clients"}
NAME_KEYS = ("name", "playername", "accountname", "username", "displayname", "nick")
COUNT_KEYS = {"players", "playercount", "numplayers", "onlineplayers", "currentplayernum",
              "numconnectedplayers", "playersonline", "online"}
MAX_KEYS = {"maxplayers", "maxplayernum", "maxplayercount", "serverplayermaxnum",
            "playerlimit", "slots"}
SERVER_NAME_KEYS = {"servername", "hostname"}
JSON_MAX_DEPTH = 5
PATH_RE = re.compile(r"[^.\[\]]+|\[\d+\]")


def _slug(chave: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(chave).lower())


def _json_walk(dados, caminho: str):
    """Anda um caminho estilo 'a.b[0].c'. Caminho vazio devolve o objeto inteiro."""
    atual = dados
    for parte in PATH_RE.findall(caminho or ""):
        if parte.startswith("["):
            indice = int(parte[1:-1])
            if not isinstance(atual, list) or indice >= len(atual):
                raise QueryError(f"'{caminho}' nao existe na resposta")
            atual = atual[indice]
        elif isinstance(atual, dict) and parte in atual:
            atual = atual[parte]
        else:
            raise QueryError(f"'{caminho}' nao existe na resposta")
    return atual


def _nome_do_item(item) -> str:
    if not isinstance(item, dict):
        return str(item).strip() if isinstance(item, str) else ""
    por_slug = {_slug(k): v for k, v in item.items()}
    for chave in NAME_KEYS:
        valor = por_slug.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


def _lista_de_jogadores(item) -> bool:
    """Uma lista so vale se for de objetos — e, se tiver alguem, com cara de jogador."""
    if not isinstance(item, list) or not all(isinstance(i, dict) for i in item):
        return False
    return not item or bool(_nome_do_item(item[0]))


def _acha_lista(dados, profundidade: int = 0):
    """Primeira lista de jogadores da resposta, procurando pelo nome da chave e pela forma."""
    if _lista_de_jogadores(dados):
        return dados
    if not isinstance(dados, dict) or profundidade >= JSON_MAX_DEPTH:
        return None
    # A chave manda: {"players": []} com ninguem online e resposta valida, e pela
    # forma (lista vazia) nao daria para reconhecer.
    for chave, valor in dados.items():
        if _slug(chave) in LIST_KEYS and isinstance(valor, list):
            return valor if all(isinstance(i, dict) for i in valor) else None
    for valor in dados.values():
        achou = _acha_lista(valor, profundidade + 1)
        if achou is not None:
            return achou
    return None


def _acha_valor(dados, chaves: set, tipos: tuple, profundidade: int = 0):
    """Primeiro valor do tipo pedido guardado em uma das chaves conhecidas."""
    if not isinstance(dados, dict) or profundidade >= JSON_MAX_DEPTH:
        return None
    for chave, valor in dados.items():
        if _slug(chave) in chaves and isinstance(valor, tipos) and not isinstance(valor, bool):
            return valor
    for valor in dados.values():
        achou = _acha_valor(valor, chaves, tipos, profundidade + 1)
        if achou is not None:
            return achou
    return None


def read_players_json(dados, caminho_lista: str = "", caminho_contagem: str = "") -> dict:
    """Tira jogadores de um JSON qualquer.

    Sem caminhos preenchidos o painel procura sozinho uma lista de jogadores e, se nao
    houver, um numero em alguma chave conhecida (currentplayernum, numplayers, ...).
    """
    lista = None
    if caminho_lista:
        lista = _json_walk(dados, caminho_lista)
        if not isinstance(lista, list):
            raise QueryError(f"'{caminho_lista}' nao aponta para uma lista")
    elif not caminho_contagem:
        lista = _acha_lista(dados)

    quantos = None
    if caminho_contagem:
        bruto = _json_walk(dados, caminho_contagem)
        if isinstance(bruto, list):
            quantos = len(bruto)
        elif isinstance(bruto, (int, float)) and not isinstance(bruto, bool):
            quantos = int(bruto)
        else:
            raise QueryError(f"'{caminho_contagem}' nao e um numero nem uma lista")
    elif lista is None:
        achou = _acha_valor(dados, COUNT_KEYS, (int, float))
        quantos = int(achou) if achou is not None else None

    nomes = []
    if isinstance(lista, list):
        for item in lista[:128]:
            nome = _nome_do_item(item)
            if nome:
                nomes.append({"name": nome, "since": "", "score": 0, "seconds": 0})
        if quantos is None:
            quantos = len(lista)

    if quantos is None:
        raise QueryError(
            "nao achei jogadores na resposta - preencha o caminho da lista ou da contagem"
        )

    maximo = _acha_valor(dados, MAX_KEYS, (int, float))
    return {
        "players": quantos,
        "list": nomes,
        "max_players": int(maximo) if maximo is not None else None,
        "server_name": _acha_valor(dados, SERVER_NAME_KEYS, (str,)) or "",
        "map": "",
        "error": "",
    }


def _tem_login(server: sqlite3.Row) -> bool:
    """True quando o servidor esta configurado para obter o token sozinho."""
    try:
        return bool((server["http_login_url"] or "").strip()
                    and (server["http_token_path"] or "").strip())
    except (IndexError, KeyError):
        # Linha vinda de um SELECT sem as colunas novas (ou banco antes da migracao).
        return False


def _valor_guardado(server: sqlite3.Row, coluna: str) -> str:
    try:
        return (server[coluna] or "").strip()
    except (IndexError, KeyError):
        return ""


def http_login(server: sqlite3.Row) -> str:
    """Troca a credencial por um token e guarda no banco. Devolve o token."""
    url = _valor_guardado(server, "http_login_url")
    caminho = _valor_guardado(server, "http_token_path")
    if not url or not caminho:
        raise QueryError("login automatico incompleto (falta URL de login ou caminho do token)")

    # O login vai SEM Authorization: e ele quem produz a credencial.
    dados = http_json(server, url, "", _valor_guardado(server, "http_login_body"))
    token = _json_walk(dados, caminho)
    if not isinstance(token, str) or not token.strip():
        raise QueryError(
            f"o login respondeu, mas nao achei um token em '{caminho}'"
        )
    token = token.strip()
    # Conexao propria, e nao db(): db() vive no 'g' do Flask e a contagem tambem roda
    # fora de request (cache/pollagem em thread). Aqui a escrita e uma linha so.
    con = _connect()
    try:
        with con:
            con.execute("UPDATE servers SET http_token = ? WHERE id = ?",
                        (token, int(server["id"])))
    finally:
        con.close()
    return token


def players_from_http(server: sqlite3.Row) -> dict:
    if not (server["http_url"] or "").strip():
        raise QueryError("informe a URL da API do jogo")

    com_login = _tem_login(server)
    if com_login:
        token = _valor_guardado(server, "http_token")
        # Sem token guardado (primeira vez, ou depois de trocar a senha) ja entra
        # pelo login em vez de gastar uma chamada que vai falhar.
        auth = f"bearer:{token}" if token else f"bearer:{http_login(server)}"
    else:
        auth = server["http_auth"]

    try:
        dados = http_json(server, server["http_url"], auth, server["http_body"])
    except AuthError:
        if not com_login:
            raise
        # Token expirado ou revogado: renova uma vez e repete. Se falhar de novo,
        # o erro sobe - ai o problema e a credencial, nao o prazo do token.
        dados = http_json(server, server["http_url"],
                          f"bearer:{http_login(server)}", server["http_body"])

    return read_players_json(dados, server["http_list_path"], server["http_count_path"])


# ------------------------------------------------------ jogadores (pelo log)

# Nem todo jogo publica consulta A2S (o RuneScape Dragonwilds, por exemplo, nao publica).
# Quando o servidor anuncia entradas e saidas no log, da para contar por ali: o painel
# reproduz os eventos desde o ultimo start do servico e ve quem sobrou.
LOG_SCAN_MAX = 20000
RE_MAX_LEN = 300
# Palavras que costumam aparecer na linha de entrada/saida — usadas so pelo assistente
# que ajuda a descobrir o padrao do jogo.
LOG_HINT_WORDS = (
    "join", "joined", "left", "leave", "connect", "disconnect", "login", "logout",
    "player", "jogador", "entrou", "saiu",
)
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")

# Le do start do servico para ca: eventos de execucoes anteriores contariam jogador
# que ja foi embora ha muito tempo.
LOG_PLAYERS_SCRIPT = r"""
set -u
unit=$1
max=$2
inicio=$(systemctl show -p ActiveEnterTimestamp --value "$unit" 2>/dev/null || true)
if [ -n "$inicio" ]; then
  journalctl -u "$unit" --since "$inicio" --no-pager -o short-iso 2>/dev/null | tail -n "$max"
else
  journalctl -u "$unit" --no-pager -o short-iso -n "$max" 2>/dev/null
fi
"""


def compile_pattern(raw: str, rotulo: str):
    """Compila um padrao vindo da tela; devolve None quando esta vazio."""
    texto = (raw or "").strip()
    if not texto:
        return None
    if len(texto) > RE_MAX_LEN:
        raise QueryError(f"padrao de {rotulo} longo demais (limite de {RE_MAX_LEN} caracteres)")
    try:
        return re.compile(texto)
    except re.error as exc:
        raise QueryError(f"padrao de {rotulo} invalido: {exc}")


def _log_timestamp(line: str) -> str:
    m = TS_RE.match(line)
    return f"{m.group(1)} {m.group(2)}" if m else ""


# Linha gigante (stack trace) nao pode custar caro no regex.
LOG_LINE_MAX = 500


def _events_by_name(linhas, entrar, sair) -> dict:
    """Os dois padroes capturam (?P<name>...): da para dizer QUEM esta online."""
    online: dict[str, str] = {}
    for line in linhas:
        curta = line[:LOG_LINE_MAX]
        entrou = entrar.search(curta)
        if entrou:
            nome = (entrou.groupdict().get("name") or "").strip()
            if nome:
                online[nome] = _log_timestamp(line)
            continue
        saiu = sair.search(curta) if sair else None
        if saiu:
            online.pop((saiu.groupdict().get("name") or "").strip(), None)
    return {
        "players": len(online),
        "list": [{"name": n, "since": t, "score": 0, "seconds": 0} for n, t in online.items()],
    }


def _events_by_count(linhas, entrar, sair) -> dict:
    """Sem nome na saida (varios servidores Unreal so avisam que alguem saiu):
    sobra somar as entradas e subtrair as saidas."""
    total = 0
    for line in linhas:
        curta = line[:LOG_LINE_MAX]
        if entrar.search(curta):
            total += 1
        elif sair and sair.search(curta):
            total = max(0, total - 1)
    return {"players": total, "list": []}


def _apply_log_events(linhas, entrar, sair) -> dict:
    """Reproduz os eventos do log em ordem e devolve quem ficou."""
    com_nome = bool(entrar.groupindex.get("name")) and (
        not sair or bool(sair.groupindex.get("name"))
    )
    return _events_by_name(linhas, entrar, sair) if com_nome else _events_by_count(linhas, entrar, sair)


# ------------------------------------------- descobrir como contar jogadores

# O jogo abre os sockets dele dentro do container: em vez de chutar a porta de consulta,
# pergunta ao proprio container quais portas estao escutando, QUEM as abriu, e testa uma
# a uma. UDP vira consulta A2S; TCP vira sondagem HTTP (e onde moram as APIs de
# administracao).
#
# Tudo sai de /proc: 'ss', 'netstat' e 'lsof' nao vem instalados em todo container.
# O caminho e o mesmo que o `ss -p` faz: /proc/net/* da porta + inode do socket, e os
# descritores abertos de cada processo (/proc/PID/fd) dizem de quem e aquele inode.
# Saber o dono e o que separa a porta do jogo do ruido (sshd, DNS do Docker, um HTTP
# qualquer numa porta alta).
LISTEN_PORTS_SCRIPT = r"""
set -u

# inode do socket -> pid. Como o painel entra como root, enxerga todos os processos.
donos() {
  for dir in /proc/[0-9]*; do
    [ -d "$dir/fd" ] || continue
    ls -l "$dir/fd" 2>/dev/null | awk -v pid="${dir#/proc/}" '
      match($0, /socket:\[[0-9]+\]/) {
        print substr($0, RSTART + 8, RLENGTH - 9), pid
      }'
  done
}

# Coluna 2 = endereco local (IP:PORTA em hex), 4 = estado, 10 = inode. Em TCP so
# interessa 0A (LISTEN); em UDP o socket ligado ja e a porta aberta.
sockets() {
  arquivo=$1 proto=$2 estado=$3
  [ -r "$arquivo" ] || return 0
  awk -v p="$proto" -v e="$estado" \
    'NR > 1 && (e == "" || $4 == e) { split($2, a, ":"); print p, a[2], $10 }' "$arquivo"
}

mapa=$(donos)
{
  sockets /proc/net/udp  udp ""
  sockets /proc/net/udp6 udp ""
  sockets /proc/net/tcp  tcp 0A
  sockets /proc/net/tcp6 tcp 0A
} | sort -u | while read -r proto hex inode; do
  porta=$(printf '%d' "0x$hex" 2>/dev/null) || continue
  pid=$(printf '%s\n' "$mapa" | awk -v i="$inode" '$1 == i { print $2; exit }')
  nome='?'
  if [ -n "$pid" ] && [ -r "/proc/$pid/comm" ]; then
    nome=$(cat "/proc/$pid/comm" 2>/dev/null) || nome='?'
  fi
  printf '%s %s %s %s\n' "$proto" "$porta" "${pid:-0}" "${nome:-?}"
done
"""

# Portas de consulta que a maioria dos jogos Steam usa quando nao ha nada declarado.
QUERY_PORT_GUESSES = (27015, 27016, 27005)
# Portas de API de administracao mais comuns: 8212 (REST do Palworld), 7777 (HTTPS do
# Satisfactory), 8080 (padrao de quem escreve um painelzinho proprio).
API_PORT_GUESSES = (8212, 7777, 8080)
# O sshd e o proprio painel entrando no container: sondar essa porta so gera ruido.
PORTAS_IGNORADAS = (22,)


def _portas_do_texto(texto: str) -> list[int]:
    """Tira numeros de porta do campo livre 'Portas do jogo' (ex.: '8211/udp 27015/udp')."""
    return [int(n) for n in re.findall(r"\d{2,5}", texto or "") if 1 <= int(n) <= 65535]


def _sem_repetir(portas) -> list[int]:
    saida: list[int] = []
    for porta in portas:
        if 1 <= porta <= 65535 and porta not in saida and porta not in PORTAS_IGNORADAS:
            saida.append(porta)
    return saida


# Processos que sempre abrem porta num container e nunca sao o jogo: marca-los deixa a
# lista legivel sem esconder nada de quem esta procurando.
PROCESSOS_DE_INFRA = frozenset({
    "sshd", "sshd-session", "systemd", "systemd-resolve", "systemd-resolved", "dockerd",
    "containerd", "dnsmasq", "cron", "rsyslogd", "chronyd", "ntpd",
})


def candidate_ports(server: sqlite3.Row) -> tuple[list[int], list[int], dict, str]:
    """Portas a testar (UDP, TCP), quem abriu cada uma, e o aviso se a leitura falhou.

    A lista vem do container (portas realmente abertas, com o processo dono) e so entao
    recebe as portas declaradas no cadastro e os chutes conhecidos, como rede de seguranca
    para quando o servidor esta parado — nessa hora nao ha socket nenhum para detectar.
    """
    escutando: dict[str, list[int]] = {"udp": [], "tcp": []}
    donos: dict[tuple[str, int], dict] = {}
    aviso = ""
    try:
        raw = ssh_output(server, q("bash", "-lc", LISTEN_PORTS_SCRIPT, "gp"), timeout=60)
        for linha in raw.splitlines():
            campos = linha.split(None, 3)
            if len(campos) != 4 or campos[0] not in escutando or not campos[1].isdigit():
                continue
            proto, porta, pid, nome = campos[0], int(campos[1]), campos[2], campos[3]
            escutando[proto].append(porta)
            # Mesma porta em IPv4 e IPv6: fica a primeira que soube dizer o dono.
            if donos.get((proto, porta), {}).get("proc", "?") == "?":
                donos[(proto, porta)] = {
                    "pid": int(pid) if pid.isdigit() else 0,
                    "proc": nome.strip() or "?",
                    "infra": nome.strip() in PROCESSOS_DE_INFRA,
                }
    except (RemoteError, ValueError) as exc:
        aviso = f"nao consegui listar as portas abertas do container: {exc}"

    def prioridade(proto: str, porta: int) -> int:
        """Porta com processo dono de verdade primeiro; infra por ultimo.

        No meio ficam as sem dono: existe socket, mas nenhum processo DESTE container o
        abriu (o resolvedor DNS do Docker, por exemplo, que vive fora do namespace).
        """
        dono = donos.get((proto, porta))
        if dono is None or dono["proc"] == "?":
            return 1
        return 2 if dono["infra"] else 0

    def util_primeiro(proto: str) -> list[int]:
        return sorted(escutando[proto], key=lambda p: (prioridade(proto, p), p))

    declaradas = _portas_do_texto(server["game_port"])
    udp = _sem_repetir(util_primeiro("udp") + declaradas + list(QUERY_PORT_GUESSES))
    tcp = _sem_repetir(util_primeiro("tcp") + declaradas + list(API_PORT_GUESSES))
    return udp, tcp, donos, aviso


def _com_dono(itens: list[dict], donos: dict, proto: str) -> list[dict]:
    """Anexa o processo dono a cada porta sondada, para a tela poder mostrar.

    Tres estados diferentes, e a tela precisa saber qual e qual:
    'detectada'  - o socket existe e o processo dono foi identificado;
    'sem-dono'   - o socket existe, mas nenhum processo deste container o abriu;
    'nao-vista'  - a porta nem estava aberta (veio do cadastro ou da lista de chutes).
    """
    for item in itens:
        dono = donos.get((proto, item["port"]))
        if dono is None:
            item.update({"origem": "nao-vista", "proc": "", "pid": 0, "infra": False})
        elif dono["proc"] == "?":
            item.update({"origem": "sem-dono", "proc": "", "pid": 0, "infra": False})
        else:
            item.update({"origem": "detectada", "proc": dono["proc"],
                         "pid": dono["pid"], "infra": dono["infra"]})
    return itens


# Sondagem HTTP das portas TCP. Roda dentro do container (uma unica ida de SSH para
# todas as portas) porque API de administracao costuma escutar so em 127.0.0.1 — de
# fora do container ela pareceria fechada.
#
# Duas etapas por porta: primeiro um GET em "/" so para saber se ali fala HTTP; so
# quem responde alguma coisa leva os caminhos conhecidos. Assim uma porta que nao e
# HTTP custa uma tentativa, nao seis.
HTTP_PROBE_TIMEOUT = float(os.environ.get("GAMEPANEL_PROBE_TIMEOUT", "2"))
HTTP_PROBE_PORTS_MAX = 12
HTTP_PROBE_SCRIPT = r"""
set -u
tmo=$1
shift
caminhos='/v1/api/info /v1/api/metrics /v1/api/players /api/v1 /status /api/info'

sonda=""
if command -v curl >/dev/null 2>&1; then
  pega() { curl -sS -k -m "$tmo" -o /dev/null -w '%{http_code} %{content_type}' "$1" 2>/dev/null || echo "000 -"; }
elif command -v python3 >/dev/null 2>&1; then
  sonda=$(mktemp 2>/dev/null) || sonda=/tmp/gamepanel-sonda.py
  cat >"$sonda" <<'PY'
import sys
import urllib.error
import urllib.request

url, tmo = sys.argv[1], float(sys.argv[2])
try:
    if url.startswith("https"):
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx = None
    resp = urllib.request.urlopen(url, timeout=tmo, context=ctx)
    print(resp.getcode(), resp.headers.get("Content-Type", "-") or "-")
except urllib.error.HTTPError as exc:
    print(exc.code, exc.headers.get("Content-Type", "-") or "-")
except Exception:
    print("000 -")
PY
  pega() { python3 "$sonda" "$1" "$tmo" 2>/dev/null || echo "000 -"; }
else
  echo "o container nao tem curl nem python3 para sondar as portas" >&2
  exit 127
fi

for porta in "$@"; do
  esquema=http
  raiz=$(pega "http://127.0.0.1:${porta}/")
  case "$raiz" in
    000*)
      # Nada em HTTP: pode ser uma API que so aceita TLS (o Satisfactory e assim).
      raiz=$(pega "https://127.0.0.1:${porta}/")
      esquema=https
      ;;
  esac
  printf '%s|%s|/|%s\n' "$porta" "$esquema" "$raiz"
  case "$raiz" in
    000*) continue ;;
  esac
  for caminho in $caminhos; do
    printf '%s|%s|%s|%s\n' "$porta" "$esquema" "$caminho" \
      "$(pega "${esquema}://127.0.0.1:${porta}${caminho}")"
  done
done

[ -n "$sonda" ] && rm -f "$sonda"
exit 0
"""


def probe_http_ports(server: sqlite3.Row, portas: list[int]) -> tuple[list[dict], list[int], str]:
    """Sonda as portas TCP com HTTP. Devolve (o que respondeu, portas mudas, aviso)."""
    portas = portas[:HTTP_PROBE_PORTS_MAX]
    if not portas:
        return [], [], ""
    # Pior caso: 2 tentativas na raiz + 6 caminhos, por porta.
    limite = int(HTTP_PROBE_TIMEOUT * 8 * len(portas)) + 20
    try:
        raw = ssh_output(
            server,
            q("bash", "-lc", HTTP_PROBE_SCRIPT, "gp", f"{HTTP_PROBE_TIMEOUT:g}",
              *[str(p) for p in portas]),
            timeout=limite,
        )
    except RemoteError as exc:
        return [], portas, f"nao consegui sondar as portas TCP: {exc}"

    achados: list[dict] = []
    responderam: set[int] = set()
    for linha in raw.splitlines():
        campos = linha.split("|")
        if len(campos) != 4 or not campos[0].isdigit():
            continue
        porta, esquema, caminho, resultado = campos
        status, _, tipo = resultado.strip().partition(" ")
        if not status.isdigit() or int(status) == 0:
            continue
        responderam.add(int(porta))
        achados.append({
            "port": int(porta),
            "scheme": esquema,
            "path": caminho,
            "status": int(status),
            "content_type": (tipo or "-").split(";")[0].strip(),
            "url": f"{esquema}://127.0.0.1:{porta}{caminho}",
        })

    achados = _resume_genericos(achados)
    # JSON primeiro, depois quem pediu senha (401/403 = "existe API aqui").
    achados.sort(key=lambda a: (
        0 if "json" in a["content_type"] else 1,
        0 if a["status"] in (200, 401, 403) else 1,
        a["port"], a["path"],
    ))
    mudas = [p for p in portas if p not in responderam]
    return achados, mudas, ""


# Status que indicam "achei alguma coisa": 200 e resposta, 401/403 e "existe API aqui,
# ela so quer senha". Qualquer outra coisa e um servidor HTTP que nao conhece a rota.
STATUS_UTEIS = (200, 401, 403)


def _resume_genericos(achados: list[dict]) -> list[dict]:
    """Porta que respondeu 404 em tudo vira UMA linha, nao sete.

    Um processo qualquer subindo um HTTP numa porta alta (o cliente da Steam faz isso)
    enche a tela de linhas inuteis e some com o achado de verdade. Aqui ele fica como
    uma nota so, marcada para a tela nao oferecer "usar esta URL".
    """
    por_porta: dict[int, list[dict]] = {}
    for item in achados:
        por_porta.setdefault(item["port"], []).append(item)

    saida: list[dict] = []
    for itens in por_porta.values():
        if any(i["status"] in STATUS_UTEIS for i in itens):
            saida.extend(i for i in itens if i["status"] in STATUS_UTEIS)
            continue
        raiz = next((i for i in itens if i["path"] == "/"), itens[0])
        saida.append({**raiz, "generico": True})
    return saida


def probe_ports(host: str, portas: list[int]) -> list[dict]:
    """Dispara um A2S_INFO em cada porta candidata, todas ao mesmo tempo."""
    resultados: dict[int, dict] = {}
    lock = threading.Lock()

    def testa(porta: int):
        item = {"port": porta, "ok": False, "players": None, "max_players": None,
                "server_name": "", "error": ""}
        try:
            info = query_players(host, porta)
            item.update({
                "ok": True, "players": info["players"], "max_players": info["max_players"],
                "server_name": info["server_name"],
            })
        except QueryError as exc:
            item["error"] = str(exc)
        with lock:
            resultados[porta] = item

    threads = [threading.Thread(target=testa, args=(p,), daemon=True) for p in portas]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=QUERY_TIMEOUT * 2 + 2)
    return [resultados.get(p, {"port": p, "ok": False, "error": MSG_TIMEOUT}) for p in portas]


def read_log_lines(server: sqlite3.Row) -> list[str]:
    raw = ssh_output(
        server,
        q("bash", "-lc", LOG_PLAYERS_SCRIPT, "gp", server["service"], str(LOG_SCAN_MAX)),
        timeout=60,
    )
    return raw.splitlines()


def players_from_log(server: sqlite3.Row) -> dict:
    entrar = compile_pattern(server["join_re"], "entrada")
    if not entrar:
        raise QueryError("informe o padrao da linha de entrada de jogador")
    sair = compile_pattern(server["leave_re"], "saida")
    try:
        linhas = read_log_lines(server)
    except RemoteError as exc:
        raise QueryError(str(exc))

    resultado = _apply_log_events(linhas, entrar, sair)
    resultado.update({"error": "", "max_players": None, "server_name": "", "map": ""})
    return resultado


_players_cache: dict[int, tuple[float, dict]] = {}
_players_lock = threading.Lock()


def player_source(server: sqlite3.Row) -> str:
    """Como contar os jogadores deste servidor: 'a2s', 'http', 'log' ou '' (desligado)."""
    escolhido = (server["player_source"] or "").strip()
    if escolhido in PLAYER_SOURCES:
        return "" if escolhido == "none" else escolhido
    # Cadastro antigo, anterior ao campo: porta de consulta preenchida = A2S.
    return "a2s" if int(server["query_port"] or 0) else ""


def server_players(server: sqlite3.Row, force: bool = False) -> dict:
    origem = player_source(server)
    if not origem:
        return {"configured": False, "error": "", "players": None, "list": [], "source": ""}

    key = int(server["id"])
    agora = time.monotonic()
    if not force:
        with _players_lock:
            cached = _players_cache.get(key)
        if cached and agora - cached[0] < PLAYERS_TTL:
            return cached[1]

    try:
        if origem == "log":
            data = players_from_log(server)
        elif origem == "http":
            data = players_from_http(server)
        else:
            porta = int(server["query_port"] or 0)
            if not porta:
                raise QueryError("informe a porta de consulta (query Steam) do servidor")
            data = query_players(server["host"], porta)
        data["configured"] = True
    except QueryError as exc:
        data = {"configured": True, "error": str(exc), "players": None, "list": []}
    data["source"] = origem

    with _players_lock:
        _players_cache[key] = (agora, data)
    return data


def all_players(servers) -> dict[int, dict]:
    """Consulta todos em paralelo: sao 3s de espera cada quando um esta fora do ar."""
    results: dict[int, dict] = {}
    lock = threading.Lock()

    def work(srv):
        data = server_players(srv)
        with lock:
            results[int(srv["id"])] = data

    threads = [threading.Thread(target=work, args=(s,), daemon=True) for s in servers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=QUERY_TIMEOUT * 3 + 2)
    for srv in servers:
        results.setdefault(int(srv["id"]), {"configured": True, "error": MSG_TIMEOUT,
                                            "players": None, "list": [], "source": ""})
    return results


# ------------------------------------------------------------------ recursos

# Duas amostras espacadas dentro do proprio container: CPU e rede so fazem sentido como
# variacao no tempo, e medir com uma unica ida de SSH sai mais barato do que guardar a
# amostra anterior aqui e torcer para o intervalo entre telas ser regular.
METRICS_SCRIPT = r"""
set -u
CG=/sys/fs/cgroup
unit=$1
dir=$2

cpu_usec() {
  if [ -r "$CG/cpu.stat" ]; then
    awk '/^usage_usec/ { print $2; exit }' "$CG/cpu.stat"
  else
    echo -
  fi
}
# Cada numero sai no seu proprio campo (separador '|'): dois valores num campo so
# fariam o painel ler o total da CPU como texto e zerar a conta.
proc_stat() { awk '/^cpu /{ t=0; for (i=2; i<=NF; i++) t+=$i; printf "%d|%d", t, $5+$6; exit }' /proc/stat; }
# Soma todas as interfaces menos a loopback (rx = campo 2, tx = campo 10 apos o ':').
net_bytes() {
  awk 'NR>2 { sub(/:/, " "); if ($1 != "lo") { rx += $2; tx += $10 } }
       END { printf "%d|%d", rx+0, tx+0 }' /proc/net/dev
}
pid_ticks() {
  if [ "$1" -gt 0 ] && [ -r "/proc/$1/stat" ]; then
    awk '{ print $14 + $15 }' "/proc/$1/stat"
  else
    echo 0
  fi
}

pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
case "$pid" in ''|*[!0-9]*) pid=0 ;; esac

amostra() {
  printf 'sample|%s|%s|%s|%s|%s\n' \
    "$(awk '{ print $1; exit }' /proc/uptime)" \
    "$(cpu_usec)" "$(proc_stat)" "$(net_bytes)" "$(pid_ticks "$pid")"
}

amostra
sleep 0.5
amostra

printf 'cores|%s\n' "$(nproc 2>/dev/null || echo 1)"
# cpu.max = "<quota> <periodo>" (ou "max"): e o teto real quando o container tem
# limite de CPU (cpulimit no Proxmox), que o nproc sozinho nao mostra.
[ -r "$CG/cpu.max" ] && printf 'cpumax|%s\n' "$(cat "$CG/cpu.max")"
printf 'tick|%s\n' "$(getconf CLK_TCK 2>/dev/null || echo 100)"
printf 'load|%s\n' "$(cut -d' ' -f1-3 /proc/loadavg)"
printf 'boot|%s\n' "$(awk '{ print $1; exit }' /proc/uptime)"
awk '/^MemTotal:|^MemAvailable:|^SwapTotal:|^SwapFree:/ { printf "meminfo|%s|%s\n", $1, $2 }' /proc/meminfo
# Em container o cgroup e mais honesto que o /proc/meminfo quando nao ha lxcfs.
[ -r "$CG/memory.current" ] && printf 'cgmem|%s|%s\n' \
  "$(cat "$CG/memory.current")" "$(cat "$CG/memory.max" 2>/dev/null || echo max)"
df -P -B1 / "$dir" 2>/dev/null | awk 'NR>1 { printf "disk|%s|%s|%s\n", $6, $2, $3 }'
printf 'proc|%s|%s\n' "$pid" \
  "$(awk '/^VmRSS:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || echo 0)"
"""


def _num(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(max(0.0, min(100.0, part * 100.0 / whole)), 1)


# Uma funcao por linha que o script remoto emite. A chave e a etiqueta da linha e o
# numero e quantos campos ela precisa ter para valer (linha curta e descartada).
def _tag_sample(dados, parts):
    # uptime | cpu_usec | stat_total | stat_idle | rx | tx | ticks do processo
    dados["samples"].append(parts[1:])


def _tag_cores(dados, parts):
    dados["cores"] = max(1.0, _num(parts[1], 1))


def _tag_cpumax(dados, parts):
    quota, _, periodo = parts[1].strip().partition(" ")
    if quota != "max" and _num(periodo) > 0:
        dados["cores"] = max(0.1, _num(quota) / _num(periodo))


def _tag_tick(dados, parts):
    dados["clk_tck"] = max(1.0, _num(parts[1], 100))


def _tag_load(dados, parts):
    dados["load"] = parts[1]


def _tag_boot(dados, parts):
    dados["uptime"] = _num(parts[1])


def _tag_meminfo(dados, parts):
    dados["meminfo"][parts[1].rstrip(":")] = _num(parts[2]) * 1024  # vem em kB


def _tag_cgmem(dados, parts):
    dados["cg_current"] = _num(parts[1])
    dados["cg_max"] = None if parts[2].strip() == "max" else _num(parts[2])


def _tag_disk(dados, parts):
    dados["disks"][parts[1]] = {
        "mount": parts[1], "total": _num(parts[2]), "used": _num(parts[3]),
        "pct": _pct(_num(parts[3]), _num(parts[2])),
    }


def _tag_proc(dados, parts):
    dados["pid"] = int(_num(parts[1]))
    dados["rss_kb"] = _num(parts[2])


METRIC_TAGS = {
    "sample": (8, _tag_sample),
    "cores": (2, _tag_cores),
    "cpumax": (2, _tag_cpumax),
    "tick": (2, _tag_tick),
    "load": (2, _tag_load),
    "boot": (2, _tag_boot),
    "meminfo": (3, _tag_meminfo),
    "cgmem": (3, _tag_cgmem),
    "disk": (4, _tag_disk),
    "proc": (3, _tag_proc),
}


def _collect_metrics(raw: str) -> dict:
    """Primeira passada: cada linha do script vira uma entrada crua, sem contas."""
    dados: dict = {
        "samples": [], "meminfo": {}, "disks": {},
        "cores": 1.0, "clk_tck": 100.0, "load": "", "uptime": 0.0,
        "cg_current": None, "cg_max": None, "pid": 0, "rss_kb": 0.0,
    }
    for line in raw.splitlines():
        parts = line.split("|")
        minimo, trata = METRIC_TAGS.get(parts[0], (0, None))
        if trata and len(parts) >= minimo:
            trata(dados, parts)
    return dados


def _rates_from_samples(dados: dict) -> dict:
    """CPU e rede saem da diferenca entre as duas amostras."""
    saida = {"cpu_pct": None, "net_rx": None, "net_tx": None, "proc_cpu_pct": None}
    samples = dados["samples"]
    if len(samples) < 2:
        return saida

    a, b = samples[0], samples[-1]
    dt = _num(b[0]) - _num(a[0])
    if dt <= 0:
        return saida

    cores = dados["cores"]
    # cpu.stat do cgroup mede o container; /proc/stat so acerta com lxcfs no meio.
    if a[1] != "-" and b[1] != "-":
        saida["cpu_pct"] = _pct((_num(b[1]) - _num(a[1])) / 1e6, dt * cores)
    else:
        total = _num(b[2]) - _num(a[2])
        saida["cpu_pct"] = _pct(total - (_num(b[3]) - _num(a[3])), total)

    saida["net_rx"] = max(0.0, (_num(b[4]) - _num(a[4])) / dt)
    saida["net_tx"] = max(0.0, (_num(b[5]) - _num(a[5])) / dt)
    if dados["pid"]:
        usados = (_num(b[6]) - _num(a[6])) / dados["clk_tck"]
        saida["proc_cpu_pct"] = _pct(usados, dt * cores)
    return saida


def _memory_from(dados: dict) -> dict:
    total = dados["meminfo"].get("MemTotal", 0.0)
    usada = max(0.0, total - dados["meminfo"].get("MemAvailable", 0.0))
    atual, teto = dados["cg_current"], dados["cg_max"]
    # Limite do cgroup manda quando existe e e menor que a RAM da maquina: e o teto real
    # do container, e o /proc/meminfo sem lxcfs mostraria a memoria do host inteiro.
    if atual is not None and teto and (not total or teto < total):
        total, usada = teto, atual
    elif atual is not None and not total:
        total, usada = atual, atual
    return {"total": total, "used": usada, "pct": _pct(usada, total)}


def _parse_metrics(raw: str) -> dict:
    """Transforma a saida do script acima em numeros prontos para a tela."""
    dados = _collect_metrics(raw)
    taxas = _rates_from_samples(dados)
    cores = dados["cores"]
    meminfo = dados["meminfo"]

    out: dict = {
        # Pode ser fracionario quando o container tem limite de CPU (ex.: 1.5 nucleos).
        "cores": int(cores) if cores == int(cores) else round(cores, 1),
        "load": dados["load"], "uptime": dados["uptime"],
        "disks": sorted(dados["disks"].values(), key=lambda d: d["mount"]),
        "cpu_pct": taxas["cpu_pct"],
        "net_rx": taxas["net_rx"], "net_tx": taxas["net_tx"],
        "proc": {
            "pid": dados["pid"],
            "rss": dados["rss_kb"] * 1024,
            "cpu_pct": taxas["proc_cpu_pct"],
        },
        "mem": _memory_from(dados),
    }

    swap_total = meminfo.get("SwapTotal", 0.0)
    swap_usado = max(0.0, swap_total - meminfo.get("SwapFree", 0.0))
    out["swap"] = {"total": swap_total, "used": swap_usado, "pct": _pct(swap_usado, swap_total)}
    return out


_metrics_cache: dict[int, tuple[float, dict]] = {}
_metrics_lock = threading.Lock()


def server_metrics(server: sqlite3.Row, force: bool = False) -> dict:
    """Uso de CPU, memoria, disco e rede do container. Cache curto para varias abas
    abertas na mesma tela nao virarem varias sessoes de SSH por segundo."""
    key = int(server["id"])
    agora = time.monotonic()
    if not force:
        with _metrics_lock:
            cached = _metrics_cache.get(key)
        if cached and agora - cached[0] < METRICS_TTL:
            return cached[1]

    alvo = server["config_path"] or FILE_DEFAULT_PATH
    try:
        raw = ssh_output(
            server, q("bash", "-lc", METRICS_SCRIPT, "gp", server["service"], alvo), timeout=30
        )
        data = _parse_metrics(raw)
        data["error"] = ""
    except RemoteError as exc:
        data = {"error": str(exc)}

    with _metrics_lock:
        _metrics_cache[key] = (agora, data)
    return data


def all_metrics(servers) -> dict[int, dict]:
    """Igual ao all_status: em serie, cinco servidores custariam cinco vezes mais."""
    results: dict[int, dict] = {}
    lock = threading.Lock()

    def work(srv):
        data = server_metrics(srv)
        with lock:
            results[int(srv["id"])] = data

    threads = [threading.Thread(target=work, args=(s,), daemon=True) for s in servers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=35)
    for srv in servers:
        results.setdefault(int(srv["id"]), {"error": MSG_TIMEOUT})
    return results


# --------------------------------------------------------------- status cache

_status_cache: dict[int, tuple[float, dict]] = {}
_status_lock = threading.Lock()


def server_status(server: sqlite3.Row, force: bool = False) -> dict:
    key = int(server["id"])
    now = time.monotonic()
    if not force:
        with _status_lock:
            cached = _status_cache.get(key)
        if cached and now - cached[0] < STATUS_TTL:
            return cached[1]

    state = {"reachable": False, "service": "desconhecido", "error": ""}
    try:
        # `is-active` sai !=0 quando o servico esta parado, e isso nao e erro de conexao:
        # o '|| true' garante que so uma falha de SSH de verdade caia no except.
        raw = ssh_output(
            server, q("systemctl", "is-active", server["service"]) + " || true"
        )
        state["reachable"] = True
        state["service"] = raw.splitlines()[-1].strip() if raw else "inactive"
    except RemoteError as exc:
        state["error"] = str(exc)
        state["service"] = "inacessivel"

    with _status_lock:
        _status_cache[key] = (now, state)
    return state


def invalidate_status(server_id: int) -> None:
    with _status_lock:
        _status_cache.pop(int(server_id), None)


def all_status(servers) -> dict[int, dict]:
    """Consulta em paralelo — com 5 servidores o serial levaria ~10s por pageload."""
    results: dict[int, dict] = {}
    lock = threading.Lock()

    def work(srv):
        state = server_status(srv)
        with lock:
            results[int(srv["id"])] = state

    threads = [threading.Thread(target=work, args=(s,), daemon=True) for s in servers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=QUICK_TIMEOUT + 5)
    for srv in servers:
        results.setdefault(
            int(srv["id"]),
            {"reachable": False, "service": "desconhecido", "error": MSG_TIMEOUT},
        )
    return results


# ------------------------------------------------------------------- jobs

# chave -> (rotulo, monta o comando remoto, pede confirmacao na UI)
ACTIONS = {
    "start": ("Iniciar servidor", lambda s: q("systemctl", "start", s["service"]), False),
    "restart": ("Reiniciar servidor", lambda s: q("systemctl", "restart", s["service"]), True),
    "stop": ("Parar servidor", lambda s: q("systemctl", "stop", s["service"]), True),
    "update": ("Atualizar jogo (SteamCMD)", lambda s: "/usr/local/bin/update-game", True),
    "check-update": ("Checar update", lambda s: "/usr/local/bin/check-game-update", False),
}

JOB_LABELS = {key: label for key, (label, _cmd, _c) in ACTIONS.items()}
JOB_LABELS["shell"] = "Comando no container"
JOB_LABELS["terminal"] = "Terminal interativo"
JOB_LABELS["edit-file"] = "Arquivo salvo"
JOB_LABELS["delete-file"] = "Arquivo apagado"
JOB_LABELS["edit-config"] = "Configuracao alterada"
JOB_LABELS["download-file"] = "Arquivo baixado"


def job_label(action: str) -> str:
    return JOB_LABELS.get(action, action)


def log_job(
    action: str,
    server: sqlite3.Row | dict,
    username: str,
    command: str = "",
    output: str = "",
    status: str = "ok",
) -> int:
    """Registra no historico algo que ja aconteceu (edicao de arquivo, sessao de
    terminal). Diferente de start_job, nao dispara nada — so deixa o rastro."""
    conn = db()
    with conn:
        cur = conn.execute(
            "INSERT INTO jobs (server_id, target, action, status, exit_code, output,"
            " command, username, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                server["id"], f"{server['ssh_user']}@{server['host']}", action, status,
                0 if status == "ok" else None, output[-200000:], command, username,
                now_iso(), now_iso(),
            ),
        )
    return int(cur.lastrowid)


def start_job(
    action: str,
    server: sqlite3.Row,
    username: str,
    remote_cmd: str | None = None,
    command: str = "",
    timeout: int = JOB_TIMEOUT,
) -> int:
    if remote_cmd is None:
        remote_cmd = ACTIONS[action][1](server)
    conn = db()
    with conn:
        cur = conn.execute(
            "INSERT INTO jobs (server_id, target, action, status, command, username,"
            " created_at) VALUES (?,?,?,?,?,?,?)",
            (
                server["id"], f"{server['ssh_user']}@{server['host']}", action,
                "running", command, username, now_iso(),
            ),
        )
    job_id = int(cur.lastrowid)
    server_id = int(server["id"])
    # A thread nao pode usar a Row ligada a conexao do request: copia o que precisa.
    target = dict(server)

    def run():
        try:
            proc = ssh_run(target, remote_cmd, timeout=timeout)
            output = (proc.stdout or "") + (proc.stderr or "")
            status = "ok" if proc.returncode == 0 else "error"
            code = proc.returncode
        except RemoteError as exc:
            output, status, code = str(exc), "error", None
        # Conexao propria: esta thread vive fora do contexto do request.
        conn2 = _connect()
        with conn2:
            conn2.execute(
                "UPDATE jobs SET status=?, exit_code=?, output=?, finished_at=?"
                " WHERE id=?",
                (status, code, output.strip()[-200000:], now_iso(), job_id),
            )
        conn2.close()
        invalidate_status(server_id)

    threading.Thread(target=run, daemon=True).start()
    return job_id


# ------------------------------------------------------------------- rotas


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = f"{request.remote_addr}|{username.lower()}"
        remaining = _lockout_remaining(key)
        if remaining:
            flash(f"Muitas tentativas. Tente de novo em {remaining}s.", "error")
            return render_template(TPL_LOGIN), 429
        row = db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row and verify_password(password, row["password_hash"]):
            _clear_fails(key)
            session.clear()
            session["uid"] = row["id"]
            session["username"] = row["username"]
            session.permanent = True
            csrf_token()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") else url_for("dashboard"))
        _record_fail(key)
        flash("Usuario ou senha invalidos.", "error")
        return render_template(TPL_LOGIN), 401
    return render_template(TPL_LOGIN)


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def dashboard():
    servers = db().execute(SQL_ALL_SERVERS).fetchall()
    return render_template(
        "dashboard.html", servers=servers, status=all_status(servers), actions=ACTIONS
    )


@app.get("/api/status")
@login_required
def api_status():
    servers = db().execute(SQL_ALL_SERVERS).fetchall()
    return jsonify({str(sid): state for sid, state in all_status(servers).items()})


@app.get("/api/metrics")
@login_required
def api_metrics():
    """Medidores de todos os servidores — alimenta os mini-graficos do painel."""
    servers = db().execute(SQL_ALL_SERVERS).fetchall()
    return jsonify({str(sid): data for sid, data in all_metrics(servers).items()})


@app.get("/api/players")
@login_required
def api_players():
    servers = db().execute(SQL_ALL_SERVERS).fetchall()
    return jsonify({str(sid): data for sid, data in all_players(servers).items()})


@app.get("/api/servers/<int:sid>/players")
@login_required
def api_server_players(sid: int):
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    return jsonify(server_players(server))


def _aba_porta(server: sqlite3.Row) -> dict:
    """Aba 1: dispara A2S em cada porta UDP que o container esta escutando."""
    candidatas, _tcp, donos, aviso = candidate_ports(server)
    portas = _com_dono(probe_ports(server["host"], candidatas[:12]), donos, "udp")
    # Porta aberta pelo processo do jogo e que nao respondeu A2S e uma conclusao, nao um
    # erro: o jogo simplesmente nao publica consulta. Sem essa contagem a tela so diria
    # "sem resposta" e deixaria a duvida entre "porta errada" e "nao existe consulta".
    do_jogo = [p for p in portas if p["origem"] == "detectada" and not p["infra"]]
    return {
        "portas": portas,
        "aviso": aviso,
        "udp_do_jogo": len(do_jogo),
        "udp_mudas": bool(do_jogo) and not any(p["ok"] for p in do_jogo),
    }


def _aba_http(server: sqlite3.Row, http: dict, testar: bool) -> dict:
    """Aba 2: quais portas TCP falam HTTP, e o teste da URL escolhida."""
    _udp, candidatas, donos, aviso = candidate_ports(server)
    achados, mudas, erro_probe = probe_http_ports(server, candidatas)
    _com_dono(achados, donos, "tcp")
    mudas = _com_dono([{"port": p} for p in mudas], donos, "tcp")
    saida = {"achados": achados, "mudas": mudas, "aviso": aviso or erro_probe,
             # Achado que vale um clique: porta que respondeu numa rota conhecida. Sem
             # nenhum, a tela explica que a API costuma vir desligada de fabrica.
             "tem_api": any(not a.get("generico") for a in achados),
             "teste_http": None, "erro_http": ""}
    if not testar:
        return saida
    try:
        # O teste usa os valores do FORMULARIO, nao os do banco: e o unico jeito de
        # conferir o login antes de salvar. Por isso monta-se uma linha temporaria.
        provisorio = dict(server)
        provisorio.update(http)
        if (http.get("http_login_url") or "").strip() and (http.get("http_token_path") or "").strip():
            token = http_login(provisorio)
            auth = f"bearer:{token}"
        else:
            auth = http["http_auth"]
        dados = http_json(server, http["http_url"], auth, http["http_body"])
        teste = read_players_json(dados, http["http_list_path"], http["http_count_path"])
        # A resposta crua ajuda a preencher os caminhos quando a busca automatica erra.
        teste["amostra"] = json.dumps(dados, indent=2, ensure_ascii=False)[:4000]
        saida["teste_http"] = teste
    except QueryError as exc:
        saida["erro_http"] = str(exc)
    return saida


def _aba_log(server: sqlite3.Row, join_re: str, leave_re: str, testar: bool) -> dict:
    """Aba 3: linhas do log com cara de entrada/saida e o teste dos padroes."""
    saida = {"amostras": [], "teste": None, "erro_log": ""}
    try:
        linhas = read_log_lines(server)
        chaves = re.compile("|".join(LOG_HINT_WORDS), re.I)
        amostras = [ln for ln in linhas if chaves.search(ln)][-120:]
        saida["amostras"] = amostras
        if not testar:
            return saida
        entrar = compile_pattern(join_re, "entrada")
        if not entrar:
            raise QueryError("informe o padrao da linha de entrada")
        sair = compile_pattern(leave_re, "saida")
        teste = _apply_log_events(linhas, entrar, sair)
        teste["casaram"] = [
            ln for ln in amostras
            if entrar.search(ln[:LOG_LINE_MAX]) or (sair and sair.search(ln[:LOG_LINE_MAX]))
        ][-20:]
        saida["teste"] = teste
    except (RemoteError, QueryError) as exc:
        saida["erro_log"] = str(exc)
    return saida


@app.get("/servers/<int:sid>/players/descobrir")
@admin_required
def players_setup(sid: int):
    """Assistente: acha a porta/API que responde e ajuda a achar o padrao no log."""
    server = _server_or_404(sid)
    aba = request.args.get("aba", "porta")
    testar = bool(request.args.get("testar"))

    # Os campos das tres abas viajam pela URL para o botao "Testar" nao perder o que
    # ja foi digitado.
    http = {campo: request.args.get(campo, server[campo]) for campo in HTTP_FIELDS}
    join_re = request.args.get("join_re", server["join_re"])
    leave_re = request.args.get("leave_re", server["leave_re"])

    dados = {"portas": [], "aviso": "", "achados": [], "mudas": [], "amostras": [],
             "tem_api": False, "udp_do_jogo": 0, "udp_mudas": False,
             "teste": None, "teste_http": None, "erro_log": "", "erro_http": ""}
    if aba == "http":
        dados.update(_aba_http(server, http, testar))
    elif aba == "log":
        dados.update(_aba_log(server, join_re, leave_re, testar))
    else:
        dados.update(_aba_porta(server))

    return render_template(
        "players_setup.html", server=server, aba=aba,
        http=http, join_re=join_re, leave_re=leave_re, **dados,
    )


@app.post("/servers/<int:sid>/players/usar")
@admin_required
def players_use(sid: int):
    """Grava a forma de contagem escolhida no assistente."""
    server = _server_or_404(sid)
    origem = request.form.get("player_source", "")
    conn = db()
    if origem == "a2s":
        porta = request.form.get("query_port", "0")
        if not porta.isdigit() or not 1 <= int(porta) <= 65535:
            flash("Porta invalida.", "error")
            return redirect(url_for("players_setup", sid=sid))
        with conn:
            conn.execute(
                "UPDATE servers SET query_port = ?, player_source = 'a2s' WHERE id = ?",
                (int(porta), sid),
            )
        flash(f"Contagem de jogadores ligada pela consulta na porta {porta}/udp.", "ok")
    elif origem == "http":
        errors: list[str] = []
        campos = _campos_http(request.form, errors)
        if errors or not campos["http_url"]:
            flash(errors[0] if errors else "Informe a URL da API.", "error")
            return redirect(url_for("players_setup", sid=sid, aba="http"))
        with conn:
            conn.execute(
                "UPDATE servers SET http_url=?, http_auth=?, http_body=?,"
                " http_list_path=?, http_count_path=?,"
                " http_login_url=?, http_login_body=?, http_token_path=?,"
                # Token guardado zera ao salvar: se a URL/credencial mudou, o antigo
                # nao vale mais, e a proxima consulta ja faz login com o que ficou.
                " http_token='', player_source='http' WHERE id=?",
                (*[campos[c] for c in HTTP_FIELDS], sid),
            )
        if campos["http_login_url"]:
            flash("Contagem ligada pela API, com login automatico (o token renova sozinho).", "ok")
        else:
            flash("Contagem de jogadores ligada pela API HTTP do servidor.", "ok")
    elif origem == "log":
        errors: list[str] = []
        entrada = _padrao(request.form.get("join_re"), "entrada", errors)
        saida = _padrao(request.form.get("leave_re"), "saida", errors)
        if errors or not entrada:
            flash(errors[0] if errors else "Informe o padrao da linha de entrada.", "error")
            return redirect(url_for("players_setup", sid=sid, aba="log"))
        with conn:
            conn.execute(
                "UPDATE servers SET join_re = ?, leave_re = ?, player_source = 'log' WHERE id = ?",
                (entrada, saida, sid),
            )
        flash("Contagem de jogadores ligada pelo log do servidor.", "ok")
    else:
        flash("Escolha invalida.", "error")
        return redirect(url_for("players_setup", sid=sid))

    with _players_lock:
        _players_cache.pop(sid, None)
    return redirect(url_for("server_detail", sid=sid))


@app.get("/api/servers/<int:sid>/metrics")
@login_required
def api_server_metrics(sid: int):
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    data = server_metrics(server)
    return jsonify(data), (502 if data.get("error") else 200)


def _porta(valor: str, padrao: int, minimo: int, erro: str, errors: list[str]) -> int:
    """Le uma porta do formulario; `minimo` 0 permite desligar o recurso."""
    bruto = (valor or "").strip() or str(padrao)
    if bruto.isdigit() and minimo <= int(bruto) <= 65535:
        return int(bruto)
    errors.append(erro)
    return padrao


def _servico(valor: str, errors: list[str]) -> str:
    service = (valor or "").strip()
    if service and not service.endswith(".service"):
        service = f"{service}.service"  # o sufixo e o de sempre: nao vale incomodar
    if not UNIT_RE.match(service):
        errors.append("Servico invalido (ex.: dragonwilds.service).")
    return service


def _pasta_config(valor: str, errors: list[str]) -> str:
    caminho = (valor or "").strip()[:400]
    if not caminho:
        return ""
    try:
        return clean_path(caminho)
    except ValueError as exc:
        errors.append(f"Pasta de configuracao invalida: {exc}")
        return ""


def _arquivos_config(valor: str, errors: list[str]) -> str:
    """Le a lista de arquivos de configuracao (um caminho absoluto por linha)."""
    caminhos: list[str] = []
    for linha in (valor or "").replace(",", "\n").splitlines():
        bruto = linha.strip()
        if not bruto:
            continue
        try:
            limpo = clean_path(bruto)
        except ValueError as exc:
            errors.append(f"Arquivo de configuracao invalido ({bruto}): {exc}")
            continue
        if limpo not in caminhos:
            caminhos.append(limpo)
    if len(caminhos) > CONFIG_FILES_MAX:
        errors.append(f"No maximo {CONFIG_FILES_MAX} arquivos de configuracao por servidor.")
        caminhos = caminhos[:CONFIG_FILES_MAX]
    return "\n".join(caminhos)


CAMINHO_JSON_RE = re.compile(r"^[A-Za-z0-9_.\[\]-]{0,120}$")


def _campos_http(form, errors: list[str]) -> dict:
    """Le e confere os campos da chamada HTTP (URL, autenticacao, corpo, caminhos)."""
    url = (form.get("http_url", "") or "").strip()[:HTTP_URL_MAX]
    if url and not URL_RE.match(url):
        errors.append("URL da API invalida (ex.: http://127.0.0.1:8212/v1/api/players).")
        url = ""

    corpo = (form.get("http_body", "") or "").strip()[:HTTP_BODY_MAX]
    if corpo:
        try:
            json.loads(corpo)
        except ValueError as exc:
            errors.append(f"Corpo da requisicao nao e JSON valido: {exc}.")
            corpo = ""

    caminhos = {}
    for campo, rotulo in (("http_list_path", "lista"), ("http_count_path", "contagem"),
                          ("http_token_path", "token")):
        texto = (form.get(campo, "") or "").strip()[:HTTP_PATH_MAX]
        if texto and not CAMINHO_JSON_RE.match(texto):
            errors.append(f"Caminho da {rotulo} invalido (use algo como 'data.players').")
            texto = ""
        caminhos[campo] = texto

    # Login automatico: os tres campos andam juntos. Preencher so parte deles quase
    # sempre e engano, e falhar aqui e melhor do que descobrir na hora da consulta.
    login_url = (form.get("http_login_url", "") or "").strip()[:HTTP_URL_MAX]
    if login_url and not URL_RE.match(login_url):
        errors.append("URL de login invalida (ex.: https://127.0.0.1:7787/api/v1).")
        login_url = ""
    login_body = (form.get("http_login_body", "") or "").strip()[:HTTP_BODY_MAX]
    if login_body:
        try:
            json.loads(login_body)
        except ValueError as exc:
            errors.append(f"Corpo do login nao e JSON valido: {exc}.")
            login_body = ""
    if (login_url or login_body) and not caminhos["http_token_path"]:
        errors.append("Para o login automatico, informe tambem o caminho do token "
                      "(ex.: data.authenticationToken).")

    return {
        "http_url": url,
        "http_login_url": login_url,
        "http_login_body": login_body,
        # Guarda a senha da API como ela precisa ser mandada. O banco do painel ja da
        # acesso de root aos containers, entao isso nao amplia o estrago de um vazamento
        # — mas trate o arquivo panel.db como segredo.
        "http_auth": (form.get("http_auth", "") or "").strip()[:300],
        "http_body": corpo,
        **caminhos,
    }


def _padrao(valor: str, rotulo: str, errors: list[str]) -> str:
    """Guarda o regex so depois de conferir que ele compila."""
    texto = (valor or "").strip()[:RE_MAX_LEN]
    if not texto:
        return ""
    try:
        compile_pattern(texto, rotulo)
    except QueryError as exc:
        errors.append(str(exc))
        return ""
    return texto


def _form_server(form) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = form.get("name", "").strip()
    host = form.get("host", "").strip()
    ssh_user = form.get("ssh_user", "").strip() or "root"
    origem = (form.get("player_source", "") or "").strip()
    if origem and origem not in PLAYER_SOURCES:
        errors.append("Forma de contar jogadores invalida.")
        origem = ""

    if not name:
        errors.append("Informe um nome.")
    if not HOST_RE.match(host):
        errors.append("Host invalido (use o IP ou hostname do container).")
    if not USER_RE.match(ssh_user):
        errors.append("Usuario SSH invalido.")

    return (
        {
            "name": name,
            "host": host,
            "ssh_user": ssh_user,
            "ssh_port": _porta(form.get("ssh_port"), 22, 1, "Porta SSH invalida.", errors),
            "service": _servico(form.get("service"), errors),
            "game_port": form.get("game_port", "").strip()[:120],
            "notes": form.get("notes", "").strip()[:2000],
            "config_path": _pasta_config(form.get("config_path"), errors),
            "config_files": _arquivos_config(form.get("config_files"), errors),
            "query_port": _porta(
                form.get("query_port"), 0, 0,
                "Porta de consulta invalida (use 0 para desligar).", errors,
            ),
            "player_source": origem,
            "join_re": _padrao(form.get("join_re"), "entrada", errors),
            "leave_re": _padrao(form.get("leave_re"), "saida", errors),
            **_campos_http(form, errors),
        },
        errors,
    )


# Colunas que o formulario preenche, na mesma ordem do INSERT/UPDATE abaixo. Manter a
# lista em um lugar so evita o classico "acrescentei a coluna e esqueci de um dos SQLs".
SERVER_FIELDS = (
    "name", "host", "ssh_port", "ssh_user", "service", "game_port", "notes",
    "config_path", "config_files", "query_port", "player_source", "join_re", "leave_re",
    *HTTP_FIELDS,
)
SQL_INSERT_SERVER = (
    f"INSERT INTO servers ({', '.join(SERVER_FIELDS)}, created_at)"
    f" VALUES ({', '.join('?' * (len(SERVER_FIELDS) + 1))})"
)
SQL_UPDATE_SERVER = (
    f"UPDATE servers SET {', '.join(c + '=?' for c in SERVER_FIELDS)} WHERE id=?"
)


@app.route("/servers/new", methods=["GET", "POST"])
@admin_required
def server_new():
    data = dict.fromkeys(SERVER_FIELDS, "")
    data.update({"ssh_user": "root", "ssh_port": 22, "query_port": 0})
    if request.method == "POST":
        data, errors = _form_server(request.form)
        if not errors:
            try:
                conn = db()
                with conn:
                    conn.execute(
                        SQL_INSERT_SERVER,
                        (*[data[c] for c in SERVER_FIELDS], now_iso()),
                    )
                flash(f"Servidor {data['name']} cadastrado.", "ok")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                errors.append(f"Ja existe um servidor cadastrado em {data['host']}.")
        for err in errors:
            flash(err, "error")
    return render_template("server_form.html", data=data, mode="new")


@app.route("/servers/<int:sid>/edit", methods=["GET", "POST"])
@admin_required
def server_edit(sid: int):
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    data = dict(server)
    if request.method == "POST":
        data, errors = _form_server(request.form)
        if not errors:
            try:
                conn = db()
                with conn:
                    conn.execute(
                        SQL_UPDATE_SERVER, (*[data[c] for c in SERVER_FIELDS], sid)
                    )
                invalidate_status(sid)
                # A contagem fica em cache por alguns segundos: trocar a fonte pelo
                # formulario tem que valer na hora, como vale pelo assistente.
                with _players_lock:
                    _players_cache.pop(sid, None)
                flash("Servidor atualizado.", "ok")
                return redirect(url_for("server_detail", sid=sid))
            except sqlite3.IntegrityError:
                errors.append(f"Ja existe um servidor cadastrado em {data['host']}.")
        for err in errors:
            flash(err, "error")
    return render_template("server_form.html", data=data, mode="edit", sid=sid)


@app.post("/servers/<int:sid>/delete")
@admin_required
def server_delete(sid: int):
    conn = db()
    with conn:
        conn.execute("DELETE FROM servers WHERE id = ?", (sid,))
    invalidate_status(sid)
    flash("Servidor removido do painel (o container nao foi tocado).", "ok")
    return redirect(url_for("dashboard"))


@app.get("/servers/<int:sid>")
@login_required
def server_detail(sid: int):
    conn = db()
    server = conn.execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    jobs = conn.execute(
        "SELECT * FROM jobs WHERE server_id = ? ORDER BY id DESC LIMIT 15", (sid,)
    ).fetchall()
    lines = _log_lines_arg(request.args.get("lines"))
    logs, log_cursor, log_error = "", "", ""
    try:
        logs, log_cursor = read_logs(server, lines)
    except RemoteError as exc:
        log_error = str(exc)
    return render_template(
        "server_detail.html",
        server=server,
        status=server_status(server),
        metrics=server_metrics(server),
        players=server_players(server),
        jobs=jobs,
        logs=logs,
        log_cursor=log_cursor,
        log_error=log_error,
        lines=lines,
        actions=ACTIONS,
    )


# O cursor e uma chave opaca do journald ("s=...;i=...;b=..."): validada aqui porque
# volta do navegador e entra num comando remoto.
CURSOR_RE = re.compile(r"^[A-Za-z0-9=;:._-]{1,400}$")
LOG_FOLLOW_MAX = 500


def _log_lines_arg(raw: str, default: int = 80) -> int:
    try:
        return max(10, min(500, int(raw)))
    except (TypeError, ValueError):
        return default


def read_logs(server: sqlite3.Row, lines: int, cursor: str = "") -> tuple[str, str]:
    """Le o log do servico. Com cursor, traz so o que entrou depois dele.

    Devolve (texto, novo_cursor). O cursor vem vazio quando o journalctl do container
    nao souber emiti-lo — nesse caso a tela recarrega o bloco inteiro a cada volta.
    """
    if cursor and CURSOR_RE.match(cursor):
        cmd = q(
            "journalctl", "-u", server["service"], "--no-pager", "--show-cursor",
            "--after-cursor", cursor, "-n", str(LOG_FOLLOW_MAX),
        )
    else:
        cmd = q(
            "journalctl", "-u", server["service"], "--no-pager", "--show-cursor",
            "-n", str(lines),
        )
    raw = ssh_output(server, cmd, timeout=30)

    out = raw.splitlines()
    new_cursor = ""
    if out and out[-1].startswith("-- cursor:"):
        new_cursor = out.pop().split(":", 1)[1].strip()
    body = "\n".join(ln for ln in out if ln.strip() != "-- No entries --")
    return body, new_cursor


@app.get("/api/servers/<int:sid>/logs")
@login_required
def api_logs(sid: int):
    """Alimenta o "seguir log" da tela de detalhe."""
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    # Cursor recusado (adulterado, ou de um journalctl que nao os emite) vira leitura
    # completa: sem isso o cliente anexaria o log inteiro por cima do que ja esta na tela.
    cursor = request.args.get("cursor", "")
    if not CURSOR_RE.match(cursor or ""):
        cursor = ""
    try:
        text, new_cursor = read_logs(server, _log_lines_arg(request.args.get("lines")), cursor)
    except RemoteError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({
        "text": text,
        "cursor": new_cursor,
        # Sem cursor (primeira volta, ou journalctl antigo) o cliente troca o bloco
        # inteiro; com cursor ele so anexa as linhas novas.
        "append": bool(cursor and new_cursor),
    })


@app.post("/servers/<int:sid>/action/<action>")
@login_required
def server_action(sid: int, action: str):
    if action not in ACTIONS:
        abort(404)
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    job_id = start_job(action, server, session.get("username", "?"))
    invalidate_status(sid)
    return redirect(url_for("job_detail", jid=job_id))


# ------------------------------------------------------------------ console


@app.route("/servers/<int:sid>/console", methods=["GET", "POST"])
@admin_required
def console(sid: int):
    if not ALLOW_SHELL:
        abort(403, "O console esta desabilitado (GAMEPANEL_ALLOW_SHELL=0).")
    conn = db()
    server = conn.execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)

    if request.method == "POST":
        command = request.form.get("command", "").strip()
        if not command:
            flash("Digite um comando.", "error")
        elif len(command) > SHELL_MAX_LEN:
            flash(f"Comando muito longo (limite de {SHELL_MAX_LEN} caracteres).", "error")
        else:
            # O comando inteiro vira UM argumento de 'bash -lc' no destino — o shell
            # local do ssh nunca o interpreta, entao pipes e aspas chegam intactos.
            job_id = start_job(
                "shell",
                server,
                session.get("username", "?"),
                remote_cmd=q("bash", "-lc", command),
                command=command,
                timeout=SHELL_TIMEOUT,
            )
            return redirect(url_for("console", sid=sid, job=job_id))

    job = None
    job_arg = request.args.get("job", "")
    if job_arg.isdigit():
        job = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND server_id = ?", (int(job_arg), sid)
        ).fetchone()
    history = conn.execute(
        "SELECT * FROM jobs WHERE server_id = ? AND action = 'shell'"
        " ORDER BY id DESC LIMIT 20",
        (sid,),
    ).fetchall()
    return render_template(
        "console.html", server=server, job=job, history=history,
        shell_timeout=SHELL_TIMEOUT,
    )


# ------------------------------------------------------- terminal interativo

TERM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


def _become_tty_leader() -> None:
    """Roda no filho, entre fork e exec: sessao nova + PTY como terminal de controle.

    Sem o TIOCSCTTY o ssh enxerga um terminal que nao e o dele e recusa o modo raw,
    e o teclado passa a chegar em blocos de linha em vez de tecla a tecla.
    """
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class TermSession:
    """Uma sessao SSH interativa viva: um `ssh -tt` amarrado a um PTY local.

    O navegador nao fala com o PTY direto — empurra teclas por POST e puxa a saida por
    long-poll, dizendo por um offset em bytes o que ja leu. Sem WebSocket de proposito:
    o painel roda em gunicorn com workers sync, que nao os suporta.
    """

    def __init__(self, server: dict, uid: int, username: str, cols: int, rows: int):
        self.id = secrets.token_urlsafe(24)
        self.uid = uid
        self.username = username
        self.server_id = int(server["id"])
        self.opened_at = time.time()
        self.last_seen = time.time()
        self.cols, self.rows = cols, rows
        self.alive = True
        self.exit_code: int | None = None

        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._wake = threading.Event()
        self._buf = bytearray()
        self._base = 0  # offset absoluto do primeiro byte ainda guardado

        self.master, slave = pty.openpty()
        try:
            _set_winsize(self.master, cols, rows)
            argv = ssh_argv(
                server,
                extra=("-tt", "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3"),
            )
            # Ambiente minimo e explicito: e o TERM daqui que decide os codigos que o
            # emulador do navegador vai ter de entender.
            env = {
                "TERM": "xterm-256color",
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                # O ssh so usa o HOME para procurar ~/.ssh, e aqui a chave e o
                # known_hosts vao explicitos; a pasta de dados serve de porto seguro.
                "HOME": os.environ.get("HOME") or os.path.dirname(KNOWN_HOSTS),
                "LANG": "C.UTF-8",
            }
            self.proc = subprocess.Popen(
                argv, stdin=slave, stdout=slave, stderr=slave,
                close_fds=True, preexec_fn=_become_tty_leader, env=env,
            )
        except OSError as exc:
            os.close(self.master)
            raise RemoteError(f"falha ao abrir a sessao: {exc}")
        finally:
            os.close(slave)

        threading.Thread(target=self._reader, daemon=True).start()

    # -- saida ------------------------------------------------------------
    def _reader(self) -> None:
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:  # PTY fechou = ssh terminou
                break
            with self._lock:
                self._buf += chunk
                excess = len(self._buf) - TERM_BUFFER_BYTES
                if excess > 0:
                    del self._buf[:excess]
                    self._base += excess
            self._wake.set()
        try:
            self.exit_code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.exit_code = None
        self.alive = False
        self._wake.set()

    def read(self, offset: int, wait: float = TERM_POLL_WAIT) -> tuple[bytes, int, bool]:
        """Devolve (dados, novo_offset, perdeu_bytes) esperando ate `wait` por novidade."""
        deadline = time.monotonic() + wait
        while True:
            with self._lock:
                end = self._base + len(self._buf)
                start = max(offset, self._base)
                if start < end:
                    data = bytes(self._buf[start - self._base:])
                    return data, start + len(data), start > offset
                # Sem novidade: limpa o sinal ainda com o lock para nao perder um
                # append que aconteca entre a checagem e o wait().
                self._wake.clear()
            remaining = deadline - time.monotonic()
            if not self.alive or remaining <= 0:
                return b"", max(offset, self._base), False
            self._wake.wait(timeout=min(1.0, remaining))

    # -- entrada e controle ------------------------------------------------
    def write(self, data: bytes) -> None:
        with self._write_lock:
            while data:
                try:
                    sent = os.write(self.master, data)
                except (OSError, ValueError) as exc:
                    raise RemoteError(f"sessao encerrada: {exc}")
                data = data[sent:]

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        try:
            _set_winsize(self.master, cols, rows)
        except OSError:
            pass

    def close(self) -> None:
        self.alive = False
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGHUP)
        except OSError:  # inclui ProcessLookupError quando o ssh ja morreu
            pass
        try:
            os.close(self.master)
        except OSError:
            pass
        self._wake.set()


_terms: dict[str, TermSession] = {}
_terms_lock = threading.Lock()
_reaper_started = False


def _reap_terms() -> None:
    """Mata sessoes ociosas — cada uma segura um processo ssh e um PTY."""
    while True:
        time.sleep(30)
        now = time.time()
        # Copia sob o lock: o laco remove sessoes do dicionario, e uma aba abrindo
        # outra sessao ao mesmo tempo mudaria o dicionario no meio da iteracao.
        with _terms_lock:
            abertas = tuple(_terms.values())
        for term in abertas:
            idle = now - term.last_seen
            # Sessao encerrada fica um pouco no ar para o navegador ler a saida final.
            if idle > TERM_IDLE_TIMEOUT or (not term.alive and idle > 60):
                term.close()
                with _terms_lock:
                    _terms.pop(term.id, None)


def _term_of_user(tid: str) -> TermSession:
    if not TERM_ID_RE.match(tid or ""):
        abort(404)
    with _terms_lock:
        term = _terms.get(tid)
    # Sessao de outro usuario e tratada como inexistente.
    if not term or term.uid != session.get("uid"):
        abort(404, "sessao de terminal expirada ou encerrada")
    term.last_seen = time.time()
    return term


def _terminal_guard():
    if not ALLOW_SHELL:
        abort(403, "O terminal esta desabilitado (GAMEPANEL_ALLOW_SHELL=0).")
    if not HAVE_PTY:
        abort(503, "Terminal indisponivel: este sistema nao tem PTY.")


@app.get("/servers/<int:sid>/terminal")
@admin_required
def terminal(sid: int):
    _terminal_guard()
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    return render_template(
        "terminal.html", server=server, idle_timeout=TERM_IDLE_TIMEOUT
    )


@app.post("/api/term/<int:sid>/open")
@admin_required
def api_term_open(sid: int):
    global _reaper_started
    _terminal_guard()
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    body = request.get_json(silent=True) or {}
    cols = max(20, min(400, int(body.get("cols") or 80)))
    rows = max(5, min(150, int(body.get("rows") or 24)))

    with _terms_lock:
        # Uma aba esquecida nao pode impedir a proxima de abrir: derruba as mortas.
        for dead in [t for t in _terms.values() if not t.alive]:
            _terms.pop(dead.id, None)
        if len(_terms) >= TERM_MAX_SESSIONS:
            return jsonify({
                "error": f"limite de {TERM_MAX_SESSIONS} terminais simultaneos atingido"
            }), 429

    try:
        term = TermSession(dict(server), session["uid"], session.get("username", "?"), cols, rows)
    except RemoteError as exc:
        return jsonify({"error": str(exc)}), 502

    with _terms_lock:
        _terms[term.id] = term
        if not _reaper_started:
            threading.Thread(target=_reap_terms, daemon=True).start()
            _reaper_started = True

    log_job(
        "terminal", server, session.get("username", "?"),
        command=f"terminal interativo aberto ({cols}x{rows})",
        output=f"sessao {term.id[:8]} em {server['ssh_user']}@{server['host']}",
    )
    return jsonify({"id": term.id, "offset": 0, "cols": cols, "rows": rows})


@app.get("/api/term/<tid>/read")
@admin_required
def api_term_read(tid: str):
    _terminal_guard()
    term = _term_of_user(tid)
    try:
        offset = max(0, int(request.args.get("offset", "0")))
    except ValueError:
        offset = 0
    data, new_offset, lost = term.read(offset)
    return jsonify({
        "data": base64.b64encode(data).decode("ascii"),
        "offset": new_offset,
        "lost": lost,
        "alive": term.alive,
        "exit_code": term.exit_code,
    })


@app.post("/api/term/<tid>/keys")
@admin_required
def api_term_keys(tid: str):
    _terminal_guard()
    term = _term_of_user(tid)
    body = request.get_json(silent=True) or {}
    data = body.get("data", "")
    if not isinstance(data, str) or len(data) > 64 * 1024:
        abort(400, "entrada invalida")
    try:
        term.write(data.encode("utf-8"))
    except RemoteError as exc:
        return jsonify({"error": str(exc), "alive": False}), 409
    return jsonify({"ok": True, "alive": term.alive})


@app.post("/api/term/<tid>/resize")
@admin_required
def api_term_resize(tid: str):
    _terminal_guard()
    term = _term_of_user(tid)
    body = request.get_json(silent=True) or {}
    try:
        cols = max(20, min(400, int(body.get("cols", 80))))
        rows = max(5, min(150, int(body.get("rows", 24))))
    except (TypeError, ValueError):
        abort(400, "tamanho invalido")
    term.resize(cols, rows)
    return jsonify({"ok": True})


@app.post("/api/term/<tid>/close")
@admin_required
def api_term_close(tid: str):
    _terminal_guard()
    term = _term_of_user(tid)
    term.close()
    with _terms_lock:
        _terms.pop(term.id, None)
    return jsonify({"ok": True})


# ------------------------------------------------- editor de configuracoes


def _resolve_segments(path: str) -> str:
    """Resolve '..' e '.' sem tocar no destino (nao segue link nem consulta o disco)."""
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/" + "/".join(parts)


def _check_roots(path: str) -> None:
    if not FILE_ROOTS or "/" in FILE_ROOTS:  # "/" configurado = sem restricao
        return
    # rstrip + "/" para /opt/game nao liberar /opt/gamex sem querer.
    if any(path == r or path.startswith(r.rstrip("/") + "/") for r in FILE_ROOTS):
        return
    raise ValueError(f"fora das pastas permitidas ({', '.join(FILE_ROOTS)})")


def clean_path(raw: str) -> str:
    """Normaliza um caminho absoluto vindo da tela (resolve '..' de forma lexica)."""
    path = (raw or "").strip()
    if not path.startswith("/"):
        raise ValueError("use um caminho absoluto (comecando com /)")
    if "\x00" in path or "\n" in path or "\r" in path:
        raise ValueError("caractere invalido no caminho")
    if len(path) > 400:
        raise ValueError("caminho longo demais")
    cleaned = _resolve_segments(path)
    _check_roots(cleaned)
    return cleaned


def parent_of(path: str) -> str:
    return path.rsplit("/", 1)[0] or "/"


@app.template_filter("nivel")
def _bar_level(pct: float | None) -> str:
    """Classe da barra: perto do teto ela muda de cor (mesma regra do metrics.js)."""
    if pct is None:
        return ""
    if pct >= 92:
        return " hot"
    if pct >= 80:
        return " warn"
    return ""


@app.template_filter("duracao")
def _human_uptime(segundos: float | None) -> str:
    total = int(segundos or 0)
    dias, resto = divmod(total, 86400)
    horas, resto = divmod(resto, 3600)
    minutos = resto // 60
    if dias:
        return f"{dias}d {horas}h"
    if horas:
        return f"{horas}h {minutos}min"
    if minutos:
        return f"{minutos}min"
    # Jogador que acabou de entrar: "0min" nao diz nada.
    return f"{total}s"


@app.template_filter("tamanho")
def _human_size(num: int | None) -> str:
    """1536 -> '1.5 KB'. Um save de jogo em bytes crus nao diz nada para ninguem."""
    valor = float(num or 0)
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidade == "GB":
            if unidade == "B":
                return f"{int(valor)} B"
            return f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} GB"


LIST_SCRIPT = r"""
set -e
d=$1
[ -d "$d" ] || { echo "pasta nao encontrada: $d" >&2; exit 3; }
find "$d" -maxdepth 1 -mindepth 1 -printf '%y\t%Y\t%s\t%TY-%Tm-%Td %TH:%TM\t%M\t%f\n' \
  2>/dev/null | head -n "$2"
"""

# $2 = limite de edicao, $3 = quanto trazer do fim quando o arquivo passa do limite.
# Arquivo grande nao e mais um erro: vem so o fim dele, marcado como 'tail'.
READ_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
[ -f "$f" ] || { echo "nao e um arquivo comum" >&2; exit 4; }
sz=$(stat -Lc %s -- "$f")
if [ "$sz" -le "$2" ]; then kind=full; else kind=tail; fi
stat -Lc "META|%s|%y|%a|%U|%G|$kind" -- "$f"
if [ "$kind" = full ]; then
  base64 -w0 -- "$f"
else
  tail -c "$3" -- "$f" | base64 -w0
fi
"""

# Usado antes do download: confere que da para baixar e quanto tem para vir.
STAT_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
[ -f "$f" ] || { echo "nao e um arquivo comum (pastas nao sao baixaveis)" >&2; exit 4; }
[ -r "$f" ] || { echo "sem permissao de leitura" >&2; exit 5; }
stat -Lc 'META|%s|%y|%a|%U|%G' -- "$f"
"""

# Grava por cima do arquivo existente (cat >) em vez de trocar o inode: assim dono,
# grupo e permissao continuam os do jogo — o servidor roda como 'steam', nao root.
WRITE_SCRIPT = r"""
set -e
f=$1
d=$(dirname "$f")
[ -d "$d" ] || { echo "pasta nao existe: $d" >&2; exit 3; }
t=$(mktemp "$d/.gamepanel-XXXXXX")
trap 'rm -f "$t"' EXIT
base64 -d > "$t"
if [ -e "$f" ]; then
  [ -f "$f" ] || { echo "nao e um arquivo comum" >&2; exit 4; }
  cp -a -- "$f" "$f.$(date +%Y%m%d-%H%M%S).bak"
  cat "$t" > "$f"
else
  cat "$t" > "$f"
  chmod 0644 "$f"
  # Arquivo novo herda o dono da pasta: o jogo roda como 'steam' e precisa continuar
  # conseguindo reescrever o proprio config.
  chown --reference="$d" "$f" 2>/dev/null || true
fi
echo "gravado: $(stat -Lc %s -- "$f") bytes"
"""

# Apagar nao tem .bak: um save de varios GB nao cabe numa copia de seguranca, e quem
# manda apagar quer o espaco de volta. Por isso o escopo e estreito: arquivo comum,
# link, ou pasta VAZIA (rmdir) — nada de remocao recursiva a partir da tela.
DELETE_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || [ -L "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
if [ -d "$f" ] && [ ! -L "$f" ]; then
  rmdir -- "$f" 2>/dev/null || { echo "a pasta nao esta vazia (esvazie antes de apagar)" >&2; exit 4; }
  echo "pasta apagada: $f"
else
  sz=$(stat -Lc %s -- "$f" 2>/dev/null || echo 0)
  # -f para o rm nunca parar perguntando por arquivo sem permissao de escrita; o erro
  # que importa (pasta somente leitura) continua vindo.
  rm -f -- "$f"
  echo "apagado: $f ($sz bytes)"
fi
"""


def _files_guard():
    if not ALLOW_FILES:
        abort(403, "O editor de arquivos esta desabilitado (GAMEPANEL_ALLOW_FILES=0).")


def _server_or_404(sid: int) -> sqlite3.Row:
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    return server


def list_dir(server: sqlite3.Row, path: str) -> tuple[list[dict], bool]:
    proc = ssh_run(server, q("bash", "-lc", LIST_SCRIPT, "gp", path, str(FILE_LIST_MAX)), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao listar a pasta")
    entries: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 5)
        if len(parts) != 6:
            continue
        kind, target_kind, size, mtime, mode, name = parts
        real = target_kind if kind == "l" else kind
        entries.append({
            "name": name,
            "dir": real == "d",
            "link": kind == "l",
            "size": int(size) if size.isdigit() else 0,
            "mtime": mtime,
            "mode": mode,
            "path": (path.rstrip("/") + "/" + name) if path != "/" else "/" + name,
        })
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return entries, len(entries) >= FILE_LIST_MAX


def _parse_meta(head: str, campos: int) -> list[str]:
    meta = head.split("|")
    if meta[0] != "META" or len(meta) < campos:
        raise RemoteError("resposta inesperada do container ao ler o arquivo")
    return meta


def stat_file(server: sqlite3.Row, path: str) -> dict:
    """Metadados sem trazer o conteudo — usado antes de comecar um download."""
    proc = ssh_run(server, q("bash", "-lc", STAT_SCRIPT, "gp", path), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao ler o arquivo")
    meta = _parse_meta(proc.stdout.strip(), 6)
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1] or "arquivo",
        "size": int(meta[1]) if meta[1].isdigit() else 0,
        "mtime": meta[2][:19],
        "mode": meta[3],
        "owner": f"{meta[4]}:{meta[5]}",
    }


def read_file(server: sqlite3.Row, path: str) -> dict:
    """Le o arquivo para o editor.

    Arquivo dentro do limite vem inteiro e editavel. Acima do limite vem so o fim
    (somente leitura) — quem precisa do arquivo completo usa o download.
    """
    proc = ssh_run(
        server,
        q("bash", "-lc", READ_SCRIPT, "gp", path, str(FILE_MAX_BYTES), str(FILE_PREVIEW_BYTES)),
        timeout=180,
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao ler o arquivo")
    head, _, payload = proc.stdout.partition("\n")
    meta = _parse_meta(head, 7)
    try:
        raw = base64.b64decode(payload.strip() or "", validate=True)
    except ValueError:  # binascii.Error e uma subclasse de ValueError
        raise RemoteError("conteudo do arquivo chegou corrompido")
    binary = b"\x00" in raw
    truncated = meta[6] == "tail"
    text = "" if binary else raw.decode("utf-8", "replace")
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1] or "arquivo",
        "size": int(meta[1]) if meta[1].isdigit() else len(raw),
        "mtime": meta[2][:19],
        "mode": meta[3],
        "owner": f"{meta[4]}:{meta[5]}",
        "binary": binary,
        # Fim do arquivo apenas: editar e salvar daqui apagaria todo o resto.
        "truncated": truncated,
        "shown": len(raw),
        "editable": not binary and not truncated,
        "text": text,
        # \r\n vira \n no textarea; guardamos para devolver o arquivo como estava.
        "crlf": b"\r\n" in raw,
    }


@app.get("/servers/<int:sid>/files")
@admin_required
def files(sid: int):
    _files_guard()
    server = _server_or_404(sid)
    default_dir = server["config_path"] or FILE_DEFAULT_PATH

    entries: list[dict] = []
    truncated = False
    errors: list[str] = []
    opened = None

    file_arg = request.args.get("file", "").strip()
    dir_arg = request.args.get("path", "").strip()

    try:
        current = clean_path(file_arg or dir_arg or default_dir)
    except ValueError as exc:
        errors.append(str(exc))
        current = "/"
    if file_arg and current != "/":
        try:
            opened = read_file(server, current)
        except RemoteError as exc:
            errors.append(str(exc))
        current = parent_of(current)

    try:
        entries, truncated = list_dir(server, current)
    except RemoteError as exc:
        errors.append(str(exc))

    # Migalhas de pao: /opt/game/Pal -> [/, /opt, /opt/game, /opt/game/Pal]
    crumbs, walked = [{"name": "/", "path": "/"}], ""
    for seg in current.strip("/").split("/"):
        if not seg:
            continue
        walked += "/" + seg
        crumbs.append({"name": seg, "path": walked})

    return render_template(
        "files.html", server=server, entries=entries, truncated=truncated,
        current=current, crumbs=crumbs, opened=opened, errors=errors,
        max_kb=FILE_MAX_BYTES // 1024, preview_kb=FILE_PREVIEW_BYTES // 1024,
        matches=None,
    )


def find_config_files(server: sqlite3.Row, root: str) -> list[dict]:
    """Varre a pasta do jogo atras dos arquivos de configuracao mais provaveis."""
    names = " -o ".join(f"-name {shlex.quote(g)}" for g in CONFIG_GLOBS)
    script = (
        "set -e\n"
        'd=$1\n'
        '[ -d "$d" ] || { echo "pasta nao encontrada: $d" >&2; exit 3; }\n'
        f'find "$d" -maxdepth 5 -type f \\( {names} \\) '
        r"-printf '%s\t%TY-%Tm-%Td %TH:%TM\t%p\n' 2>/dev/null | LC_ALL=C sort -k3 | head -n 300"
        "\n"
    )
    proc = ssh_run(server, q("bash", "-lc", script, "gp", root), timeout=90)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha na busca")
    achados: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        achados.append({
            "size": int(parts[0]) if parts[0].isdigit() else 0,
            "mtime": parts[1],
            "path": parts[2],
        })
    return achados


def write_file(server: sqlite3.Row, path: str, data: bytes) -> str:
    """Grava o arquivo no container (com .bak, dono e permissao preservados)."""
    proc = ssh_run(
        server, q("bash", "-lc", WRITE_SCRIPT, "gp", path), timeout=120,
        stdin_data=base64.b64encode(data),
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao gravar")
    return proc.stdout.strip()


def delete_file(server: sqlite3.Row, path: str) -> str:
    """Apaga um arquivo (ou pasta vazia) no container. Nao tem volta."""
    proc = ssh_run(server, q("bash", "-lc", DELETE_SCRIPT, "gp", path), timeout=60)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao apagar")
    return proc.stdout.strip()


@app.get("/servers/<int:sid>/files/search")
@admin_required
def files_search(sid: int):
    _files_guard()
    server = _server_or_404(sid)
    try:
        root = clean_path(request.args.get("path", "") or server["config_path"] or FILE_DEFAULT_PATH)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("files", sid=sid))

    matches: list[dict] = []
    errors: list[str] = []
    try:
        matches = find_config_files(server, root)
    except RemoteError as exc:
        errors.append(str(exc))

    return render_template(
        "files.html", server=server, entries=[], truncated=False, current=root,
        crumbs=[{"name": "/", "path": "/"}], opened=None, errors=errors,
        max_kb=FILE_MAX_BYTES // 1024, preview_kb=FILE_PREVIEW_BYTES // 1024,
        matches=matches,
    )


@app.post("/servers/<int:sid>/files/save")
@admin_required
def files_save(sid: int):
    _files_guard()
    server = _server_or_404(sid)
    raw_path = request.form.get("path", "")
    content = request.form.get("content", "")
    keep_crlf = request.form.get("crlf") == "1"

    try:
        path = clean_path(raw_path)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("files", sid=sid))

    # O navegador manda \r\n; so devolvemos assim se o arquivo original ja usava CRLF.
    text = content.replace("\r\n", "\n")
    if keep_crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if len(data) > FILE_MAX_BYTES:
        flash(f"Arquivo grande demais para salvar (limite de {FILE_MAX_BYTES // 1024} KB).", "error")
        return redirect(url_for("files", sid=sid, file=path))

    # O arquivo pode ter crescido desde que a tela abriu (log, save do jogo). Gravar o
    # que esta no textarea agora apagaria tudo o que nao coube nele.
    try:
        atual = stat_file(server, path)
        if atual["size"] > FILE_MAX_BYTES:
            flash(
                f"{path} tem {atual['size'] // 1024} KB e passou do limite de edicao"
                f" ({FILE_MAX_BYTES // 1024} KB). Nada foi gravado — baixe o arquivo para mexer nele.",
                "error",
            )
            return redirect(url_for("files", sid=sid, file=path))
    except RemoteError:
        pass  # arquivo novo, ou stat falhou: o proprio gravar reporta o erro

    try:
        saida = write_file(server, path, data)
        log_job(
            "edit-file", server, session.get("username", "?"),
            command=path, output=saida,
        )
        flash(f"{path} salvo ({len(data)} bytes). Uma copia .bak foi guardada ao lado.", "ok")
    except RemoteError as exc:
        log_job(
            "edit-file", server, session.get("username", "?"),
            command=path, output=str(exc), status="error",
        )
        flash(f"Nao consegui salvar: {exc}", "error")

    return redirect(url_for("files", sid=sid, file=path))


@app.post("/servers/<int:sid>/files/delete")
@admin_required
def files_delete(sid: int):
    _files_guard()
    server = _server_or_404(sid)

    try:
        path = clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("files", sid=sid))

    # Raiz permitida nao se apaga: sem isso um clique errado poderia levar /opt/game
    # inteiro (a pasta so cai vazia, mas nem esse caso vale a pena permitir).
    raizes = {"/"} | {r.rstrip("/") or "/" for r in FILE_ROOTS}
    if path in raizes:
        flash(f"{path} e uma pasta raiz do editor — nao da para apagar por aqui.", "error")
        return redirect(url_for("files", sid=sid, path=path))

    volta = parent_of(path)
    try:
        saida = delete_file(server, path)
        log_job("delete-file", server, session.get("username", "?"), command=path, output=saida)
        flash(f"{saida} (sem copia .bak — apagar nao tem volta).", "ok")
        # Arquivo fixado na tela Config que deixou de existir: tirar do cadastro evita
        # que a tela abra sempre num erro de leitura.
        registrados = config_paths(server)
        if path in registrados:
            _save_config_files(sid, [p for p in registrados if p != path])
            flash(f"{path} tambem saiu dos arquivos da tela Config.", "ok")
    except RemoteError as exc:
        log_job(
            "delete-file", server, session.get("username", "?"),
            command=path, output=str(exc), status="error",
        )
        flash(f"Nao consegui apagar: {exc}", "error")

    return redirect(url_for("files", sid=sid, path=volta))


def _attachment_header(name: str) -> str:
    """Content-Disposition que aguenta acento e aspas no nome do arquivo."""
    ascii_name = re.sub(r'[^A-Za-z0-9._-]', "_", name) or "arquivo"
    quoted = urllib.parse.quote(name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def stream_remote_file(server: sqlite3.Row, path: str):
    """Joga o arquivo do container direto para o navegador, sem passar por disco.

    E `cat` na outra ponta lido em pedacos: um save de varios GB desce sem o painel
    guardar nada em memoria.
    """
    argv = ssh_argv(server) + [q("cat", "--", path)]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def gerar():
        try:
            while True:
                chunk = proc.stdout.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            # Navegador que cancela no meio nao pode deixar um ssh orfao segurando fd.
            if proc.poll() is None:
                proc.kill()
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    pipe.close()
            proc.wait()

    return gerar()


@app.get("/servers/<int:sid>/files/download")
@admin_required
def files_download(sid: int):
    """Baixa qualquer arquivo do container — inclusive binario ou grande demais para o editor."""
    _files_guard()
    server = _server_or_404(sid)
    try:
        path = clean_path(request.args.get("path", ""))
        info = stat_file(server, path)
    except (ValueError, RemoteError) as exc:
        abort(400, str(exc))

    if FILE_DOWNLOAD_MAX and info["size"] > FILE_DOWNLOAD_MAX:
        abort(400, f"arquivo de {info['size']} bytes acima do limite de download"
                   f" ({FILE_DOWNLOAD_MAX} bytes) — use scp para este")

    log_job(
        "download-file", server, session.get("username", "?"),
        command=path, output=f"{info['size']} bytes",
    )
    return app.response_class(
        stream_with_context(stream_remote_file(server, path)),
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": _attachment_header(info["name"]),
            "Content-Length": str(info["size"]),
            "X-Content-Type-Options": "nosniff",
        },
    )


# ------------------------------------------------- edicao rapida de config
#
# Mesmo motor de leitura/gravacao da tela "Arquivos", so que o arquivo chega na tela
# como formulario: um campo por chave. Quem sabe o que quer mudar (nome do servidor,
# senha de admin, numero de jogadores) nao precisa achar o arquivo nem contar virgula.


def config_paths(server: sqlite3.Row) -> list[str]:
    """Arquivos de configuracao registrados no cadastro do servidor."""
    return [linha.strip() for linha in (server["config_files"] or "").splitlines() if linha.strip()]


def load_config_doc(server: sqlite3.Row, path: str) -> tuple[gameconf.ConfigFile, dict]:
    """Le o arquivo no container e o interpreta campo a campo."""
    info = read_file(server, path)
    if info["binary"]:
        raise gameconf.ConfigError(
            "este arquivo e binario — a edicao campo a campo nao se aplica a ele"
        )
    if info["truncated"]:
        raise gameconf.ConfigError(
            f"o arquivo tem {info['size'] // 1024} KB e passa do limite de edicao"
            f" ({FILE_MAX_BYTES // 1024} KB) — arquivo de configuracao nao costuma"
            " chegar a esse tamanho, confira se e o arquivo certo"
        )
    # O parser trabalha so com \n; se o arquivo usava CRLF ele volta assim na gravacao.
    doc = gameconf.load(info["name"], info["text"].replace("\r\n", "\n"))
    if len(doc.settings) > CONFIG_SETTINGS_MAX:
        raise gameconf.ConfigError(
            f"o arquivo tem {len(doc.settings)} chaves (o formulario para em"
            f" {CONFIG_SETTINGS_MAX}) — pelo jeito nao e um arquivo de configuracao"
        )
    return doc, info


def _save_config_files(sid: int, caminhos: list[str]) -> None:
    conn = db()
    with conn:
        conn.execute(
            "UPDATE servers SET config_files = ? WHERE id = ?", ("\n".join(caminhos), sid)
        )


@app.get("/servers/<int:sid>/config")
@login_required
def config_quick(sid: int):
    _files_guard()
    server = _server_or_404(sid)
    arquivos = config_paths(server)
    errors: list[str] = []

    alvo = (request.args.get("file") or "").strip()
    if alvo:
        try:
            alvo = clean_path(alvo)
        except ValueError as exc:
            errors.append(str(exc))
            alvo = ""
    # O caminho vem da URL: sem esta trava a tela Config seria um leitor de arquivo
    # qualquer do container (como root), justo o que o operador nao tem permissao de
    # abrir. Para ele valem so os arquivos que um admin ja registrou no servidor.
    if alvo and alvo not in arquivos and not is_admin():
        abort(403, "Operador so abre os arquivos de configuracao ja registrados neste servidor.")
    if not alvo and arquivos:
        alvo = arquivos[0]

    doc = info = None
    if alvo:
        try:
            doc, info = load_config_doc(server, alvo)
            # Aqui o formulario deixa de ser "chave = texto" e passa a saber o que cada
            # campo significa: booleano vira caixa, enum vira lista, duracao aparece em
            # minutos em vez de nanossegundos.
            enriquece_settings(doc, info["name"])
        except (RemoteError, gameconf.ConfigError) as exc:
            errors.append(f"{alvo}: {exc}")

    # Sem arquivo registrado a tela ja chega com a lista de candidatos do container:
    # e o caminho de "informar qual e o arquivo" sem sair procurando por pastas.
    sugestoes = None
    # Procurar candidatos e listar pastas do container — leitura que so admin faz.
    if is_admin() and (request.args.get("descobrir") == "1" or (not arquivos and not alvo)):
        try:
            sugestoes = find_config_files(server, server["config_path"] or FILE_DEFAULT_PATH)
        except RemoteError as exc:
            errors.append(str(exc))
            sugestoes = []

    return render_template(
        "config.html", server=server, arquivos=arquivos, alvo=alvo, doc=doc, info=info,
        sugestoes=sugestoes, errors=errors, registrado=alvo in arquivos,
        max_files=CONFIG_FILES_MAX,
    )


@app.post("/servers/<int:sid>/config/files")
@admin_required
def config_files_edit(sid: int):
    """Registra (ou tira) um arquivo da tela rapida, com um clique."""
    _files_guard()
    server = _server_or_404(sid)
    try:
        path = clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("config_quick", sid=sid))

    caminhos = config_paths(server)
    if request.form.get("acao") == "remover":
        caminhos = [p for p in caminhos if p != path]
        _save_config_files(sid, caminhos)
        flash(f"{path} saiu da tela de configuracao (o arquivo nao foi tocado).", "ok")
        return redirect(url_for("config_quick", sid=sid))

    if path in caminhos:
        return redirect(url_for("config_quick", sid=sid, file=path))
    if len(caminhos) >= CONFIG_FILES_MAX:
        flash(f"Limite de {CONFIG_FILES_MAX} arquivos por servidor.", "error")
        return redirect(url_for("config_quick", sid=sid))
    caminhos.append(path)
    _save_config_files(sid, caminhos)
    flash(f"{path} agora abre direto na tela Config.", "ok")
    return redirect(url_for("config_quick", sid=sid, file=path))


@app.template_filter("ident")
def _ident(value: str) -> str:
    """Identificador de secao/chave dentro do formulario.

    Os ids do gameconf usam \\x1f para separar niveis; percent-encoded eles atravessam
    o HTML sem virar caractere de controle solto no meio de um atributo.
    """
    return urllib.parse.quote(value or "", safe="")


def enriquece_settings(doc: gameconf.ConfigFile, nome_arquivo: str) -> None:
    """Anexa a descricao do catalogo a cada campo lido do arquivo.

    Campo sem entrada no catalogo fica exatamente como antes (texto livre): o objetivo
    e melhorar o que da para melhorar, nunca esconder chave que o jogo passou a usar.
    """
    for secao in doc.sections:
        for s in secao.settings:
            spec = gamefields.describe(nome_arquivo, s.key)
            s.spec = spec
            s.display_value = spec.to_display(s.value) if spec else s.value


def _edits_do_formulario(form, nome_arquivo: str = "") -> tuple[list[gameconf.Edit], list[str]]:
    """Monta a lista de alteracoes: so o que o usuario realmente mexeu.

    Devolve tambem os erros de validacao. O valor chega na unidade da TELA (minutos,
    multiplicador) e e convertido para a unidade do ARQUIVO (nanossegundos) aqui - por
    isso a conferencia acontece antes da conversao, para a mensagem falar a lingua de
    quem digitou.
    """
    total = form.get("n", "0")
    total = int(total) if total.isdigit() else 0
    edits: list[gameconf.Edit] = []
    erros: list[str] = []
    for i in range(min(total, 4000)):
        chave = (form.get(f"key.{i}", "") or "").strip()
        if not chave:
            continue  # linha de "adicionar configuracao" deixada em branco
        valor = (form.get(f"val.{i}", "") or "").replace("\r", "")
        ident = urllib.parse.unquote((form.get(f"id.{i}", "") or "").strip())
        if ident and valor == (form.get(f"orig.{i}", "") or "").replace("\r", ""):
            continue  # campo intocado: nao reescreve a linha

        spec = gamefields.describe(nome_arquivo, chave) if nome_arquivo else None
        if spec:
            problema = spec.validate(valor)
            if problema:
                erros.append(f"{spec.label or chave}: {problema}")
                continue
            valor = spec.from_display(valor)

        edits.append(gameconf.Edit(
            id=ident,
            section=urllib.parse.unquote(form.get(f"sec.{i}", "") or ""),
            key=chave,
            value=valor,
        ))
    return edits, erros


@app.post("/servers/<int:sid>/config/save")
@login_required
def config_save(sid: int):
    _files_guard()
    server = _server_or_404(sid)
    try:
        path = clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("config_quick", sid=sid))
    # Mesma trava do config_quick, agora na escrita: o caminho chega pelo formulario.
    if path not in config_paths(server) and not is_admin():
        abort(403, "Operador so salva os arquivos de configuracao ja registrados neste servidor.")

    voltar = url_for("config_quick", sid=sid, file=path)
    try:
        # O nome do arquivo escolhe o catalogo: e ele que diz o que validar e em que
        # unidade o valor foi digitado.
        edits, erros_validacao = _edits_do_formulario(request.form, path.rsplit("/", 1)[-1])
    except gameconf.ConfigError as exc:
        flash(str(exc), "error")
        return redirect(voltar)
    if erros_validacao:
        # Nada e gravado quando ha erro: salvar metade das alteracoes deixaria o arquivo
        # num estado que a pessoa nao pediu e nao sabe qual e.
        flash("Nao salvei nada porque ha valor fora do limite - " + "; ".join(erros_validacao[:3]),
              "error")
        return redirect(voltar)
    if not edits:
        flash("Nenhum campo foi alterado.", "ok")
        return redirect(voltar)

    # O arquivo e relido AGORA: o jogo pode te-lo reescrito desde que a tela abriu, e as
    # alteracoes sao aplicadas por chave — nao por numero de linha.
    try:
        doc, info = load_config_doc(server, path)
        texto = doc.apply(edits)
    except (RemoteError, gameconf.ConfigError) as exc:
        flash(f"Nao consegui salvar: {exc}", "error")
        return redirect(voltar)

    if info["crlf"]:
        texto = texto.replace("\n", "\r\n")
    data = texto.encode("utf-8")
    if len(data) > FILE_MAX_BYTES:
        flash(f"Arquivo grande demais para salvar (limite de {FILE_MAX_BYTES // 1024} KB).", "error")
        return redirect(voltar)

    mexidas = ", ".join(dict.fromkeys(e.key for e in edits))
    try:
        saida = write_file(server, path, data)
    except RemoteError as exc:
        log_job("edit-config", server, session.get("username", "?"),
                command=f"{path}: {mexidas}", output=str(exc), status="error")
        flash(f"Nao consegui salvar: {exc}", "error")
        return redirect(voltar)

    log_job("edit-config", server, session.get("username", "?"),
            command=f"{path}: {mexidas}", output=f"{saida}\nalterado: {mexidas}")
    flash(f"{len(edits)} configuracao(oes) salva(s) em {path}: {mexidas}."
          " Uma copia .bak foi guardada ao lado.", "ok")

    # Quase todo jogo so le a configuracao no start — por isso o reiniciar mora aqui.
    if request.form.get("restart") == "1":
        job_id = start_job("restart", server, session.get("username", "?"))
        invalidate_status(sid)
        return redirect(url_for("job_detail", jid=job_id))
    return redirect(voltar)


# --------------------------------------------------------------------- jobs


@app.get("/jobs/<int:jid>")
@login_required
def job_detail(jid: int):
    conn = db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
    if not job:
        abort(404)
    server = None
    if job["server_id"]:
        server = conn.execute(
            SQL_SERVER_BY_ID, (job["server_id"],)
        ).fetchone()
    return render_template("job.html", job=job, server=server)


@app.get("/api/jobs/<int:jid>")
@login_required
def api_job(jid: int):
    job = db().execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
    if not job:
        abort(404)
    return jsonify(
        {
            "status": job["status"],
            "exit_code": job["exit_code"],
            "output": job["output"],
            "finished_at": job["finished_at"],
        }
    )


# ------------------------------------------------------------- acesso / conta


@app.get("/ssh-key")
@login_required
def ssh_key():
    return render_template("ssh_key.html", pubkey=public_key())


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        row = db().execute(
            "SELECT * FROM users WHERE id = ?", (session["uid"],)
        ).fetchone()
        erro = valida_senha(new, confirm)
        if not row or not verify_password(current, row["password_hash"]):
            flash("Senha atual incorreta.", "error")
        elif erro:
            flash(erro, "error")
        else:
            conn = db()
            with conn:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(new), session["uid"]),
                )
            flash("Senha alterada.", "ok")
            return redirect(url_for("dashboard"))
    return render_template("account.html")


# ------------------------------------------------------------------ usuarios


def valida_senha(nova: str, confirma: str) -> str:
    """Devolve a mensagem de erro; string vazia quando a senha serve."""
    if len(nova) < PASSWORD_MIN:
        return f"A senha precisa ter ao menos {PASSWORD_MIN} caracteres."
    if nova != confirma:
        return "A confirmacao nao confere."
    return ""


def conta_admins(excluindo: int = 0) -> int:
    """Quantos administradores sobrariam sem o usuario `excluindo`."""
    return db().execute(
        "SELECT COUNT(*) FROM users WHERE role = ? AND id <> ?", (ROLE_ADMIN, excluindo)
    ).fetchone()[0]


def _usuario_ou_404(uid: int) -> sqlite3.Row:
    row = db().execute(
        "SELECT id, username, role FROM users WHERE id = ?", (uid,)
    ).fetchone()
    if not row:
        abort(404)
    return row


@app.get("/usuarios")
@admin_required
def users_list():
    rows = db().execute(
        "SELECT id, username, role, created_at FROM users ORDER BY role, username"
    ).fetchall()
    return render_template(
        "users.html", users=rows, roles=ROLES, role_labels=ROLE_LABELS,
        meu_id=session.get("uid"), min_len=PASSWORD_MIN,
    )


@app.post("/usuarios")
@admin_required
def user_new():
    username = request.form.get("username", "").strip().lower()
    role = request.form.get("role", ROLE_OPERADOR)
    senha = request.form.get("new", "")
    if not USER_RE.match(username):
        erro = ("Nome de usuario invalido: use de 1 a 32 caracteres entre letras"
                " minusculas, numeros, '-' e '_', comecando por letra ou '_'.")
    elif role not in ROLES:
        erro = "Papel invalido."
    else:
        erro = valida_senha(senha, request.form.get("confirm", ""))
    if erro:
        flash(erro, "error")
        return redirect(url_for("users_list"))

    conn = db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at)"
                " VALUES (?,?,?,?)",
                (username, hash_password(senha), role, now_iso()),
            )
    except sqlite3.IntegrityError:
        # username e UNIQUE: e o unico jeito de dois admins criarem o mesmo nome ao
        # mesmo tempo sem um sobrescrever o outro.
        flash(f"Ja existe um usuario chamado '{username}'.", "error")
        return redirect(url_for("users_list"))
    flash(f"Usuario '{username}' criado como {ROLE_LABELS[role].lower()}."
          " Passe a senha para ele e peca para troca-la na tela Conta.", "ok")
    return redirect(url_for("users_list"))


@app.post("/usuarios/<int:uid>/papel")
@admin_required
def user_role(uid: int):
    alvo = _usuario_ou_404(uid)
    role = request.form.get("role", "")
    if role not in ROLES:
        abort(400, "Papel invalido.")
    if uid == session.get("uid"):
        # Rebaixar a si mesmo tranca a pessoa fora desta tela no mesmo clique.
        flash("Voce nao pode mudar o proprio papel — peca a outro administrador.", "error")
    elif role == alvo["role"]:
        flash(f"'{alvo['username']}' ja e {ROLE_LABELS[role].lower()}.", "ok")
    elif alvo["role"] == ROLE_ADMIN and conta_admins(excluindo=uid) == 0:
        flash("Este e o unico administrador: promova outra pessoa antes de rebaixa-lo.",
              "error")
    else:
        conn = db()
        with conn:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))
        flash(f"'{alvo['username']}' agora e {ROLE_LABELS[role].lower()}.", "ok")
    return redirect(url_for("users_list"))


@app.post("/usuarios/<int:uid>/senha")
@admin_required
def user_password(uid: int):
    """Reset feito pelo admin — sem a senha atual, que e justamente a esquecida."""
    alvo = _usuario_ou_404(uid)
    erro = valida_senha(request.form.get("new", ""), request.form.get("confirm", ""))
    if erro:
        flash(erro, "error")
        return redirect(url_for("users_list"))
    conn = db()
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(request.form.get("new", "")), uid),
        )
    flash(f"Senha de '{alvo['username']}' redefinida.", "ok")
    return redirect(url_for("users_list"))


@app.post("/usuarios/<int:uid>/remover")
@admin_required
def user_delete(uid: int):
    alvo = _usuario_ou_404(uid)
    if uid == session.get("uid"):
        flash("Voce nao pode remover a propria conta.", "error")
    elif alvo["role"] == ROLE_ADMIN and conta_admins(excluindo=uid) == 0:
        flash("Nao da para remover o unico administrador do painel.", "error")
    else:
        conn = db()
        with conn:
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        # A sessao dele morre no proximo clique: o login_required confere o banco.
        flash(f"Usuario '{alvo['username']}' removido.", "ok")
    return redirect(url_for("users_list"))


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.errorhandler(400)
def _bad_request(exc):
    return render_template(TPL_ERROR, code=400, message=str(exc)), 400


@app.errorhandler(403)
def _forbidden(exc):
    return render_template(TPL_ERROR, code=403, message=str(exc)), 403


@app.errorhandler(404)
def _not_found(_exc):
    return render_template(TPL_ERROR, code=404, message="Pagina nao encontrada."), 404


@app.errorhandler(413)
def _too_large(_exc):
    return render_template(
        TPL_ERROR, code=413,
        message=f"Conteudo grande demais (o editor aceita ate {FILE_MAX_BYTES // 1024} KB por arquivo).",
    ), 413


@app.errorhandler(503)
def _unavailable(exc):
    return render_template(TPL_ERROR, code=503, message=str(exc)), 503


# --------------------------------------------------------------- bootstrap CLI


def ensure_admin_user(username: str, password: str, role: str = "") -> None:
    """Cria o usuario inicial, ou reseta a senha se ele ja existir.

    Continua sendo a saida de emergencia quando ninguem consegue entrar: e por aqui
    que se devolve o papel de admin a alguem sem passar pela tela (`--role admin`).
    Sem `--role`, um usuario que ja existe mantem o papel que tinha.
    """
    if role and role not in ROLES:
        raise SystemExit(f"papel invalido: {role} (use {' ou '.join(ROLES)})")
    init_db()
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row and role:
            conn.execute(
                "UPDATE users SET password_hash = ?, role = ? WHERE id = ?",
                (hash_password(password), role, row["id"]),
            )
            print(f"Senha do usuario '{username}' redefinida; papel: {role}.")
        elif row:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), row["id"]),
            )
            print(f"Senha do usuario '{username}' redefinida.")
        else:
            # Usuario criado pela linha de comando e admin por padrao: e o do deploy,
            # que precisa cadastrar servidor e criar os demais na tela.
            papel = role or ROLE_ADMIN
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at)"
                " VALUES (?,?,?,?)",
                (username, hash_password(password), papel, now_iso()),
            )
            print(f"Usuario '{username}' criado ({papel}).")
    conn.close()


def ensure_server(
    name: str,
    host: str,
    service: str,
    ssh_port: int = 22,
    ssh_user: str = "root",
    game_port: str = "",
    notes: str = "",
    config_path: str = "",
    config_files: str = "",
    query_port: int = 0,
    player_source: str = "",
) -> bool:
    """Cadastra (ou atualiza) um servidor sem passar pela tela. Devolve True se criou.

    E por aqui que o deploy registra o container recem-criado no painel — inclusive o
    arquivo de configuracao do jogo, para a tela "Config" ja abrir pronta. Num redeploy
    os dados do container mandam, mas o que e escolha de quem usa o painel (arquivos de
    config acrescentados a mao, forma de contar jogadores) nao e apagado.
    """
    init_db()
    conn = _connect()
    criado = False
    try:
        with conn:
            atual = conn.execute(
                "SELECT * FROM servers WHERE host = ? AND ssh_port = ?", (host, ssh_port)
            ).fetchone()
            if atual is None:
                conn.execute(
                    "INSERT INTO servers (name, host, ssh_port, ssh_user, service,"
                    " game_port, notes, config_path, config_files, query_port,"
                    " player_source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (name, host, ssh_port, ssh_user, service, game_port, notes,
                     config_path, config_files, query_port, player_source, now_iso()),
                )
                criado = True
            else:
                arquivos = [p for p in (atual["config_files"] or "").splitlines() if p.strip()]
                for novo in config_files.splitlines():
                    if novo.strip() and novo.strip() not in arquivos:
                        arquivos.append(novo.strip())
                conn.execute(
                    "UPDATE servers SET name=?, ssh_user=?, service=?, game_port=?,"
                    " notes=?, config_path=?, config_files=?, query_port=?,"
                    " player_source=? WHERE id=?",
                    (
                        name, ssh_user, service, game_port, notes or atual["notes"],
                        config_path or atual["config_path"],
                        "\n".join(arquivos[:CONFIG_FILES_MAX]), query_port,
                        atual["player_source"] or player_source, atual["id"],
                    ),
                )
    finally:
        conn.close()
    return criado


init_db()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Painel de servidores de jogos")
    parser.add_argument("--create-user", metavar="USUARIO")
    parser.add_argument("--password", metavar="SENHA")
    parser.add_argument("--role", default="", choices=("", *ROLES),
                        help="papel do usuario (padrao: admin ao criar; manter ao redefinir)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GAMEPANEL_PORT", "8080")))
    # Usado pelo deploy (deploy-docker.ps1) para deixar o servidor ja cadastrado.
    parser.add_argument("--register-server", metavar="NOME")
    parser.add_argument("--server-host", default="")
    parser.add_argument("--service", default="")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--game-port", default="")
    parser.add_argument("--query-port", type=int, default=0)
    parser.add_argument("--config-path", default="")
    parser.add_argument("--config-files", default="")
    parser.add_argument("--player-source", default="")
    parser.add_argument("--notes", default="")
    opts = parser.parse_args()

    if opts.create_user:
        if not opts.password:
            raise SystemExit("--create-user exige --password")
        ensure_admin_user(opts.create_user, opts.password, opts.role)
    elif opts.register_server:
        if not opts.server_host or not opts.service:
            raise SystemExit("--register-server exige --server-host e --service")
        criado = ensure_server(
            name=opts.register_server,
            host=opts.server_host,
            service=opts.service,
            ssh_port=opts.ssh_port,
            ssh_user=opts.ssh_user,
            game_port=opts.game_port,
            notes=opts.notes,
            config_path=opts.config_path,
            # A linha de comando nao aceita quebra de linha com conforto: aqui os
            # arquivos vem separados por virgula.
            config_files="\n".join(
                p.strip() for p in opts.config_files.split(",") if p.strip()
            ),
            query_port=opts.query_port,
            player_source=opts.player_source,
        )
        print(f"servidor '{opts.register_server}' {'cadastrado' if criado else 'atualizado'}"
              f" ({opts.server_host})")
    else:
        app.run(host=opts.host, port=opts.port)
