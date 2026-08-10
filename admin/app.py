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

SQL_SERVER_BY_ID = "SELECT * FROM servers WHERE id = ?"
SQL_ALL_SERVERS = "SELECT * FROM servers ORDER BY name"
TPL_ERROR = "error.html"
TPL_LOGIN = "login.html"
MSG_TIMEOUT = "tempo esgotado"

UNIT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,80}\.service$")
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

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
  query_port INTEGER NOT NULL DEFAULT 0,
  player_source TEXT NOT NULL DEFAULT '',
  join_re    TEXT NOT NULL DEFAULT '',
  leave_re   TEXT NOT NULL DEFAULT '',
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
MIGRATIONS = (
    ("servers", "config_path", "ALTER TABLE servers ADD COLUMN config_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "query_port", "ALTER TABLE servers ADD COLUMN query_port INTEGER NOT NULL DEFAULT 0"),
    ("servers", "player_source", "ALTER TABLE servers ADD COLUMN player_source TEXT NOT NULL DEFAULT ''"),
    ("servers", "join_re", "ALTER TABLE servers ADD COLUMN join_re TEXT NOT NULL DEFAULT ''"),
    ("servers", "leave_re", "ALTER TABLE servers ADD COLUMN leave_re TEXT NOT NULL DEFAULT ''"),
)


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _connect()
    with conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(ddl)
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


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


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
    return {
        "csrf_token": csrf_token,
        "current_user": session.get("username"),
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

A2S_HEADER = b"\xff\xff\xff\xff"
A2S_SPLIT = b"\xff\xff\xff\xfe"
A2S_INFO_REQ = A2S_HEADER + b"TSource Engine Query\x00"


class QueryError(RuntimeError):
    pass


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
# pergunta ao proprio container quais portas UDP estao escutando e testa uma a uma.
# /proc/net/udp existe sempre; 'ss' nao vem instalado em todo container.
UDP_PORTS_SCRIPT = r"""
set -u
hex=$(awk 'NR>1 { split($2, a, ":"); print a[2] }' /proc/net/udp /proc/net/udp6 2>/dev/null | sort -u)
for h in $hex; do
  printf '%d\n' "0x$h" 2>/dev/null || true
done | sort -un
"""

# Portas de consulta que a maioria dos jogos Steam usa quando nao ha nada declarado.
QUERY_PORT_GUESSES = (27015, 27016, 27005)


def _portas_do_texto(texto: str) -> list[int]:
    """Tira numeros de porta do campo livre 'Portas do jogo' (ex.: '8211/udp 27015/udp')."""
    return [int(n) for n in re.findall(r"\d{2,5}", texto or "") if 1 <= int(n) <= 65535]


def candidate_ports(server: sqlite3.Row) -> tuple[list[int], str]:
    """Portas a testar: as que o container esta escutando + as declaradas + as usuais."""
    escutando: list[int] = []
    aviso = ""
    try:
        raw = ssh_output(server, q("bash", "-lc", UDP_PORTS_SCRIPT, "gp"), timeout=30)
        escutando = [int(p) for p in raw.split() if p.isdigit()]
    except (RemoteError, ValueError) as exc:
        aviso = f"nao consegui listar as portas UDP do container: {exc}"

    candidatas: list[int] = []
    for porta in escutando + _portas_do_texto(server["game_port"]) + list(QUERY_PORT_GUESSES):
        if 1 <= porta <= 65535 and porta not in candidatas:
            candidatas.append(porta)
    return candidatas, aviso


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
    """Como contar os jogadores deste servidor: 'a2s', 'log' ou '' (desligado)."""
    escolhido = (server["player_source"] or "").strip()
    if escolhido in ("a2s", "log", "none"):
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


@app.get("/servers/<int:sid>/players/descobrir")
@login_required
def players_setup(sid: int):
    """Assistente: acha a porta que responde a consulta e ajuda a achar o padrao no log."""
    server = _server_or_404(sid)
    aba = request.args.get("aba", "porta")

    portas, aviso = [], ""
    if aba == "porta":
        candidatas, aviso = candidate_ports(server)
        portas = probe_ports(server["host"], candidatas[:12])

    # Assistente do log: linhas candidatas e teste do padrao digitado.
    amostras: list[str] = []
    teste = None
    erro_log = ""
    join_re = request.args.get("join_re", server["join_re"])
    leave_re = request.args.get("leave_re", server["leave_re"])
    if aba == "log":
        try:
            linhas = read_log_lines(server)
            chaves = re.compile("|".join(LOG_HINT_WORDS), re.I)
            amostras = [ln for ln in linhas if chaves.search(ln)][-120:]
            if request.args.get("testar"):
                entrar = compile_pattern(join_re, "entrada")
                if not entrar:
                    raise QueryError("informe o padrao da linha de entrada")
                sair = compile_pattern(leave_re, "saida")
                teste = _apply_log_events(linhas, entrar, sair)
                teste["casaram"] = [
                    ln for ln in amostras
                    if entrar.search(ln[:LOG_LINE_MAX]) or (sair and sair.search(ln[:LOG_LINE_MAX]))
                ][-20:]
        except (RemoteError, QueryError) as exc:
            erro_log = str(exc)

    return render_template(
        "players_setup.html", server=server, aba=aba, portas=portas, aviso=aviso,
        amostras=amostras, teste=teste, erro_log=erro_log,
        join_re=join_re, leave_re=leave_re,
    )


@app.post("/servers/<int:sid>/players/usar")
@login_required
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
    if origem not in ("", "none", "a2s", "log"):
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
            "query_port": _porta(
                form.get("query_port"), 0, 0,
                "Porta de consulta invalida (use 0 para desligar).", errors,
            ),
            "player_source": origem,
            "join_re": _padrao(form.get("join_re"), "entrada", errors),
            "leave_re": _padrao(form.get("leave_re"), "saida", errors),
        },
        errors,
    )


@app.route("/servers/new", methods=["GET", "POST"])
@login_required
def server_new():
    data = {
        "name": "", "host": "", "ssh_user": "root", "ssh_port": 22,
        "service": "", "game_port": "", "notes": "", "config_path": "", "query_port": 0,
        "player_source": "", "join_re": "", "leave_re": "",
    }
    if request.method == "POST":
        data, errors = _form_server(request.form)
        if not errors:
            try:
                conn = db()
                with conn:
                    conn.execute(
                        "INSERT INTO servers (name, host, ssh_port, ssh_user, service,"
                        " game_port, notes, config_path, query_port, player_source,"
                        " join_re, leave_re, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            data["name"], data["host"], data["ssh_port"],
                            data["ssh_user"], data["service"], data["game_port"],
                            data["notes"], data["config_path"], data["query_port"],
                            data["player_source"], data["join_re"], data["leave_re"],
                            now_iso(),
                        ),
                    )
                flash(f"Servidor {data['name']} cadastrado.", "ok")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                errors.append(f"Ja existe um servidor cadastrado em {data['host']}.")
        for err in errors:
            flash(err, "error")
    return render_template("server_form.html", data=data, mode="new")


@app.route("/servers/<int:sid>/edit", methods=["GET", "POST"])
@login_required
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
                        "UPDATE servers SET name=?, host=?, ssh_port=?, ssh_user=?,"
                        " service=?, game_port=?, notes=?, config_path=?, query_port=?,"
                        " player_source=?, join_re=?, leave_re=? WHERE id=?",
                        (
                            data["name"], data["host"], data["ssh_port"],
                            data["ssh_user"], data["service"], data["game_port"],
                            data["notes"], data["config_path"], data["query_port"],
                            data["player_source"], data["join_re"], data["leave_re"], sid,
                        ),
                    )
                invalidate_status(sid)
                flash("Servidor atualizado.", "ok")
                return redirect(url_for("server_detail", sid=sid))
            except sqlite3.IntegrityError:
                errors.append(f"Ja existe um servidor cadastrado em {data['host']}.")
        for err in errors:
            flash(err, "error")
    return render_template("server_form.html", data=data, mode="edit", sid=sid)


@app.post("/servers/<int:sid>/delete")
@login_required
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
@login_required
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
@login_required
def terminal(sid: int):
    _terminal_guard()
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    return render_template(
        "terminal.html", server=server, idle_timeout=TERM_IDLE_TIMEOUT
    )


@app.post("/api/term/<int:sid>/open")
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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


@app.get("/servers/<int:sid>/files/search")
@login_required
def files_search(sid: int):
    """Varre a pasta do jogo atras dos arquivos de configuracao mais provaveis."""
    _files_guard()
    server = _server_or_404(sid)
    try:
        root = clean_path(request.args.get("path", "") or server["config_path"] or FILE_DEFAULT_PATH)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("files", sid=sid))

    names = " -o ".join(f"-name {shlex.quote(g)}" for g in CONFIG_GLOBS)
    script = (
        "set -e\n"
        'd=$1\n'
        '[ -d "$d" ] || { echo "pasta nao encontrada: $d" >&2; exit 3; }\n'
        f'find "$d" -maxdepth 5 -type f \\( {names} \\) '
        r"-printf '%s\t%TY-%Tm-%Td %TH:%TM\t%p\n' 2>/dev/null | LC_ALL=C sort -k3 | head -n 300"
        "\n"
    )
    matches: list[dict] = []
    errors: list[str] = []
    try:
        proc = ssh_run(server, q("bash", "-lc", script, "gp", root), timeout=90)
        if proc.returncode != 0:
            raise RemoteError((proc.stderr or proc.stdout).strip() or "falha na busca")
        for line in proc.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            matches.append({
                "size": int(parts[0]) if parts[0].isdigit() else 0,
                "mtime": parts[1],
                "path": parts[2],
            })
    except RemoteError as exc:
        errors.append(str(exc))

    return render_template(
        "files.html", server=server, entries=[], truncated=False, current=root,
        crumbs=[{"name": "/", "path": "/"}], opened=None, errors=errors,
        max_kb=FILE_MAX_BYTES // 1024, preview_kb=FILE_PREVIEW_BYTES // 1024,
        matches=matches,
    )


@app.post("/servers/<int:sid>/files/save")
@login_required
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
        proc = ssh_run(
            server, q("bash", "-lc", WRITE_SCRIPT, "gp", path), timeout=120,
            stdin_data=base64.b64encode(data),
        )
        if proc.returncode != 0:
            raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao gravar")
        log_job(
            "edit-file", server, session.get("username", "?"),
            command=path, output=proc.stdout.strip(),
        )
        flash(f"{path} salvo ({len(data)} bytes). Uma copia .bak foi guardada ao lado.", "ok")
    except RemoteError as exc:
        log_job(
            "edit-file", server, session.get("username", "?"),
            command=path, output=str(exc), status="error",
        )
        flash(f"Nao consegui salvar: {exc}", "error")

    return redirect(url_for("files", sid=sid, file=path))


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
@login_required
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
        if not row or not verify_password(current, row["password_hash"]):
            flash("Senha atual incorreta.", "error")
        elif len(new) < 8:
            flash("A nova senha precisa ter ao menos 8 caracteres.", "error")
        elif new != confirm:
            flash("A confirmacao nao confere.", "error")
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


def ensure_admin_user(username: str, password: str) -> None:
    """Cria o usuario inicial, ou reseta a senha se ele ja existir."""
    init_db()
    conn = _connect()
    with conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), row["id"]),
            )
            print(f"Senha do usuario '{username}' redefinida.")
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                (username, hash_password(password), now_iso()),
            )
            print(f"Usuario '{username}' criado.")
    conn.close()


init_db()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Painel de servidores de jogos")
    parser.add_argument("--create-user", metavar="USUARIO")
    parser.add_argument("--password", metavar="SENHA")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GAMEPANEL_PORT", "8080")))
    opts = parser.parse_args()

    if opts.create_user:
        if not opts.password:
            raise SystemExit("--create-user exige --password")
        ensure_admin_user(opts.create_user, opts.password)
    else:
        app.run(host=opts.host, port=opts.port)
