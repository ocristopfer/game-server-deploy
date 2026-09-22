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
import sqlite3
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, NamedTuple

# Rodando como SCRIPT (`python3 /opt/gamepanel/gamepanel/app.py --reset-2fa ...`), quem
# entra no sys.path e a pasta do proprio pacote, e `import gamepanel` nao resolve. Isto
# poe o pai dela na frente. Nao e detalhe: a saida de emergencia do segundo fator e o
# cadastro de servidor do deploy-game.ps1 chamam o arquivo por caminho, e desde que o
# codigo foi para src/ os dois quebravam com ModuleNotFoundError - o do deploy em
# silencio, porque ele so avisa "painel nao encontrado" e segue.
if __package__ in (None, ""):  # pragma: no cover - so vale fora do import normal
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# markupsafe vem junto com o Jinja, que vem junto com o python3-flask do apt: nao e
# dependencia nova. E o mesmo escape que o autoescape do template usa.
from markupsafe import Markup, escape

from gamepanel import cli
from gamepanel import i18n
from gamepanel import navigation as ui
from gamepanel.games import config_format as gameconf
from gamepanel.games import gamefields
from gamepanel.games.catalog import search as busca_de_jogos
from gamepanel.games.catalog.templates import MODELOS as MODELOS_DE_JOGO
from gamepanel.integrations import broker_client, webhook_client
from gamepanel.runtime import a2s, http_probe
from gamepanel.runtime import log_probe
from gamepanel.runtime import port_probe
from gamepanel.runtime import ssh as ssh_transport
# Apelido: ha uma rota `terminal()` neste mesmo modulo (a tela /servers/<id>/terminal),
# e o nome `terminal` sem apelido acabaria REBATIZADO por ela — o import ficaria valendo
# so ate a definicao da rota, silenciosamente (mypy pegou isso: "Name already defined").
# Apelidos pelo mesmo motivo: ha rotas `files()` (`/servers/<id>/files`) e
# `backups()` (`/servers/<id>/backups`) neste modulo.
from gamepanel.runtime import backups as backups_rt
from gamepanel.runtime import files as files_rt
from gamepanel.runtime import terminal as term_runtime
from gamepanel.persistence import schema
from gamepanel.security import qr, totp
from gamepanel.services import (
    alert_service,
    broker_service,
    chart_service,
    metrics_service,
    parallel,
    player_service,
    schedule_service,
    server_service,
    status_service,
)
from gamepanel.tasks import broker_jobs, log_stream, scheduler

# O terminal interativo depende de PTY (so existe em POSIX). Em outros sistemas o
# resto do painel continua funcionando e a tela do terminal responde 503.
HAVE_PTY = term_runtime.HAVE_PTY
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

# Um servidor cadastrado, como o resto do painel o enxerga.
#
# Ou e a linha do SQLite, ou uma COPIA dela em dict - e a copia nao e detalhe de
# implementacao: uma `sqlite3.Row` pertence a conexao que a produziu, e conexao de
# SQLite nao atravessa thread. Toda tarefa longa (um update de jogo leva quase uma hora)
# roda com `dict(server)` em vez da Row; ver `start_job`. As duas formas respondem a
# `server["host"]`, que e tudo o que estas funcoes precisam.
Servidor = sqlite3.Row | Mapping[str, Any]


# ---------------------------------------------------------------- configuracao

DB_PATH = os.environ.get("GAMEPANEL_DB", "/var/lib/gamepanel/panel.db")
SECRET_FILE = os.environ.get("GAMEPANEL_SECRET_FILE", "/etc/gamepanel/secret_key")
SSH_KEY = os.environ.get("GAMEPANEL_SSH_KEY", "/etc/gamepanel/id_ed25519")
# Gravavel: as host keys dos containers sao aprendidas no primeiro acesso (accept-new).
KNOWN_HOSTS = os.environ.get("GAMEPANEL_KNOWN_HOSTS", "/var/lib/gamepanel/known_hosts")
# Onde ficam os sockets de conexao reaproveitada do SSH. Ao lado do known_hosts, e nao no
# /tmp: o socket da acesso a uma sessao ja autenticada nos containers de jogo, e /tmp e
# espaco compartilhado — pasta do proprio painel, com 0700, fecha essa porta.
SSH_CONTROL_DIR = os.environ.get(
    "GAMEPANEL_SSH_CONTROL_DIR", os.path.join(os.path.dirname(KNOWN_HOSTS), "ssh-control"))
# Quanto a conexao mestre fica de pe depois que o comando dela termina. E o que faz a
# volta seguinte do monitor pegar carona em vez de pagar outro aperto de mao; 60s cobre
# com folga o ritmo do monitor (15s a 60s) sem deixar conexao ociosa pendurada por horas.
SSH_CONTROL_PERSIST = os.environ.get("GAMEPANEL_SSH_CONTROL_PERSIST", "60")

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

# Broker de provisionamento: cria instancias de jogo e abre portas no firewall. O painel
# nao guarda credencial de Proxmox/OPNsense, so o token do broker. DESLIGADO por padrao: quem
# liga (GAMEPANEL_ALLOW_BROKER=1) precisa apontar URL, arquivo do token e, em https, a
# impressao SHA-256 do certificado. Sem isso o recurso nao aparece em lugar nenhum.
BROKER_URL = os.environ.get("GAMEPANEL_BROKER_URL", "")
BROKER_TOKEN_FILE = os.environ.get("GAMEPANEL_BROKER_TOKEN_FILE", "")
BROKER_CERT_SHA256 = os.environ.get("GAMEPANEL_BROKER_CERT_SHA256", "")
BROKER_POLL = float(os.environ.get("GAMEPANEL_BROKER_POLL", "2"))
# Voltas seguidas sem resposta do broker antes de dar o job por perdido.
BROKER_FALHAS_MAX = 15


def _configura_broker() -> bool:
    """Liga o cliente do broker. Qualquer configuracao ruim DESLIGA o recurso (e loga o
    motivo) em vez de derrubar o painel: o resto dele nao depende disto."""
    if os.environ.get("GAMEPANEL_ALLOW_BROKER", "0") != "1":
        return False
    try:
        with open(BROKER_TOKEN_FILE, encoding="utf-8") as arquivo:
            token = arquivo.read().strip()
        broker_client.configurar(BROKER_URL, token, BROKER_CERT_SHA256,
                                 permitir_http=os.environ.get("GAMEPANEL_DEV", "") == "1")
    except (OSError, ValueError) as erro:
        print(f"[painel] broker DESLIGADO: {erro}", file=sys.stderr)
        return False
    return True


ALLOW_BROKER = _configura_broker()

# Editor de arquivos: le/grava arquivos de configuracao do jogo pelo mesmo SSH.
ALLOW_FILES = os.environ.get("GAMEPANEL_ALLOW_FILES", "1") == "1"
# 1 = quem nao ativou o segundo fator so alcanca a tela de ativacao. Desligado por padrao: ligar
# ANTES de cada admin ter o aplicativo no celular tranca todo mundo fora do painel.
REQUIRE_2FA = os.environ.get("GAMEPANEL_REQUIRE_2FA", "0") == "1"
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
# Upload: o arquivo sobe em multipart e desce por SSH em streaming, sem passar inteiro
# pela memoria do painel — por isso o teto aqui e bem maior que o do editor, que carrega
# tudo num textarea. 0 = sem limite.
#
# Cuidado ao aumentar: o Werkzeug guarda o corpo do multipart num arquivo temporario do
# CONTAINER DO PAINEL antes de a view ver um byte. Subir 2 GB exige 2 GB livres la — e o
# CT do painel costuma ser pequeno. 512 MB cobre mod e save sem esse risco.
FILE_UPLOAD_MAX = int(os.environ.get("GAMEPANEL_UPLOAD_MAX", str(512 * 1024 * 1024)))
UPLOAD_CHUNK = 256 * 1024

# Backup: tar.gz das pastas que valem a pena guardar (save + configuracao do jogo),
# criado DENTRO do container e guardado la. O painel nao vira deposito de save — ele
# dispara, lista, baixa e restaura.
BACKUP_DIR = os.environ.get("GAMEPANEL_BACKUP_DIR", "/var/backups/gamepanel")
# Quantas copias manter por servidor; as mais antigas saem sozinhas. 0 = nunca apagar.
BACKUP_KEEP = int(os.environ.get("GAMEPANEL_BACKUP_KEEP", "5"))
BACKUP_TIMEOUT = int(os.environ.get("GAMEPANEL_BACKUP_TIMEOUT", "3600"))
BACKUP_PATHS_MAX = 8
BACKUP_LIST_MAX = 100

# Agendamento: tarefas que o painel dispara sozinho (reiniciar de madrugada, backup
# diario). O relogio e o do CONTAINER DO PAINEL — se as horas nao baterem com as suas,
# o que esta errado e o TZ dele.
# Este e o piso de TODOS os avisos do painel: nada pode chegar mais rapido do que a volta
# do relogio. Ele mesmo custa quase nada (as quatro tarefas tem cada uma o seu proprio
# ritmo la dentro e saem na hora quando nao e a vez delas), entao 15s da folga para o
# alerta de jogador sem multiplicar SSH de ninguem.
SCHEDULE_TICK = float(os.environ.get("GAMEPANEL_SCHEDULE_TICK", "15"))
# Tarefa atrasada demais nao dispara. Se o painel passou a noite fora do ar, ninguem quer
# o "reiniciar as 5h" caindo as 14h, no meio da partida: ela espera a proxima ocorrencia.
SCHEDULE_GRACE = int(os.environ.get("GAMEPANEL_SCHEDULE_GRACE", "3600"))
# Nome que aparece no historico no lugar do usuario, quando quem disparou foi o relogio.
SCHEDULE_USER = "agendador"

# Retencao do historico: cada job guarda ate 200 KB de saida, e um backup diario sozinho
# ja poe 365 linhas por ano no banco. 0 desliga a limpeza.
JOBS_KEEP_DAYS = int(os.environ.get("GAMEPANEL_JOBS_KEEP_DAYS", "60"))
JOBS_PURGE_EVERY = 3600.0
HISTORY_PAGE = 60

# Amostras para os graficos de uso. Cada uma custa uma leitura de medidores — a chamada
# mais cara do painel (o script remoto dorme 0,5s para tirar duas amostras de CPU) —,
# entao o intervalo e generoso: 5 min dao 288 pontos por dia, de sobra para o grafico.
SAMPLE_EVERY = float(os.environ.get("GAMEPANEL_SAMPLE_EVERY", "300"))
SAMPLES_KEEP_DAYS = int(os.environ.get("GAMEPANEL_SAMPLES_KEEP_DAYS", "7"))

# Alertas: o painel avisa por webhook (Discord, Slack, o que aceitar um POST de JSON)
# quando um servidor cai, some do SSH, enche o disco ou quando uma tarefa agendada falha.
# A URL fica no banco (tela "Alertas"); esta variavel so serve de valor inicial, para o
# deploy poder deixar tudo pronto.
WEBHOOK_URL_PADRAO = os.environ.get("GAMEPANEL_WEBHOOK_URL", "")
WEBHOOK_TIMEOUT = float(os.environ.get("GAMEPANEL_WEBHOOK_TIMEOUT", "6"))
# O Cloudflare na frente do Discord devolve 403 (erro 1010) para o User-Agent padrao do
# urllib ("Python-urllib/3.x"), antes mesmo do pedido chegar no webhook. Mandar um
# User-Agent proprio resolve, e nenhum outro destino se incomoda com ele.
WEBHOOK_UA = os.environ.get("GAMEPANEL_WEBHOOK_UA", "GamePanel/1.0 (alertas)")
# Teto de destinos. Cada alerta vira um POST por destino, em serie, dentro da volta do
# monitor — uma lista sem fim faria a volta esperar por todos eles.
WEBHOOK_MAX = int(os.environ.get("GAMEPANEL_WEBHOOK_MAX", "10"))
# De quanto em quanto tempo o painel confere o estado de cada servidor. Cada volta custa
# uma ida de SSH por servidor — nao adianta descer muito.
MONITOR_EVERY = float(os.environ.get("GAMEPANEL_MONITOR_EVERY", "60"))
# Jogador entrando e a unica coisa que alguem espera ver "agora" — quem recebe o aviso
# costuma querer entrar junto, e um minuto depois ja e tarde. Por isso ele tem relogio
# proprio, mais curto que o do estado.
PLAYER_CHECK_EVERY = float(os.environ.get("GAMEPANEL_PLAYER_CHECK_EVERY", "15"))
# ...mas so vale para quem responde de graca. A2S e HTTP saem de dentro do container sem
# nada extra; a contagem por LOG e outra historia: cada consulta e uma ida de SSH que
# arrasta ate LOG_SCAN_MAX linhas para o painel aplicar o regex. Nesse ritmo curto isso
# seriam megabytes por minuto por servidor, para achar duas linhas novas. Quem conta por
# log fica no relogio do estado ate existir leitura incremental ou log em streaming.
PLAYER_FAST_SOURCES = {"a2s", "http"}
# Quem conta por log ganha tempo real por outro caminho: uma conexao SSH longa rodando
# `journalctl -f`. Em vez de perguntar "tem alguem novo?" de minuto em minuto, o painel
# fica ouvindo e reage a linha no instante em que ela sai.
LOG_STREAM = os.environ.get("GAMEPANEL_LOG_STREAM", "1") not in ("0", "false", "no")
# Uma entrada e uma saida no mesmo segundo (alguem trocando de servidor, um grupo
# entrando junto) nao podem virar uma releitura do log cada. A primeira linha dispara,
# as seguintes dessa janela pegam carona na mesma conferida.
LOG_STREAM_DEBOUNCE = float(os.environ.get("GAMEPANEL_LOG_STREAM_DEBOUNCE", "3"))
# Depois de a conexao cair, quanto esperar antes de tentar de novo. Servidor desligado
# nao pode virar um laco de SSH a cada segundo.
LOG_STREAM_RETRY = float(os.environ.get("GAMEPANEL_LOG_STREAM_RETRY", "30"))
# O disco sai dos medidores, que custam bem mais caro (o script remoto dorme 0,5s para
# tirar duas amostras). Ele nao enche em um minuto, entao a conferida e espacada.
DISK_CHECK_EVERY = float(os.environ.get("GAMEPANEL_DISK_CHECK_EVERY", "600"))
# Uma acao do painel (parar, reiniciar, atualizar) derruba o servidor de proposito. Nesta
# janela depois dela, queda nao vira alerta — senao todo restart pelo botao viraria susto.
ALERT_QUIET = float(os.environ.get("GAMEPANEL_ALERT_QUIET", "180"))

# Padroes usados pelo botao "procurar arquivos de config".
CONFIG_GLOBS = ("*.ini", "*.cfg", "*.conf", "*.json", "*.yaml", "*.yml", "*.properties", "*.txt")
# Quantos arquivos de configuracao um servidor pode ter registrados para a tela "Config".
CONFIG_FILES_MAX = 8
# Teto de campos no formulario da tela "Config": acima disso o arquivo quase certamente
# nao e configuracao (um log casa com "chave=valor" em varias linhas).
CONFIG_SETTINGS_MAX = 600

SQL_SERVER_BY_ID = "SELECT * FROM servers WHERE id = ?"
SQL_ALL_SERVERS = "SELECT * FROM servers ORDER BY name"
SQL_SET_PASSWORD = "UPDATE users SET password_hash = ? WHERE id = ?"
# Formato de data curto do painel ("17/09 05:00"). Estava escrito a mao em tres
# telas; uma delas com um espaco a mais bastaria para a lista parecer desalinhada.
FORMATO_DATA_CURTA = "%d/%m %H:%M"

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

# CSRF: o painel tem a propria protecao, e nao o Flask-WTF.
#
# Analisador estatico costuma marcar este `Flask(__name__)` como "CSRF desabilitado"
# porque nao ve um `CSRFProtect(app)`. Aqui a protecao e o par `csrf_token()` (o
# gerador que os templates chamam) e `_check_csrf` (um `before_request` que barra
# qualquer metodo que mude estado sem o token da sessao) - procure pelos dois neste
# arquivo. A escolha e a mesma do resto do painel: dependencia so a stdlib mais o
# `python3-flask` do apt, porque o container do painel nao baixa pacote de lugar
# nenhum. Nao remova `_check_csrf` achando que o Flask cobre isso sozinho: ele nao
# cobre.
#
# A marca de supressao na linha abaixo e o "hotspot revisado" do proprio analisador
# (regra python:S4502). Sem ela o aviso volta a cada analise e acaba virando ruido que
# se aprende a ignorar - que e como um aviso de CSRF de verdade passaria batido um dia.
#
# Ela vai sozinha na linha, sem texto depois: a marca tem sintaxe propria, e explicacao
# colada nela e uma supressao malformada (foi o que aconteceu aqui na primeira vez). O
# porque fica neste bloco, que e onde se procura por ele.
app = Flask(__name__)  # NOSONAR


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

SCHEMA = schema.SCHEMA
MIGRATIONS = schema.MIGRATIONS


def db() -> sqlite3.Connection:
    """Conexao por request. WAL para o job em background nao travar a leitura da tela."""
    conn = getattr(g, "_db", None)
    if conn is None:
        conn = _connect()
        g._db = conn
    return conn


def _connect() -> sqlite3.Connection:
    return schema.connect(DB_PATH)


@app.teardown_appcontext
def _close_db(_exc) -> None:
    conn = getattr(g, "_db", None)
    if conn is not None:
        conn.close()


# Colunas acrescentadas depois da primeira versao: CREATE TABLE IF NOT EXISTS nao
# altera tabelas que ja existem, entao cada uma precisa do seu ALTER aqui.
# O terceiro item e um comando SQL ou uma tupla deles (o ALTER mais o conserto das
# linhas antigas, quando o valor padrao da coluna nao serve para quem ja existia).
def init_db() -> None:
    schema.init_db(DB_PATH, WEBHOOK_URL_PADRAO, ALERT_DEFAULT, now_iso)


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


def _lockout_remaining(key: str, tries: int = LOCKOUT_TRIES, window: float = LOCKOUT_WINDOW) -> int:
    with _login_lock:
        fails = [t for t in _login_fails.get(key, []) if time.time() - t < window]
        _login_fails[key] = fails
        if len(fails) < tries:
            return 0
        return int(window - (time.time() - fails[0])) + 1


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
    # `in` e nao `getattr(..., sentinela)`: o cache guarda None de proposito (ninguem
    # logado), entao "tem chave" e "tem valor" sao perguntas diferentes aqui.
    if "_user" in g:
        return g._user
    uid = session.get("uid")
    row = None
    if uid:
        row = db().execute(
            "SELECT id, username, role, created_at, totp_enabled, lang"
            " FROM users WHERE id = ?", (uid,)
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


# Rotas que recebem corpo grande. O teto geral (MAX_CONTENT_LENGTH) e apertado porque o
# editor manda o arquivo percent-encoded dentro de um formulario; o upload precisa de bem
# mais que isso.
#
# Este hook tem de vir ANTES do _check_csrf no arquivo: a ordem de registro e a ordem de
# execucao, e e o _check_csrf quem toca em request.form primeiro — o teto e conferido na
# hora em que o corpo e lido, entao ajustar so la dentro da view chegaria tarde (413).
BIG_BODY_ENDPOINTS = {"files_upload"}


@app.before_request
def _teto_do_corpo():
    if request.endpoint in BIG_BODY_ENDPOINTS:
        request.max_content_length = (FILE_UPLOAD_MAX + UPLOAD_CHUNK) if FILE_UPLOAD_MAX else None


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


# Com GAMEPANEL_REQUIRE_2FA=1 quem ainda nao ativou o segundo fator so alcanca isto.
ENDPOINTS_SEM_2FA = frozenset({
    "login", "login_2fa", "logout", "account_2fa", "health", "static",
    "manifest", "service_worker", "offline",
})


@app.before_request
def _exige_segundo_fator():
    if not REQUIRE_2FA or request.endpoint in ENDPOINTS_SEM_2FA or request.endpoint is None:
        return None
    usuario = usuario_logado()
    if usuario is None or usuario["totp_enabled"]:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "ative a verificacao em duas etapas em Conta"}), 403
    flash("Este painel exige a verificacao em duas etapas: ative-a para continuar.", "error")
    return redirect(url_for("account_2fa"))


def static_url(nome: str) -> str:
    """URL de um arquivo estatico com a marca do mtime.

    Sem isto, um deploy que muda o css/components.css ou o js/terminal.js continua
    servindo o que o navegador guardou — e o relato chega como "a tela quebrou depois
    da atualizacao".

    Aceita caminho com subpasta ("css/tokens.css"): a arvore de estaticos e organizada
    em css/, js/ e icons/.
    """
    try:
        marca = int(os.path.getmtime(os.path.join(app.static_folder or "", nome)))
    except OSError:
        marca = 0
    return url_for("static", filename=nome, v=marca)


IDIOMA_PADRAO = i18n.idioma_valido(os.environ.get("GAMEPANEL_LANG"))


def idioma_atual() -> str:
    """O idioma DESTE pedido, decidido uma vez e guardado no `g`.

    A ordem e de preferencia: o que a pessoa escolheu na Conta vence tudo; sem escolha
    (ou sem ninguem logado, como na tela de login) vale o que o navegador pede; e o
    ultimo recurso e o padrao do deploy.
    """
    escolhido = getattr(g, "_idioma", None)
    if escolhido is not None:
        return escolhido
    usuario = usuario_logado()
    do_usuario = _valor_guardado(usuario, "lang") if usuario else ""
    if do_usuario:
        escolhido = i18n.idioma_valido(do_usuario)
    elif request:
        escolhido = i18n.do_cabecalho(request.headers.get("Accept-Language"))
    else:
        escolhido = IDIOMA_PADRAO
    g._idioma = escolhido
    return escolhido


def traduzir(chave: str, **campos: object) -> str:
    """O `_()` das telas e das mensagens: a frase daquela chave, no idioma
    deste pedido."""
    return i18n.traduzir(chave, idioma_atual(), **campos)


def traduzir_html(chave: str, **campos: object) -> Markup:
    """O `_h()` das telas: frase que TRAZ marcacao (`<strong>`, `<code>`).

    Existe porque paragrafo de ajuda nao se parte: quebrar o texto em cada `<strong>`
    deixaria metade do paragrafo em portugues na tela em ingles. A frase vem do catalogo,
    que e codigo deste repositorio, entao ela pode conter marcacao; o que chega de fora
    sao os CAMPOS, e cada um e escapado antes de entrar.

    `escape` e nao `escape(str(...))` de proposito: assim um campo que JA e marcacao
    (o `_h` de outra frase, encaixado nesta) passa inteiro em vez de aparecer na tela
    com os sinais de maior e menor a mostra.
    """
    # A frase vem de `i18n`, que e codigo deste repositorio, e todo campo passou por
    # `escape` na linha de baixo: nao ha entrada de usuario chegando crua aqui.
    return Markup(i18n.traduzir(  # noqa: S704
        chave, idioma_atual(), **{nome: escape(valor) for nome, valor in campos.items()}
    ))


@app.context_processor
def _inject():
    usuario = usuario_logado()
    return {
        "csrf_token": csrf_token,
        # `_` e o nome de sempre para traduzir numa tela; `_h` e o irmao para a frase
        # que traz marcacao (ver `traduzir_html`).
        "_": traduzir,
        "_h": traduzir_html,
        "idioma_atual": idioma_atual(),
        "idiomas": i18n.IDIOMAS,
        "static_url": static_url,
        "current_user": usuario["username"] if usuario else None,
        # As telas escondem o que o operador nao pode abrir. Quem manda e o
        # @admin_required na rota; isto aqui e so para nao mostrar botao que da 403.
        "is_admin": bool(usuario) and usuario["role"] == ROLE_ADMIN,
        "role_label": ROLE_LABELS.get(usuario["role"], usuario["role"]) if usuario else "",
        "job_label": job_label,
        "allow_shell": ALLOW_SHELL,
        "allow_term": ALLOW_SHELL and HAVE_PTY,
        "allow_files": ALLOW_FILES,
        "allow_broker": ALLOW_BROKER,
        # A tela precisa saber se a contagem esta ligada, e ela pode vir da porta de
        # consulta OU do log — nao da para olhar so o query_port.
        "player_source": player_source,
        # Quais acoes a API daquele servidor aceita (vazio na maioria dos jogos).
        "acoes_de_jogador": acoes_de_jogador,
        "rotulo_de_acao": PLAYER_ACTION_LABELS,
        **_contexto_de_navegacao(),
    }


def _contexto_de_navegacao() -> dict:
    """O mapa da interface, ja filtrado para quem esta logado e para este deploy.

    Os templates nao decidem mais o que existe no menu: eles desenham o que vier
    daqui. Antes, a lista de telas de um servidor estava escrita a mao em seis
    templates diferentes, cada um com um subconjunto proprio — e era por isso que
    "Graficos" existia numa tela e nao na outra.
    """
    admin = is_admin()
    secoes = ui.secoes_visiveis(admin=admin, arquivos=ALLOW_FILES, shell=ALLOW_SHELL)
    tem_pty = ALLOW_SHELL and HAVE_PTY
    barra, conta = ui.nav_desktop(admin=admin, broker=ALLOW_BROKER)
    return {
        "nav_principal": ui.itens_visiveis(ui.NAV_PRINCIPAL, admin=admin, broker=ALLOW_BROKER),
        "nav_secundaria": ui.itens_visiveis(ui.NAV_SECUNDARIA, admin=admin, broker=ALLOW_BROKER),
        "nav_ativa": ui.nav_ativa_de(request.endpoint),
        "nav_desktop_barra": barra,
        "nav_desktop_conta": conta,
        "nav_ativa_desktop": ui.nav_ativa_desktop_de(request.endpoint),
        "secoes_do_servidor": secoes,
        "endpoint_da_secao": lambda secao: ui.endpoint_da_secao(secao, tem_pty=tem_pty),
        "acoes_de_energia": ui.acoes_do_grupo(ui.GRUPO_ENERGIA),
        "acoes_de_manutencao": ui.acoes_do_grupo(ui.GRUPO_MANUTENCAO),
        "energia_do_cartao": ui.energia_do_cartao,
        "energia_restante": ui.energia_restante,
    }


# ------------------------------------------------------------------- ssh
#
# Implementacao real em gamepanel.runtime.ssh (extraida na Fase 4 - so a camada de
# transporte, testada indiretamente pelas dezenas de testes que ja exercitam
# server_status/server_players/etc.). Os nomes abaixo continuam existindo neste modulo
# de proposito: e o que `monkeypatch.setattr(panel, "ssh_run", ...)` e chamadas diretas
# como `panel.ssh_argv(...)` (ver test_players.py) esperam encontrar.

def _ssh_config() -> ssh_transport.SshConfig:
    # Funcao, nao valor: monkeypatch.setattr(panel, "SSH_KEY", ...) (e as demais
    # variaveis abaixo) so tem efeito se isto reler os globais do modulo a cada chamada.
    return ssh_transport.SshConfig(
        key=SSH_KEY, known_hosts=KNOWN_HOSTS, control_dir=SSH_CONTROL_DIR,
        control_persist=SSH_CONTROL_PERSIST, quick_timeout=QUICK_TIMEOUT,
    )


_ssh = ssh_transport.SshClient(_ssh_config)
RemoteError = ssh_transport.RemoteError
ssh_argv = _ssh.argv
ssh_run = _ssh.run
ssh_output = _ssh.output
public_key = _ssh.public_key
q = ssh_transport.quote_command


def em_paralelo(tarefas: dict, timeout: float = 40.0) -> dict:
    """Roda varias leituras remotas ao mesmo tempo; devolve {nome: (valor, erro)}.

    Cada uma custa a sua ida de SSH, e elas nao dependem umas das outras — em serie a
    tela paga a soma, e com um servidor fora do ar paga a soma dos timeouts.

    Nada aqui pode tocar no `g` do Flask (a conexao por request nao atravessa thread).
    As funcoes usadas na tela de detalhe ou nao falam com o banco, ou abrem conexao
    propria — o `http_login` da contagem por API e o caso, e ele ja faz assim.
    """
    saida: dict = {}
    lock = threading.Lock()

    def work(nome, funcao):
        try:
            valor, erro = funcao(), ""
        except (RemoteError, QueryError) as exc:
            valor, erro = None, str(exc)
        with lock:
            saida[nome] = (valor, erro)

    threads = [threading.Thread(target=work, args=(n, f), daemon=True)
               for n, f in tarefas.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    for nome in tarefas:
        saida.setdefault(nome, (None, MSG_TIMEOUT))
    return saida


# ------------------------------------------------------------- jogadores (A2S)
#
# Implementacao real em gamepanel.runtime.a2s (extraida na Fase 4). Os nomes abaixo
# continuam existindo neste modulo de proposito - QueryError em particular e usado por
# `raise`/`except` em todo o resto de app.py (HTTP, log, acoes de jogador), e
# `pytest.raises(panel.QueryError)` em test_players.py precisa continuar achando a
# MESMA classe.
QUERY_TIMEOUT = float(os.environ.get("GAMEPANEL_QUERY_TIMEOUT", "3"))
PLAYERS_TTL = float(os.environ.get("GAMEPANEL_PLAYERS_TTL", "5"))

PLAYER_SOURCES = player_service.PLAYER_SOURCES

QueryError = a2s.QueryError
AuthError = a2s.AuthError


def query_players(host: str, port: int) -> dict:
    # Le QUERY_TIMEOUT na hora da chamada (nao um valor congelado no import): mesmo
    # motivo do SshClient em runtime/ssh.py.
    return a2s.query_players(host, port, timeout=QUERY_TIMEOUT)


# ------------------------------------------- jogadores (API HTTP do proprio jogo)
#
# A parte pura (montar o pedido HTTP, interpretar a resposta, achar lista/contagem no
# JSON) mora em gamepanel.runtime.http_probe; a que depende do banco (guardar o token
# renovado) mora em gamepanel.services.player_service. Os nomes abaixo continuam aqui
# porque o resto de app.py — e os testes — chamam por eles.
HTTP_TIMEOUT = float(os.environ.get("GAMEPANEL_HTTP_TIMEOUT", "6"))
HTTP_BODY_MAX = 2000
HTTP_PATH_MAX = 120
HTTP_FIELDS = player_service.HTTP_FIELDS

auth_header = http_probe.auth_header
read_players_json = http_probe.read_players_json
URL_RE = http_probe.URL_RE
HTTP_URL_MAX = http_probe.HTTP_URL_MAX
_split_status = http_probe._split_status
_json_walk = http_probe._json_walk
_id_do_item = http_probe._id_of
_tem_login = player_service._tem_login


def http_json(server: Servidor, url: str, auth: str, corpo: str, exigir_json: bool = True):
    # HTTP_TIMEOUT lido na hora da chamada, nao congelado - mesmo cuidado do SshClient
    # (runtime/ssh.py) e do query_players (runtime/a2s.py).
    return http_probe.http_json(ssh_output, server, url, auth, corpo, HTTP_TIMEOUT, exigir_json)


def _valor_guardado(server: Servidor, coluna: str) -> str:
    try:
        return (server[coluna] or "").strip()
    except (IndexError, KeyError):
        return ""


def _player_deps() -> player_service.PlayerDeps:
    """As pecas que a contagem pede, montadas na hora da chamada.

    Na hora, e nao no import: `http_json`, `read_log_lines` e `query_players` sao nomes
    deste modulo que um teste pode trocar por falsos, e um bundle congelado no import
    passaria por cima da troca sem ninguem perceber.
    """
    return player_service.PlayerDeps(
        http_json=http_json, connect=_connect, read_log_lines=read_log_lines,
        query_players=query_players, players_ttl=PLAYERS_TTL,
    )


def http_login(server: Servidor) -> str:
    return player_service.http_login(_player_deps(), server)


def chama_api_do_jogo(server: Servidor, url: str, corpo: str = "",
                      exigir_json: bool = True):
    return player_service.chama_api_do_jogo(_player_deps(), server, url, corpo, exigir_json)


def players_from_http(server: Servidor) -> dict:
    return player_service.players_from_http(_player_deps(), server)


# ------------------------------------------- acoes sobre quem esta jogando
#
# Catalogo e regra em gamepanel.services.player_service; aqui ficam so os nomes que a
# tela, as rotas e os testes ja usam.

PLAYER_MSG_MAX = player_service.PLAYER_MSG_MAX
PLAYER_ACTION_LABELS = player_service.PLAYER_ACTION_LABELS
MARCA_BASE = player_service.MARCA_BASE
MARCA_JOGADOR = player_service.MARCA_JOGADOR
MARCA_MENSAGEM = player_service.MARCA_MENSAGEM
API_ACOES = player_service.API_ACOES
api_de_acoes = player_service.api_de_acoes
acoes_de_jogador = player_service.acoes_de_jogador
_preenche = player_service._preenche


def acao_de_jogador(server: Servidor, acao: str, jogador: str, mensagem: str) -> str:
    return player_service.acao_de_jogador(_player_deps(), server, acao, jogador, mensagem)


# ------------------------------------------------------ jogadores (pelo log)
#
# Implementacao real em gamepanel.runtime.log_probe (Fase 4). Nomes preservados aqui
# pelos mesmos dois motivos de sempre: teste direto por nome (`panel.compile_pattern`,
# `panel._apply_log_events`) e uso pelo resto de app.py ainda nao extraido (LOG_FOLLOW_SCRIPT
# alimenta o streaming de log em tempo real, mais adiante no arquivo).
LOG_SCAN_MAX = log_probe.LOG_SCAN_MAX
RE_MAX_LEN = log_probe.RE_MAX_LEN
LOG_HINT_WORDS = log_probe.LOG_HINT_WORDS
LOG_LINE_MAX = log_probe.LOG_LINE_MAX
LOG_FOLLOW_SCRIPT = log_probe.LOG_FOLLOW_SCRIPT
LOG_PATH_RE = log_probe.LOG_PATH_RE
compile_pattern = log_probe.compile_pattern
_apply_log_events = log_probe.apply_log_events
log_path_valido = log_probe.log_path_valido


# ------------------------------------------- descobrir como contar jogadores
#
# Implementacao real em gamepanel.runtime.port_probe (Fase 4). Nomes preservados aqui
# pelos mesmos dois motivos de sempre: teste direto por nome (`panel._portas_do_texto`,
# `panel._sem_repetir`, `panel._com_dono`, `panel._resume_genericos`) e uso por rotas
# que ainda nao foram extraidas.
QUERY_PORT_GUESSES = port_probe.QUERY_PORT_GUESSES
API_PORT_GUESSES = port_probe.API_PORT_GUESSES
HTTP_PROBE_TIMEOUT = float(os.environ.get("GAMEPANEL_PROBE_TIMEOUT", "2"))
HTTP_PROBE_PORTS_MAX = port_probe.HTTP_PROBE_PORTS_MAX
_portas_do_texto = port_probe._portas_do_texto
_sem_repetir = port_probe._sem_repetir
_com_dono = port_probe._com_dono
_resume_genericos = port_probe._resume_genericos


def candidate_ports(server: Servidor) -> tuple[list[int], list[int], dict, str]:
    return port_probe.candidate_ports(ssh_output, server, server["game_port"])


def probe_http_ports(server: Servidor, portas: list[int]) -> tuple[list[dict], list[int], str]:
    return port_probe.probe_http_ports(ssh_output, server, portas, HTTP_PROBE_TIMEOUT)


def probe_ports(host: str, portas: list[int]) -> list[dict]:
    return port_probe.probe_ports(host, portas, QUERY_TIMEOUT)


def read_log_lines(server: Servidor, limite: int = LOG_SCAN_MAX) -> list[str]:
    return log_probe.read_log_lines(
        ssh_output, server, server["service"], _valor_guardado(server, "log_path"), limite,
    )


def players_from_log(server: Servidor) -> dict:
    return player_service.players_from_log(_player_deps(), server)


# O MESMO objeto do service (nao uma copia): a fixture `banco` dos testes limpa a
# contagem guardada por este nome, e um dicionario diferente aqui deixaria o cache de
# verdade intacto entre os casos.
_players_cache = player_service._players_cache
invalidate_players = player_service.invalidate
player_source = player_service.player_source


def server_players(server: Servidor, force: bool = False) -> dict:
    return player_service.server_players(_player_deps(), server, force)


def all_players(servers) -> dict[int, dict]:
    # `server_players` vai por dentro de um lambda, e nao direto: assim o nome e
    # resolvido neste modulo a cada chamada, e a troca por um falso (monkeypatch nos
    # testes de alerta e de grafico) continua valendo dentro do paralelo.
    return player_service.all_players(
        lambda srv: server_players(srv), servers, QUERY_TIMEOUT * 3 + 2, MSG_TIMEOUT,
    )


# ------------------------------------------------------------------ recursos
#
# Script e leitura dos numeros em gamepanel.runtime.metrics_probe; cache e decisao em
# gamepanel.services.metrics_service. `server_metrics` segue aqui porque o resto de
# app.py — e o monkeypatch dos testes de alerta e de grafico — chama por ele.
#
# O MESMO dicionario do service: a fixture `banco` limpa o cache por este nome.
_metrics_cache = metrics_service._metrics_cache


def server_metrics(server: Servidor, force: bool = False) -> dict:
    return metrics_service.server_metrics(
        ssh_output, server, FILE_DEFAULT_PATH, METRICS_TTL, force)


def all_metrics(servers) -> dict[int, dict]:
    # `server_metrics` entra por lambda para o nome ser resolvido neste modulo a cada
    # chamada — e o que mantem a troca por um falso valendo dentro do paralelo.
    return parallel.por_servidor(
        lambda srv: server_metrics(srv), servers, 35, {"error": MSG_TIMEOUT})


# --------------------------------------------------------------- status cache

_status_cache = status_service._status_cache
invalidate_status = status_service.invalidate


def server_status(server: Servidor, force: bool = False) -> dict:
    return status_service.server_status(ssh_output, server, STATUS_TTL, force)


def all_status(servers) -> dict[int, dict]:
    return parallel.por_servidor(
        lambda srv: server_status(srv), servers, QUICK_TIMEOUT + 5,
        {"reachable": False, "service": "desconhecido", "error": MSG_TIMEOUT},
    )


# ------------------------------------------------------------------- jobs

# O que cada acao RODA no container. Como ela se apresenta (rotulo, icone, grupo,
# peso visual) e outra responsabilidade, e mora no `ui.py` — aqui ficam so os
# comandos, que e o que este modulo tem para dizer sobre elas.
COMANDOS = {
    "start": lambda s: q("systemctl", "start", s["service"]),
    "restart": lambda s: q("systemctl", "restart", s["service"]),
    "stop": lambda s: q("systemctl", "stop", s["service"]),
    "update": lambda s: "/usr/local/bin/update-game",
    "check-update": lambda s: "/usr/local/bin/check-game-update",
}

# As duas listas nao podem divergir em silencio: uma acao com botao e sem comando da
# 500 no clique, e uma com comando e sem botao e codigo morto que ninguem percebe.
assert set(COMANDOS) == set(ui.POR_CHAVE), "ui.ACOES e COMANDOS fora de sincronia"

# Forma antiga, montada a partir das duas: chave -> (rotulo, comando, confirma).
# Continua sendo o que `start_job` e o historico consomem.
ACTIONS = {
    chave: (ui.POR_CHAVE[chave].rotulo, comando, ui.POR_CHAVE[chave].confirma)
    for chave, comando in COMANDOS.items()
}

JOB_LABELS = {key: label for key, (label, _cmd, _c) in ACTIONS.items()}
JOB_LABELS["shell"] = "Comando no container"
JOB_LABELS["terminal"] = "Terminal interativo"
JOB_LABELS["edit-file"] = "Arquivo salvo"
JOB_LABELS["delete-file"] = "Arquivo apagado"
JOB_LABELS["edit-config"] = "Configuracao alterada"
JOB_LABELS["download-file"] = "Arquivo baixado"
JOB_LABELS["upload-file"] = "Arquivo enviado"
JOB_LABELS["backup"] = "Backup"
JOB_LABELS["restore-backup"] = "Backup restaurado"
JOB_LABELS["delete-backup"] = "Backup apagado"
# Moderacao nao da root em container nenhum: e operacao, e fica visivel para o operador.
JOB_LABELS["player-action"] = "Acao sobre jogador"
JOB_LABELS["broker-criar"] = "Instancia criada (broker)"
JOB_LABELS["broker-desativar"] = "Instancia desativada (broker)"
JOB_LABELS["broker-remover"] = "Instancia removida (broker)"
JOB_LABELS["broker-jogo"] = "Jogo adicionado ao catalogo"

# O historico guarda a saida INTEIRA do que rodou. Estas acoes so um admin consegue
# disparar (console, terminal, editor de arquivos), entao a saida delas — que carrega o
# comando digitado, o conteudo do arquivo e o que mais tenha passado pela tela — tambem
# so ele pode ler. Sem esta lista, o operador que leva 403 no console leria o resultado
# do console abrindo o job pelo id. 'edit-config' fica de fora de proposito: mexer na
# configuracao do jogo e coisa de operador, e a saida dela nao passa disso.
JOB_ACTIONS_ADMIN = frozenset({
    "shell", "terminal", "edit-file", "delete-file", "download-file",
    # 'backup' fica de fora: criar copia e operacao, e o operador pode dispara-la. Ja
    # restaurar e apagar destroem dado, e baixar tira o save do container — sao de admin,
    # e o registro delas acompanha.
    "upload-file", "restore-backup", "delete-backup",
    # Tudo do broker e de admin: a saida cita IP, CTID e portas da infraestrutura.
    "broker-criar", "broker-desativar", "broker-remover", "broker-jogo",
})


def job_label(action: str) -> str:
    return JOB_LABELS.get(action, action)


def job_ou_403(job: sqlite3.Row) -> None:
    """Barra o operador na saida de um job que ele nao teria permissao de disparar."""
    if job["action"] in JOB_ACTIONS_ADMIN and not is_admin():
        abort(403, "Este registro e de uma acao restrita a administradores do painel.")


def filtro_de_papel() -> tuple[str, tuple]:
    """Pedaco de WHERE que esconde do operador os jobs das acoes restritas.

    Sai daqui e nao de cada consulta porque sao duas telas (o historico do servidor e o
    global) e uma rota de API: a lista de acoes tem de ser a mesma nos tres.
    """
    if is_admin():
        return "", ()
    escondidas = tuple(sorted(JOB_ACTIONS_ADMIN))
    marcadores = ",".join("?" * len(escondidas))
    return f" AND action NOT IN ({marcadores})", escondidas


def jobs_do_servidor(conn: sqlite3.Connection, sid: int, limite: int) -> list:
    """Historico do servidor ja filtrado pelo papel de quem esta olhando."""
    corte, valores = filtro_de_papel()
    return conn.execute(
        f"SELECT * FROM jobs WHERE server_id = ?{corte} ORDER BY id DESC LIMIT ?",
        (sid, *valores, limite),
    ).fetchall()


def _id_inserido(cur: sqlite3.Cursor) -> int:
    """O id da linha recem-inserida.

    `lastrowid` e Optional no tipo porque um cursor pode nao ter inserido nada; depois
    de um INSERT que deu certo, nunca. Falhar alto aqui e melhor do que espalhar um
    `or 0` que viraria "job numero zero" no historico.
    """
    if cur.lastrowid is None:
        raise RuntimeError("INSERT nao devolveu id da linha")
    return cur.lastrowid


def log_job(
    action: str,
    server: Servidor | dict,
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
    return _id_inserido(cur)


def start_job(
    action: str,
    server: Servidor,
    username: str,
    remote_cmd: str | None = None,
    command: str = "",
    timeout: int = JOB_TIMEOUT,
) -> int:
    # Resolvido AQUI, e nao dentro do `run()` la embaixo: o que a thread executa nao
    # pode depender de um parametro opcional que alguem mude no meio do caminho.
    comando_remoto: str = remote_cmd if remote_cmd is not None else ACTIONS[action][1](server)
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
    job_id = _id_inserido(cur)
    server_id = int(server["id"])
    # A thread nao pode usar a Row ligada a conexao do request: copia o que precisa.
    target = dict(server)

    def run():
        try:
            # Conexao propria: um update leva quase uma hora, e a mestre compartilhada
            # ficaria presa a ele — com o monitor inteiro dependendo de um comando que
            # pode cair no meio.
            proc = ssh_run(target, comando_remoto, timeout=timeout, multiplex=False)
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
        # Falha de tarefa AGENDADA vira alerta: e a unica que ninguem esta olhando. Quem
        # clicou o botao ja esta com o resultado na tela.
        if status == "error" and username == SCHEDULE_USER:
            try:
                notifica(conn2, "job-falhou",
                         f"{target.get('name', '?')}: {job_label(action)} falhou",
                         (output or "").strip()[-500:])
            # Alerta nunca derruba o job.
            except Exception:  # noqa: BLE001
                app.logger.exception("falha ao avisar sobre o job %s", job_id)
        conn2.close()
        invalidate_status(server_id)

    threading.Thread(target=run, daemon=True).start()
    return job_id


# ----------------------------------------------------------------- alertas
#
# O painel ja sabe o estado de cada servidor (e a tela do dashboard pergunta isso o
# tempo inteiro). O que faltava era ele CONTAR para alguem sem ninguem estar olhando: um
# POST de JSON para a URL que o Discord ou o Slack dao de graca.

ALERT_EVENTS = {
    "caiu": "Servidor parou de rodar",
    "voltou": "Servidor voltou a rodar",
    "quebrou": "Jogo quebrou (servico em 'failed')",
    "reiniciando": "Jogo caindo em loop de restart",
    "travou": "Jogo nao responde (de pe, mas mudo)",
    "respondeu": "Jogo voltou a responder",
    "jogador-entrou": "Jogador conectou",
    "jogador-saiu": "Jogador desconectou",
    "erro-no-log": "Erro no log do jogo",
    "inacessivel": "Painel perdeu contato (SSH)",
    "acessivel": "Contato restabelecido",
    "job-falhou": "Tarefa agendada falhou",
    "disco-cheio": "Disco quase cheio",
    "memoria-alta": "Memoria quase cheia",
    "cpu-alta": "Uso de CPU alto",
}
# Precisam de configuracao no cadastro do servidor para fazer alguma coisa. A tela avisa
# quem esta marcado sem ter onde olhar — senao o alerta fica ligado e mudo, e a pessoa
# conclui que o jogo nunca falha.
ALERT_PRECISA_CONFIG = {
    "travou": "contagem de jogadores por consulta (A2S) ou API HTTP",
    "respondeu": "contagem de jogadores por consulta (A2S) ou API HTTP",
    "jogador-entrou": "contagem de jogadores (A2S, API HTTP ou log)",
    "jogador-saiu": "contagem de jogadores (A2S, API HTTP ou log)",
    "erro-no-log": "uma expressao de erro no cadastro do servidor",
}
# O que vem ligado: as mas noticias que funcionam sem configurar nada. 'voltou',
# 'acessivel' e 'respondeu' sao alivio, nao urgencia — quem quiser o par completo liga na
# tela. 'erro-no-log' fica fora porque custa uma ida de SSH a mais por servidor e nao faz
# nada sem uma expressao cadastrada.
ALERT_DEFAULT = "caiu,quebrou,reiniciando,travou,inacessivel,job-falhou,disco-cheio"
DISK_PCT_DEFAULT = 90
MEM_PCT_DEFAULT = 90
CPU_PCT_DEFAULT = 90
# Os tres saem da MESMA leitura do medidor: com o cache de server_metrics no meio, olhar
# os tres custa uma ida de SSH so, entao eles andam juntos no mesmo relogio.
RECURSO_EVENTOS = {"disco-cheio", "memoria-alta", "cpu-alta"}
# Quantas linhas do diario de alertas ficam guardadas.
ALERT_LOG_KEEP = int(os.environ.get("GAMEPANEL_ALERT_LOG_KEEP", "500"))

# Quantas voltas seguidas o jogo precisa ficar mudo antes do alerta. Uma consulta A2S e
# UDP: um pacote perdido e rotina, e alertar no primeiro silencio encheria o canal de
# susto falso.
MUTE_ROUNDS = max(1, int(os.environ.get("GAMEPANEL_MUTE_ROUNDS", "3")))
# O log e o unico destes que custa uma ida de SSH propria, entao tem o seu intervalo.
LOG_CHECK_EVERY = float(os.environ.get("GAMEPANEL_LOG_CHECK_EVERY", "120"))
# Quantas linhas do fim do log olhar em cada passada.
LOG_ERR_LINES = 200
# Teto de um alerta de log por servidor nesta janela. A expressao vem da tela e um '.'
# distraido casa com tudo — sem esta trava, um engano de digitacao vira uma enxurrada.
LOG_ERR_COOLDOWN = float(os.environ.get("GAMEPANEL_LOG_ERR_COOLDOWN", "600"))


def config_get(conn: sqlite3.Connection, chave: str, padrao: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (chave,)).fetchone()
    return row["value"] if row else padrao


def config_set(conn: sqlite3.Connection, chave: str, valor: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (chave, valor),
        )


def limpa_eventos(bruto: str) -> set:
    """Filtra pela lista conhecida: evento que saiu do codigo nao volta pelo banco."""
    return {e for e in (bruto or "").split(",") if e in ALERT_EVENTS}


def webhooks_lista(conn: sqlite3.Connection) -> list:
    """Todos os destinos, na ordem de cadastro, com os eventos ja como conjunto."""
    linhas = conn.execute(
        "SELECT id, nome, url, eventos, ativo FROM webhooks ORDER BY id"
    ).fetchall()
    return [
        {
            "id": r["id"],
            "nome": r["nome"] or "Sem nome",
            "url": r["url"],
            "url_curta": mascara_url(r["url"]),
            "eventos": limpa_eventos(r["eventos"]),
            "ativo": bool(r["ativo"]),
        }
        for r in linhas
    ]


def webhook_config(conn: sqlite3.Connection) -> dict:
    """Estado dos alertas: os destinos, o que o conjunto deles cobre, e o limite do disco.

    'eventos' e a UNIAO dos destinos ligados — e o que o monitor usa para decidir se vale
    a pena olhar alguma coisa. Quem recebe o que se resolve depois, destino a destino.
    """
    try:
        disco = int(config_get(conn, "webhook_disk_pct", str(DISK_PCT_DEFAULT)))
    except ValueError:
        disco = DISK_PCT_DEFAULT
    try:
        memoria = int(config_get(conn, "webhook_mem_pct", str(MEM_PCT_DEFAULT)))
    except ValueError:
        memoria = MEM_PCT_DEFAULT
    try:
        cpu = int(config_get(conn, "webhook_cpu_pct", str(CPU_PCT_DEFAULT)))
    except ValueError:
        cpu = CPU_PCT_DEFAULT
    destinos = webhooks_lista(conn)
    cobertos = set()
    for d in destinos:
        if d["ativo"] and d["url"]:
            cobertos |= d["eventos"]
    return {
        "destinos": destinos,
        "ativos": [d for d in destinos if d["ativo"] and d["url"]],
        "eventos": cobertos,
        "disco": min(100, max(50, disco)),
        "memoria": min(100, max(50, memoria)),
        "cpu": min(100, max(50, cpu)),
    }


mascara_url = webhook_client.mascara_url


def envia_webhook(url: str, texto: str) -> str:
    # Nome proprio (e nao `webhook_client.envia` direto nas chamadas) porque a fixture
    # `webhooks` do conftest troca ESTE nome por um capturador — todo teste de alerta
    # depende disso para ver o que sairia por HTTP sem nada sair de verdade.
    return webhook_client.envia(url, texto, WEBHOOK_TIMEOUT, WEBHOOK_UA)


def notifica(conn: sqlite3.Connection, evento: str, titulo: str, detalhe: str = "") -> bool:
    """Manda o alerta para cada destino que pediu esse evento.

    Devolve se saiu para ALGUEM. Um destino fora do ar (Discord de pe, Slack caido) nao
    cala os outros: cada um e tentado e cada falha vai para o log com o nome do destino,
    entao da para saber qual deles esta quebrado sem adivinhar.
    """
    alvos = [d for d in webhooks_lista(conn)
             if d["ativo"] and d["url"] and evento in d["eventos"]]
    if not alvos:
        # Registrado de proposito: "o alerta disparou e ninguem pediu por ele" e a causa
        # mais comum de canal mudo, e e indistinguivel de "nao aconteceu nada" para quem
        # so olha o Discord. No diario as duas viram coisas diferentes.
        _registra_alerta(conn, evento, titulo, detalhe, "", "sem-destino")
        return False
    texto = f"**{titulo}**"
    if detalhe:
        texto += f"\n{detalhe}"
    saiu = False
    for destino in alvos:
        erro = envia_webhook(destino["url"], texto)
        if erro:
            app.logger.warning(
                "alerta '%s' nao saiu para '%s': %s", evento, destino["nome"], erro
            )
            _registra_alerta(conn, evento, titulo, detalhe, destino["nome"],
                             "falhou", erro)
        else:
            saiu = True
            _registra_alerta(conn, evento, titulo, detalhe, destino["nome"], "enviado")
    return saiu


def _registra_alerta(conn: sqlite3.Connection, evento: str, titulo: str, detalhe: str,
                     destino: str, status: str, erro: str = "") -> None:
    """Grava uma linha do diario.

    Engole o proprio erro de proposito: o diario existe para explicar o alerta, e seria
    absurdo ele impedir o alerta de sair. No pior caso fica sem registro, nunca sem envio.
    """
    try:
        with conn:
            conn.execute(
                "INSERT INTO alert_log (criado_em, evento, titulo, detalhe, destino,"
                " status, erro) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now_iso(), evento, titulo[:200], detalhe[:500], destino[:80],
                 status, erro[:300]))
    except sqlite3.Error:
        app.logger.exception("nao consegui gravar no diario de alertas")


def alertas_recentes(conn: sqlite3.Connection, limite: int = 60) -> list[dict]:
    """As ultimas linhas do diario, da mais nova para a mais velha."""
    linhas = conn.execute(
        "SELECT * FROM alert_log ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
    return [dict(l) for l in linhas]


def _job_recente(conn: sqlite3.Connection, sid: int) -> bool:
    """Teve acao do painel neste servidor ha pouco?

    Reiniciar pelo botao derruba o servico por alguns segundos, e isso NAO e uma queda.
    Sem esta janela, todo restart e todo update viraria alerta.
    """
    corte = (datetime.now(timezone.utc) - timedelta(seconds=ALERT_QUIET)).isoformat()
    return conn.execute(
        "SELECT 1 FROM jobs WHERE server_id = ? AND created_at >= ?"
        " AND action IN ('start','stop','restart','update','restore-backup') LIMIT 1",
        (sid, corte),
    ).fetchone() is not None


# server_id -> ultimo estado visto. Fica so na memoria de proposito: reiniciar o painel
# refaz a linha de base, e ninguem recebe um alerta de algo que ja estava assim.
_estado_monitor: dict[int, dict] = {}
_ultimo_monitor = 0.0
_ultimo_estado = 0.0
_ultimo_disco = 0.0
_ultimo_log = 0.0


def _alert_deps() -> alert_service.AlertDeps:
    """As pecas que as regras de alerta pedem, montadas na hora da chamada.

    Na hora, e nao no import: `server_players`, `server_metrics` e `notifica` sao nomes
    deste modulo, e os testes de alerta trocam os dois primeiros por falsos a cada caso
    — um bundle congelado no import passaria por cima da troca em silencio.
    """
    return alert_service.AlertDeps(
        notifica=notifica, job_recente=_job_recente, player_source=player_source,
        server_players=server_players, server_metrics=server_metrics,
        read_log_lines=read_log_lines, valor_guardado=_valor_guardado,
        tamanho_legivel=_human_size, estado_monitor=_estado_monitor,
        logger=app.logger, mute_rounds=MUTE_ROUNDS, log_err_lines=LOG_ERR_LINES,
        log_err_cooldown=LOG_ERR_COOLDOWN,
    )


def _alerta_de_estado(conn, server, estado, anterior) -> None:
    alert_service.alerta_de_estado(_alert_deps(), conn, server, estado, anterior)


def _alerta_de_restart(conn, server, estado, anterior) -> None:
    alert_service.alerta_de_restart(_alert_deps(), conn, server, estado, anterior)


def _alerta_de_mudez(conn, server, estado, anterior) -> None:
    alert_service.alerta_de_mudez(_alert_deps(), conn, server, estado, anterior)


def _alerta_de_log(conn, server, anterior) -> None:
    alert_service.alerta_de_log(_alert_deps(), conn, server, anterior)


def _alerta_de_disco(conn, server, cfg) -> None:
    alert_service.alerta_de_disco(_alert_deps(), conn, server, cfg)


def _alerta_de_memoria(conn, server, cfg) -> None:
    alert_service.alerta_de_memoria(_alert_deps(), conn, server, cfg)


def _alerta_de_cpu(conn, server, cfg) -> None:
    alert_service.alerta_de_cpu(_alert_deps(), conn, server, cfg)


# Evento de recurso -> quem confere. Os tres leem o MESMO medidor e andam no mesmo
# relogio; como tabela, ligar um quarto (rede, por exemplo) e acrescentar uma linha,
# nao mais um `if` dentro do laco do monitor.
#
# Aponta para as funcoes DESTE modulo, nao para as do service: a tabela captura o
# objeto no import, e e por estes nomes que os testes chamam.
ALERTAS_DE_RECURSO = {
    "disco-cheio": _alerta_de_disco,
    "memoria-alta": _alerta_de_memoria,
    "cpu-alta": _alerta_de_cpu,
}


def _alerta_de_jogadores(conn, server, servico, anterior, cfg) -> None:
    alert_service.alerta_de_jogadores(_alert_deps(), conn, server, servico, anterior, cfg)


_leitura_de_jogadores = alert_service.leitura_de_jogadores
_texto_de_online = alert_service.texto_de_online


# ------------------------------------------------- log em tempo real
#
# Contagem por log era o unico caso sem jeito de ficar rapida: cada conferida e uma ida de
# SSH que arrasta o log inteiro, entao perguntar de 15 em 15 segundos custaria megabytes
# por minuto para achar duas linhas. A saida e parar de perguntar: uma conexao SSH longa
# com `journalctl -f` deixa o painel OUVINDO, e a linha chega no segundo em que sai.
#
# O ponto do desenho: o stream e um GATILHO, nao uma segunda contagem. Ele so diz "algo
# aconteceu" e manda refazer a conta pelo caminho de sempre. Reproduzir aqui a maquina de
# estados do log seria um segundo lugar para errar — e pior, um que divergiria em silencio
# do numero que a tela mostra.

# Um alerta de jogador por servidor de cada vez: o stream e a volta do monitor mexem no
# MESMO _estado_monitor[sid], e sem isto os dois poderiam avisar a mesma entrada.
_jogadores_locks: dict[int, threading.Lock] = {}
_jogadores_meta = threading.Lock()


def lock_de_jogadores(sid: int) -> threading.Lock:
    with _jogadores_meta:
        return _jogadores_locks.setdefault(sid, threading.Lock())


def _log_stream_deps() -> log_stream.LogStreamDeps:
    return log_stream.LogStreamDeps(
        ssh_argv=ssh_argv, estado_monitor=_estado_monitor,
        invalidate_players=invalidate_players, connect=_connect,
        webhook_config=webhook_config, lock_de_jogadores=lock_de_jogadores,
        alerta_de_jogadores=_alerta_de_jogadores, logger=app.logger,
        debounce=LOG_STREAM_DEBOUNCE, retry=LOG_STREAM_RETRY,
    )


class _LogStream(log_stream.LogStream):
    """A conexao de log com as pecas do painel ja ligadas.

    Subclasse (e nao `functools.partial`) para continuar sendo uma CLASSE de dois
    argumentos: o supervisor a troca por um dublê nos testes, e ha teste que a constroi
    direto para conferir que um regex torto faz a thread desistir.
    """

    def __init__(self, server, assinatura):
        super().__init__(_log_stream_deps(), server, assinatura)


def _linha_de_jogador(linha: str, entrar, sair) -> bool:
    return log_stream.linha_de_jogador(linha, entrar, sair)


def _assinatura_de_stream(server) -> tuple:
    return log_stream.assinatura_de_stream(server, _valor_guardado)


def streams_desejados(servidores, cfg) -> dict[int, tuple]:
    return log_stream.streams_desejados(
        servidores, cfg, LOG_STREAM, player_source, _valor_guardado)


# `_LogStream` vai por lambda: o nome e resolvido neste modulo a cada abertura, que e o
# que deixa o teste do supervisor troca-lo por um dublê sem SSH.
_supervisor = log_stream.Supervisor(lambda server, assinatura: _LogStream(server, assinatura))
# O MESMO dicionario do supervisor: a fixture do teste o limpa por este nome.
_streams = _supervisor.abertos


def streams_vivos() -> int:
    return _supervisor.vivos()


def supervisiona_streams() -> int:
    """Liga, desliga e ressuscita as conexoes de log. Devolve quantas ficaram registradas."""
    conn = db()
    servidores = conn.execute(SQL_ALL_SERVERS).fetchall()
    return _supervisor.sincroniza(servidores, streams_desejados(servidores, webhook_config(conn)))


class _Ritmo(NamedTuple):
    """O que ESTA volta do monitor vai conferir.

    Nem tudo anda no mesmo passo, e a razao e custo: a contagem de jogadores pergunta
    direto ao jogo (barato), estado/mudez/restart custam um SSH por servidor, disco,
    memoria e CPU saem de um medidor caro que vale ler junto, e o log custa uma ida de
    SSH so dele. Separar essa decisao do laco e o que fez a funcao de monitorar caber
    na cabeca: aqui e "o que vence agora", la e "o que fazer com cada servidor".
    """

    ver_estado: bool
    quer_jogadores: bool
    recursos: set
    ver_log: bool


def _ritmo_do_monitor(cfg: dict, agora: float, forcar: bool) -> _Ritmo | None:
    """Decide o que vence nesta volta e adianta os relogios. None = ainda nao e hora."""
    global _ultimo_monitor, _ultimo_estado, _ultimo_disco, _ultimo_log

    # O passo do monitor e o do alerta mais apressado que esteja LIGADO. Com jogadores
    # ligados a volta fica curta; sem eles nada muda em relacao a antes.
    quer_jogadores = bool(cfg["eventos"] & {"jogador-entrou", "jogador-saiu"})
    passo = min(MONITOR_EVERY, PLAYER_CHECK_EVERY) if quer_jogadores else MONITOR_EVERY
    if not forcar and agora - _ultimo_monitor < passo:
        return None
    _ultimo_monitor = agora

    # ...mas so a contagem de jogadores anda nesse passo curto. Estado do servico, mudez
    # e restart continuam no ritmo antigo: cada um deles custa SSH por servidor, e
    # acelerar tudo junto multiplicaria essa conta por quatro sem necessidade.
    ver_estado = forcar or agora - _ultimo_estado >= MONITOR_EVERY
    if ver_estado:
        _ultimo_estado = agora

    # Um relogio so para disco, memoria e CPU: os tres leem o mesmo medidor, e dar um
    # ritmo proprio a cada um multiplicaria as idas de SSH sem enxergar nada novo.
    vence_recurso = forcar or agora - _ultimo_disco >= DISK_CHECK_EVERY
    recursos = cfg["eventos"] & RECURSO_EVENTOS if vence_recurso else set()
    if recursos:
        _ultimo_disco = agora

    # O log e o unico que custa uma ida de SSH so dele, entao anda no seu proprio ritmo.
    ver_log = "erro-no-log" in cfg["eventos"] and (
        forcar or agora - _ultimo_log >= LOG_CHECK_EVERY
    )
    if ver_log:
        _ultimo_log = agora

    return _Ritmo(ver_estado, quer_jogadores, recursos, ver_log)


def _volta_curta(conn, server, anterior, cfg, ritmo: _Ritmo) -> None:
    """A volta de 15s: so jogadores, e sem tocar no SSH.

    O servico que interessa aqui e "estava de pe na ultima olhada de verdade", e isso
    ja esta guardado. Se ele tiver caido desde entao, a consulta ao proprio jogo falha
    e `_alerta_de_jogadores` sai sem avisar nada — o atraso de um estado velho nao
    inventa alerta.

    Contagem por log fica de fora: ela custa SSH, e pagar isso a cada 15s so para reler
    o mesmo log inteiro nao se sustenta. Esses servidores continuam avisando no ritmo
    da volta completa.
    """
    if not ritmo.quer_jogadores or anterior is None:
        return
    if player_source(server) not in PLAYER_FAST_SOURCES:
        return
    with lock_de_jogadores(int(server["id"])):
        _alerta_de_jogadores(conn, server, anterior.get("service", ""), anterior, cfg)


def _alertas_do_servidor(conn, server, estado, anterior, cfg, ritmo: _Ritmo) -> None:
    """Os alertas que so fazem sentido com o container ALCANCAVEL."""
    if "reiniciando" in cfg["eventos"]:
        _alerta_de_restart(conn, server, estado, anterior)
    else:
        # Sem o evento ligado o contador ainda precisa acompanhar, senao ligar o alerta
        # no meio do dia renderia um "loop" falso com tudo o que se acumulou enquanto
        # ele estava desligado.
        anterior["restarts"] = int(estado.get("restarts") or 0)

    # Este custa uma sondagem no jogo (UDP ou HTTP) — nao vale a pena pagar por ela com
    # o evento desligado.
    if cfg["eventos"] & {"travou", "respondeu"}:
        _alerta_de_mudez(conn, server, estado, anterior)

    if ritmo.quer_jogadores:
        # Com stream de log ligado esta chamada vira rede de seguranca: se ele tiver
        # caido, ninguem fica sem aviso — so mais devagar. O lock e o que impede os dois
        # de avisarem a mesma entrada.
        with lock_de_jogadores(int(server["id"])):
            _alerta_de_jogadores(conn, server, estado["service"], anterior, cfg)

    if ritmo.ver_log:
        _alerta_de_log(conn, server, anterior)

    for evento, checa in ALERTAS_DE_RECURSO.items():
        if evento in ritmo.recursos:
            checa(conn, server, cfg)


def monitora_servidores(forcar: bool = False) -> int:
    """Confere o estado de todo mundo e dispara o que mudou. Devolve quantos olhou."""
    conn = db()
    cfg = webhook_config(conn)
    # Sem nenhum destino ligado pedindo algum evento, a volta inteira seria SSH gasto
    # para produzir um alerta que ninguem receberia.
    if not cfg["eventos"]:
        return 0

    ritmo = _ritmo_do_monitor(cfg, time.monotonic(), forcar)
    if ritmo is None:
        return 0

    servidores = conn.execute(SQL_ALL_SERVERS).fetchall()
    for server in servidores:
        sid = int(server["id"])
        anterior = _estado_monitor.get(sid)

        if not ritmo.ver_estado:
            _volta_curta(conn, server, anterior, cfg, ritmo)
            continue

        estado = server_status(server)
        if anterior is None:
            # Primeira olhada: so anota. Alertar aqui encheria o canal de "esta parado"
            # toda vez que o painel reiniciasse. Vale para o contador de restarts do
            # mesmo jeito: o que interessa e quanto ele sobe DAQUI para a frente.
            _estado_monitor[sid] = {"reachable": estado["reachable"],
                                    "service": estado["service"],
                                    "restarts": int(estado.get("restarts") or 0)}
            continue

        _alerta_de_estado(conn, server, estado, anterior)
        if estado["reachable"]:
            _alertas_do_servidor(conn, server, estado, anterior, cfg, ritmo)
        # Depois dos alertas: eles precisam comparar com o estado ANTERIOR, e atualizar
        # antes faria toda mudanca desaparecer no meio do caminho.
        anterior.update(reachable=estado["reachable"], service=estado["service"])

    _esquece_servidores_removidos(servidores)
    return len(servidores)


def _esquece_servidores_removidos(servidores) -> None:
    """Servidor removido do painel nao pode ficar guardando estado para sempre."""
    vivos = {int(s["id"]) for s in servidores}
    for morto in [k for k in _estado_monitor if k not in vivos]:
        _estado_monitor.pop(morto, None)


# -------------------------------------------------------- amostras de uso

_ultima_amostra = 0.0


def coleta_amostras(forcar: bool = False) -> int:
    """Guarda uma linha de CPU/memoria/jogadores por servidor. Devolve quantas gravou."""
    global _ultima_amostra
    agora = time.monotonic()
    if not forcar and agora - _ultima_amostra < SAMPLE_EVERY:
        return 0
    _ultima_amostra = agora

    conn = db()
    carimbo = now_iso()
    linhas = []
    for server in conn.execute(SQL_ALL_SERVERS).fetchall():
        dados = server_metrics(server)
        if dados.get("error"):
            # Container fora do ar nao vira linha: um buraco no grafico e a informacao
            # certa, e zero seria mentira (nao foi "usou 0% de CPU").
            continue
        contagem = None
        if player_source(server):
            try:
                jogando = server_players(server)
                contagem = None if jogando.get("error") else jogando.get("players")
            except (QueryError, RemoteError):
                contagem = None
        linhas.append((
            int(server["id"]), carimbo, dados.get("cpu_pct"),
            (dados.get("mem") or {}).get("pct"), contagem,
        ))

    if linhas:
        with conn:
            conn.executemany(
                "INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
                " VALUES (?,?,?,?,?)", linhas,
            )
    return len(linhas)


# ------------------------------------------------------------- agendamento
#
# Uma thread so, acordando a cada SCHEDULE_TICK, olha o que venceu e dispara pelo MESMO
# start_job das telas — tarefa agendada aparece no historico como qualquer outra, com
# 'agendador' no lugar do usuario.
#
# Isto depende de o painel rodar com UM worker (e como o gunicorn e configurado aqui,
# veja o provision-admin-lxc.sh): com dois processos, cada um teria a sua thread e a
# mesma tarefa dispararia em dobro.

# Conta do relogio em gamepanel.services.schedule_service; os nomes seguem aqui porque
# as rotas de agendamento, os templates e os testes chamam por eles.
SCHEDULE_KINDS = schedule_service.SCHEDULE_KINDS
SCHEDULE_ACTIONS = schedule_service.SCHEDULE_ACTIONS
DIAS_SEMANA = schedule_service.DIAS_SEMANA
ARTIGO_DIA = schedule_service.ARTIGO_DIA
EVERY_HOURS_MAX = schedule_service.EVERY_HOURS_MAX
agora_local = schedule_service.agora_local
rotulo_agendamento = schedule_service.rotulo_agendamento
ocorrencia_anterior = schedule_service.ocorrencia_anterior
# Usado tambem pelas rotas de agendamento e pelo grafico, fora desta secao.
_parse_dt = schedule_service._parse_dt


def venceu(sched, agora: datetime) -> bool:
    return schedule_service.venceu(sched, agora, SCHEDULE_GRACE)


def dispara_agendamento(conn: sqlite3.Connection, sched) -> int:
    """Coloca a tarefa para rodar. Devolve o id do job (0 quando nao deu para disparar)."""
    server = conn.execute(SQL_SERVER_BY_ID, (sched["server_id"],)).fetchone()
    if not server:
        return 0
    if sched["action"] == "backup":
        caminhos = backup_paths(server)
        if not caminhos:
            return 0  # sem o que guardar: nao adianta acordar o container
        remoto, limite = comando_de_backup(server, caminhos), BACKUP_TIMEOUT
    else:
        remoto, limite = ACTIONS[sched["action"]][1](server), JOB_TIMEOUT
    job_id = start_job(
        sched["action"], server, SCHEDULE_USER, remote_cmd=remoto,
        command=f"agendado: {rotulo_agendamento(sched)}", timeout=limite,
    )
    invalidate_status(int(server["id"]))
    return job_id


def roda_agendamentos() -> int:
    """Uma passada do relogio. Devolve quantas tarefas disparou."""
    agora = agora_local()
    conn = db()
    disparadas = 0
    for sched in conn.execute("SELECT * FROM schedules WHERE enabled = 1").fetchall():
        if sched["action"] not in SCHEDULE_ACTIONS or not venceu(sched, agora):
            continue
        # Marca ANTES de disparar: se o job demorar (um update leva quase uma hora), a
        # proxima volta do relogio nao pode achar que a tarefa ainda esta vencida.
        with conn:
            conn.execute("UPDATE schedules SET last_run = ? WHERE id = ?",
                         (agora.isoformat(), sched["id"]))
        if dispara_agendamento(conn, sched):
            disparadas += 1
    return disparadas


_ultima_limpeza = 0.0


def limpa_historico(forcar: bool = False) -> int:
    """Apaga o que envelheceu — jobs e amostras. Devolve quantos JOBS sairam.

    As duas limpezas andam juntas porque tem a mesma razao de existir (o banco do painel
    nao pode crescer para sempre) e o mesmo relogio de hora em hora; so os prazos mudam,
    porque uma amostra e minuscula perto da saida de um job.
    """
    global _ultima_limpeza
    agora = time.monotonic()
    if not forcar and agora - _ultima_limpeza < JOBS_PURGE_EVERY:
        return 0
    _ultima_limpeza = agora
    conn = db()

    if SAMPLES_KEEP_DAYS:
        velhas = (datetime.now(timezone.utc)
                  - timedelta(days=SAMPLES_KEEP_DAYS)).isoformat()
        with conn:
            conn.execute("DELETE FROM samples WHERE taken_at < ?", (velhas,))

    # O diario se mede em linhas, nao em dias: o que se quer dele e "as ultimas N", e um
    # prazo em dias deixaria a tela vazia justo num painel quieto, que e quando a duvida
    # "sera que isso ainda funciona?" aparece.
    with conn:
        conn.execute(
            "DELETE FROM alert_log WHERE id <= "
            "(SELECT MIN(id) FROM (SELECT id FROM alert_log ORDER BY id DESC LIMIT ?)) - 1",
            (ALERT_LOG_KEEP,))

    if not JOBS_KEEP_DAYS:
        return 0
    corte = (datetime.now(timezone.utc) - timedelta(days=JOBS_KEEP_DAYS)).isoformat()
    with conn:
        cur = conn.execute("DELETE FROM jobs WHERE created_at < ?", (corte,))
    return cur.rowcount or 0


def _falha_do_relogio(nome: str) -> None:
    """Anota no log do processo E no diario de alertas.

    O diario e o que a pessoa consegue ver: o traceback no stderr do gunicorn so aparece
    para quem sabe procurar, e a queixa que traz alguem ate aqui e sempre a mesma — "nao
    chega nada no Discord".
    """
    app.logger.exception("falha na tarefa '%s' do relogio", nome)
    try:
        _registra_alerta(db(), "", f"a tarefa '{nome}' do relogio falhou",
                         traceback.format_exc(limit=4)[-500:], "", "erro-interno")
    # Registrar a falha nao pode virar outra falha.
    except Exception:  # noqa: BLE001
        pass


def _scheduler_tick() -> None:
    """Uma volta do relogio. Precisa de contexto de aplicacao por causa do db().

    A lista e montada a cada volta, e nao guardada: cada nome e resolvido neste modulo
    na hora, que e o que deixa o teste trocar uma tarefa por uma que explode.
    """
    scheduler.tick(
        (("agendamentos", roda_agendamentos),
         ("monitor", monitora_servidores),
         ("log-em-tempo-real", supervisiona_streams),
         ("amostras", coleta_amostras),
         ("limpeza", limpa_historico)),
        _falha_do_relogio,
    )


def _com_contexto() -> None:
    # Contexto de aplicacao: e o que faz o db() desta thread funcionar como o das rotas
    # (conexao propria, fechada no fim pelo teardown).
    with app.app_context():
        _scheduler_tick()


_relogio = scheduler.Relogio(SCHEDULE_TICK, _com_contexto, app.logger)


def start_scheduler() -> None:
    _relogio.start()


# ------------------------------------------------------------------- rotas


def destino_seguro(bruto: str) -> str:
    r"""Para onde voltar depois do login. Vazio quando o destino nao e do painel.

    Comecar com "/" nao basta: para o navegador "//evil.com" e "/\evil.com" sao enderecos
    ABSOLUTOS, e mandariam quem acabou de digitar a senha para fora do painel.
    """
    destino = (bruto or "").strip()
    if not destino.startswith("/") or destino[:2] in ("//", "/\\"):
        return ""
    if any(c in destino for c in "\r\n\t"):
        return ""
    return destino


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
            proximo = destino_seguro(request.args.get("next", ""))
            if row["totp_enabled"]:
                # Senha certa NAO abre a sessao: so guarda "esta pessoa passou da senha, falta o
                # codigo". Sem `uid` na sessao, nenhuma rota do painel a reconhece como logada.
                session.clear()
                session["pre2fa"] = {"uid": row["id"], "ate": time.time() + PRE_2FA_SEGUNDOS,
                                     "proximo": proximo}
                csrf_token()
                return redirect(url_for("login_2fa"))
            return _abre_sessao(row, proximo)
        _record_fail(key)
        flash("Usuario ou senha invalidos.", "error")
        return render_template(TPL_LOGIN), 401
    return render_template(TPL_LOGIN)


# Tempo para digitar o codigo depois de acertar a senha.
PRE_2FA_SEGUNDOS = 300
# O chute de 6 digitos tem 3 numeros validos em 10^6: por isso a trava do codigo e por USUARIO
# (nao por IP, que um atacante troca) e mais longa que a da senha.
LOCKOUT_2FA_TENTATIVAS = 5
LOCKOUT_2FA_JANELA = 900.0


def _abre_sessao(row: sqlite3.Row, proximo: str = ""):
    session.clear()
    session["uid"] = row["id"]
    session["username"] = row["username"]
    session.permanent = True
    csrf_token()
    return redirect(proximo or url_for("dashboard"))


def _confere_segundo_fator(row: sqlite3.Row, digitado: str) -> bool:
    """Codigo do aplicativo OU um codigo de recuperacao (que se gasta). Vale so uma vez."""
    conn = db()
    passo = totp.verify(row["totp_secret"], digitado, time.time(), row["totp_last_step"])
    if passo is not None:
        with conn:
            # O `WHERE` faz do UPDATE o portao: dois pedidos com o mesmo codigo ao mesmo tempo
            # nao passam os dois (o segundo nao encontra a linha com passo menor).
            gasto = conn.execute(
                "UPDATE users SET totp_last_step = ? WHERE id = ? AND totp_last_step < ?",
                (passo, row["id"], passo),
            ).rowcount
        return gasto == 1
    try:
        guardados = json.loads(row["totp_recovery"] or "[]")
    except ValueError:
        guardados = []
    sobra = totp.consume(digitado, guardados)
    if sobra is None:
        return False
    with conn:
        gasto = conn.execute(
            "UPDATE users SET totp_recovery = ? WHERE id = ? AND totp_recovery = ?",
            (json.dumps(sobra), row["id"], row["totp_recovery"]),
        ).rowcount
    return gasto == 1


@app.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    pendente = session.get("pre2fa") or {}
    row = None
    if pendente and pendente.get("ate", 0) > time.time():
        row = db().execute("SELECT * FROM users WHERE id = ?", (pendente.get("uid"),)).fetchone()
    if row is None or not row["totp_enabled"]:
        session.clear()
        flash("A verificacao expirou. Entre de novo.", "error")
        return redirect(url_for("login"))
    if request.method == "POST":
        chave = f"2fa|{row['username'].lower()}"
        restante = _lockout_remaining(chave, LOCKOUT_2FA_TENTATIVAS, LOCKOUT_2FA_JANELA)
        if restante:
            flash(f"Muitas tentativas. Tente de novo em {restante}s.", "error")
            return render_template("login_2fa.html"), 429
        if _confere_segundo_fator(row, request.form.get("codigo", "")):
            _clear_fails(chave)
            return _abre_sessao(row, pendente.get("proximo", ""))
        _record_fail(chave)
        flash("Codigo invalido ou ja usado.", "error")
        return render_template("login_2fa.html"), 401
    return render_template("login_2fa.html")


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


@app.get("/api/recursos")
@login_required
def api_metrics():
    """Medidores de todos os servidores — alimenta os mini-graficos do painel.

    O caminho e "/api/recursos", e nao "/api/metrics", de proposito: "/api/metrics" e
    uma regra corriqueira das listas de filtro de rastreadores (uBlock Origin, AdGuard,
    DNS filtrado). Com uma delas ligada, o navegador nem chega a mandar o pedido — ele
    devolve um pixel transparente com status 499 — e o painel ficava eternamente em
    "medindo recursos...", sem erro visivel em lugar nenhum. Nome em portugues tambem
    e o que o resto das rotas do painel usa (/historico, /alertas, /graficos)."""
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


def _aba_porta(server: Servidor) -> dict:
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


def _aba_http(server: Servidor, http: dict, testar: bool) -> dict:
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


def _aba_log(server: Servidor, join_re: str, leave_re: str, log_path: str,
             testar: bool) -> dict:
    """Aba 3: linhas do log com cara de entrada/saida e o teste dos padroes."""
    saida = {"amostras": [], "teste": None, "erro_log": ""}
    try:
        # O caminho vem do FORMULARIO, nao do banco: e o unico jeito de conferir um
        # arquivo novo (o .ADM do DayZ, por exemplo) antes de salvar.
        provisorio = dict(server)
        provisorio["log_path"] = log_path
        linhas = read_log_lines(provisorio)
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


@app.route("/servers/<int:sid>/players/descobrir", methods=["GET", "POST"])
@admin_required
def players_setup(sid: int):
    """Assistente: acha a porta/API que responde e ajuda a achar o padrao no log."""
    server = _server_or_404(sid)
    # Os campos das tres abas precisam sobreviver ao botao "Testar", e entre eles esta a
    # senha de admin do jogo (http_auth, http_login_body). Por isso o formulario e POST:
    # na URL a senha ficaria no historico do navegador, no cabecalho Referer e no log de
    # qualquer proxy na frente do painel. O GET continua servindo a navegacao entre abas,
    # que so carrega o nome da aba.
    origem = request.form if request.method == "POST" else request.args
    aba = origem.get("aba", "porta")
    testar = bool(origem.get("testar"))

    http = {campo: origem.get(campo, server[campo]) for campo in HTTP_FIELDS}
    join_re = origem.get("join_re", server["join_re"])
    leave_re = origem.get("leave_re", server["leave_re"])
    log_path = origem.get("log_path", server["log_path"])

    dados = {"portas": [], "aviso": "", "achados": [], "mudas": [], "amostras": [],
             "tem_api": False, "udp_do_jogo": 0, "udp_mudas": False,
             "teste": None, "teste_http": None, "erro_log": "", "erro_http": ""}
    if aba == "http":
        dados.update(_aba_http(server, http, testar))
    elif aba == "log":
        dados.update(_aba_log(server, join_re, leave_re, log_path, testar))
    else:
        dados.update(_aba_porta(server))

    return render_template(
        "players_setup.html", server=server, aba=aba,
        http=http, join_re=join_re, leave_re=leave_re, log_path=log_path, **dados,
    )


def _liga_contagem_a2s(conn, sid: int):
    """Consulta UDP direta (A2S). Devolve um redirect quando o formulario esta errado."""
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
    return None


def _liga_contagem_http(conn, sid: int):
    """API HTTP do proprio jogo."""
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
    return None


def _liga_contagem_log(conn, sid: int):
    """Ultimo recurso: as linhas de entrada e saida no log do servidor."""
    errors: list[str] = []
    entrada = _padrao(request.form.get("join_re"), "entrada", errors)
    saida = _padrao(request.form.get("leave_re"), "saida", errors)
    caminho = _caminho_log(request.form.get("log_path"), errors)
    if errors or not entrada:
        flash(errors[0] if errors else "Informe o padrao da linha de entrada.", "error")
        return redirect(url_for("players_setup", sid=sid, aba="log"))
    with conn:
        conn.execute(
            "UPDATE servers SET join_re = ?, leave_re = ?, log_path = ?,"
            " player_source = 'log' WHERE id = ?",
            (entrada, saida, caminho, sid),
        )
    flash("Contagem de jogadores ligada pelo log do servidor.", "ok")
    return None


# Fonte de contagem -> quem grava a escolha. Uma fonte nova (RCON, por exemplo) e uma
# funcao e uma linha aqui; a rota abaixo nao muda.
FONTES_DE_CONTAGEM = {
    "a2s": _liga_contagem_a2s,
    "http": _liga_contagem_http,
    "log": _liga_contagem_log,
}


@app.post("/servers/<int:sid>/players/usar")
@admin_required
def players_use(sid: int):
    """Grava a forma de contagem escolhida no assistente."""
    _server_or_404(sid)  # so pelo 404: daqui para baixo os UPDATE usam o proprio sid
    liga = FONTES_DE_CONTAGEM.get(request.form.get("player_source", ""))
    if liga is None:
        flash("Escolha invalida.", "error")
        return redirect(url_for("players_setup", sid=sid))

    recusa = liga(db(), sid)
    if recusa is not None:
        return recusa

    invalidate_players(sid)
    return redirect(url_for("server_detail", sid=sid))


@app.post("/servers/<int:sid>/players/acao")
@login_required
def player_action(sid: int):
    """Expulsa, bane ou avisa, pela API do proprio jogo.

    E operacao, nao administracao: moderar quem esta jogando nao da acesso ao container,
    entao o operador pode — do mesmo jeito que ele ja reinicia o servidor.
    """
    server = _server_or_404(sid)
    acao = (request.form.get("acao", "") or "").strip()
    jogador = (request.form.get("jogador", "") or "").strip()[:200]
    nome = (request.form.get("nome", "") or "").strip()[:100]
    mensagem = (request.form.get("mensagem", "") or "").strip()[:PLAYER_MSG_MAX]
    quem = nome or jogador or "todos"
    registro = f"{PLAYER_ACTION_LABELS.get(acao, acao)}: {quem}"
    if mensagem:
        registro += f" ({mensagem})"
    voltar = url_for("server_detail", sid=sid)

    try:
        rotulo = acao_de_jogador(server, acao, jogador, mensagem)
    except (QueryError, RemoteError) as exc:
        log_job("player-action", server, session.get("username", "?"),
                command=registro, output=str(exc), status="error")
        flash(f"Nao consegui: {exc}", "error")
        return redirect(voltar)

    log_job("player-action", server, session.get("username", "?"),
            command=registro, output="a API aceitou o pedido")
    # A contagem fica alguns segundos em cache e ainda tem quem acabou de sair.
    invalidate_players(sid)
    flash(f"{rotulo}: {quem}." if acao != "announce" else f"Aviso enviado: {mensagem}", "ok")
    return redirect(voltar)


@app.get("/api/servers/<int:sid>/recursos")
@login_required
def api_server_metrics(sid: int):
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    data = server_metrics(server)
    return jsonify(data), (502 if data.get("error") else 200)


# Validacao do formulario em gamepanel.services.server_service. Os limites ficam aqui
# (sao configuracao do painel) e viajam num bundle; `clean_path` vai junto porque ja
# carrega as raizes permitidas (GAMEPANEL_FILE_ROOTS).
UNIT_RE = server_service.UNIT_RE
HOST_RE = server_service.HOST_RE
USER_RE = server_service.USER_RE
CAMINHO_JSON_RE = server_service.CAMINHO_JSON_RE


def _limites_do_formulario() -> server_service.FormLimits:
    return server_service.FormLimits(
        config_files_max=CONFIG_FILES_MAX, backup_paths_max=BACKUP_PATHS_MAX,
        http_url_max=HTTP_URL_MAX, http_body_max=HTTP_BODY_MAX,
        http_path_max=HTTP_PATH_MAX, re_max_len=RE_MAX_LEN,
        player_sources=PLAYER_SOURCES,
    )


def _form_server(form) -> tuple[dict, list[str]]:
    return server_service.form_server(form, clean_path, _limites_do_formulario())


# Os tres tambem sao usados pelo assistente de contagem (abas HTTP e log), fora do
# formulario de cadastro.
_caminho_log = server_service._caminho_log


def _padrao(valor: str | None, rotulo: str, errors: list[str]) -> str:
    return server_service._padrao(valor, rotulo, RE_MAX_LEN, errors)


def _campos_http(form, errors: list[str]) -> dict:
    return server_service._campos_http(form, _limites_do_formulario(), errors)


# Colunas que o formulario preenche, na mesma ordem do INSERT/UPDATE abaixo. Manter a
# lista em um lugar so evita o classico "acrescentei a coluna e esqueci de um dos SQLs".
SERVER_FIELDS = (
    "name", "host", "ssh_port", "ssh_user", "service", "game_port", "notes",
    "config_path", "config_files", "backup_paths", "query_port", "player_source",
    "join_re", "leave_re", "log_path", "error_re",
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
    data: dict = dict.fromkeys(SERVER_FIELDS, "")
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
                invalidate_players(sid)
                flash("Servidor atualizado.", "ok")
                return redirect(url_for("server_detail", sid=sid))
            except sqlite3.IntegrityError:
                errors.append(f"Ja existe um servidor cadastrado em {data['host']}.")
        for err in errors:
            flash(err, "error")
    # `server` (a linha do banco, nao o formulario) vai junto: e dele que a barra de
    # navegacao do servidor tira o id e o nome. Sem isso esta tela seria a unica do
    # servidor sem a barra — e era exatamente assim que a navegacao ia divergindo.
    return render_template("server_form.html", data=data, mode="edit", sid=sid,
                           server=server)


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
    jobs = jobs_do_servidor(conn, sid, 15)
    lines = _log_lines_arg(request.args.get("lines"))

    # Status, medidores, jogadores e log sao quatro idas de SSH independentes. Em serie a
    # tela custava a soma das quatro — e com o container fora do ar, a soma dos quatro
    # timeouts antes de mostrar "inacessivel".
    lido = em_paralelo({
        "status": lambda: server_status(server),
        "metrics": lambda: server_metrics(server),
        "players": lambda: server_players(server),
        "logs": lambda: read_logs(server, lines),
    })
    # read_logs devolve (texto, cursor) — o par inteiro vem no lugar do "valor".
    par_log, log_error = lido["logs"]
    logs, log_cursor = par_log if par_log else ("", "")

    return render_template(
        "server_detail.html",
        server=server,
        status=lido["status"][0] or {"reachable": False, "service": "desconhecido",
                                     "error": lido["status"][1]},
        metrics=lido["metrics"][0] or {"error": lido["metrics"][1]},
        # Mesma forma que o server_players devolve, para a tela nao precisar saber que
        # houve erro na leitura em vez de erro na contagem.
        players=lido["players"][0] or {"configured": True, "error": lido["players"][1],
                                       "players": None, "list": [], "source": ""},
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


def _log_lines_arg(raw: str | None, default: int = 80) -> int:
    try:
        return max(10, min(500, int(raw or "")))
    except (TypeError, ValueError):
        return default


def read_logs(server: Servidor, lines: int, cursor: str = "") -> tuple[str, str]:
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

TermSession = term_runtime.TermSession


def _open_term(server: dict, uid: int, username: str, cols: int, rows: int) -> TermSession:
    return term_runtime.TermSession(
        ssh_argv, server, uid, username, cols, rows,
        known_hosts=KNOWN_HOSTS, buffer_bytes=TERM_BUFFER_BYTES,
    )


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
        term = _open_term(dict(server), session["uid"], session.get("username", "?"), cols, rows)
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
    data, new_offset, lost = term.read(offset, TERM_POLL_WAIT)
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


def clean_path(raw: str) -> str:
    return files_rt.clean_path(raw, FILE_ROOTS)


def parent_of(path: str) -> str:
    return files_rt.parent_of(path)


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


def _files_guard():
    if not ALLOW_FILES:
        abort(403, "O editor de arquivos esta desabilitado (GAMEPANEL_ALLOW_FILES=0).")


def _server_or_404(sid: int) -> sqlite3.Row:
    server = db().execute(SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    return server


def list_dir(server: Servidor, path: str) -> tuple[list[dict], bool]:
    return files_rt.list_dir(ssh_run, server, path, FILE_LIST_MAX)


def stat_file(server: Servidor, path: str) -> dict:
    return files_rt.stat_file(ssh_run, server, path)


def read_file(server: Servidor, path: str) -> dict:
    return files_rt.read_file(ssh_run, server, path, FILE_MAX_BYTES, FILE_PREVIEW_BYTES)


RESTORE_SCRIPT = backups_rt.RESTORE_SCRIPT

# $1 = destino final. O conteudo vem CRU pela entrada padrao (sem base64: o arquivo pode
# ter gigabytes, e codificar inflaria 33% a toa).
UPLOAD_SCRIPT = files_rt.UPLOAD_SCRIPT


def ssh_stream_in(server, remote_cmd: str, origem, timeout: int) -> str:
    return files_rt.ssh_stream_in(ssh_argv, server, remote_cmd, origem, timeout, UPLOAD_CHUNK)


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
    )


def find_config_files(server: Servidor, root: str) -> list[dict]:
    return files_rt.find_config_files(ssh_run, server, root, CONFIG_GLOBS)


def write_file(server: Servidor, path: str, data: bytes) -> str:
    return files_rt.write_file(ssh_run, server, path, data)


def delete_file(server: Servidor, path: str) -> str:
    return files_rt.delete_file(ssh_run, server, path)


@app.get("/servers/<int:sid>/files/search")
@admin_required
def files_search(sid: int):
    """Procurar arquivos de configuracao — agora numa tela so.

    Isto era uma SEGUNDA implementacao da mesma coisa: `find_config_files` numa lista
    dentro de Arquivos, e a mesma `find_config_files` na mesma lista dentro de
    Configuracao. Duas telas, dois botoes chamados "Procurar", um resultado que so
    valia num dos dois lugares (so a tela de Configuracao sabe fixar o arquivo
    encontrado).

    A busca ficou onde ela serve para alguma coisa. Esta rota continua existindo para
    nao quebrar link antigo nem historico de navegador.
    """
    _server_or_404(sid)
    # `pasta` so entra na URL quando existe: `pasta=` vazio faria a busca procurar na
    # raiz do container em vez da pasta de config do cadastro.
    extras: dict[str, Any] = {"pasta": request.args["path"]} if request.args.get("path") else {}
    return redirect(url_for("config_quick", sid=sid, descobrir=1, **extras))


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


def stream_remote_file(server: Servidor, path: str):
    return files_rt.stream_remote_file(ssh_argv, server, path, DOWNLOAD_CHUNK)


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


# ------------------------------------------------------------------ upload


@app.post("/servers/<int:sid>/files/upload")
@admin_required
def files_upload(sid: int):
    """Manda um arquivo do computador para dentro do container (mod, save, config)."""
    _files_guard()
    server = _server_or_404(sid)
    # O teto deste request ja foi levantado no _teto_do_corpo (BIG_BODY_ENDPOINTS).
    destino_dir = request.form.get("path", "") or FILE_DEFAULT_PATH
    voltar = url_for("files", sid=sid, path=destino_dir)
    enviado = request.files.get("arquivo")
    if not enviado or not enviado.filename:
        flash("Escolha um arquivo para enviar.", "error")
        return redirect(voltar)

    # O navegador manda o nome como o disco de origem o tinha: fica so a ultima parte,
    # para "../../etc/passwd" nao virar caminho.
    nome = enviado.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not nome or nome in (".", ".."):
        flash("Nome de arquivo invalido.", "error")
        return redirect(voltar)

    try:
        pasta = clean_path(destino_dir)
        alvo = clean_path(f"{pasta.rstrip('/')}/{nome}")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(voltar)

    try:
        saida = ssh_stream_in(
            server, q("bash", "-lc", UPLOAD_SCRIPT, "gp", alvo),
            enviado.stream, timeout=JOB_TIMEOUT,
        )
    except RemoteError as exc:
        log_job("upload-file", server, session.get("username", "?"),
                command=alvo, output=str(exc), status="error")
        flash(f"Nao consegui enviar: {exc}", "error")
        return redirect(voltar)

    log_job("upload-file", server, session.get("username", "?"), command=alvo, output=saida)
    flash(f"{saida}. Se o arquivo ja existia, uma copia .bak ficou ao lado.", "ok")
    return redirect(url_for("files", sid=sid, path=pasta))


# ------------------------------------------------------------------ backup
#
# O backup mora DENTRO do container do jogo, nao no painel: e um tar.gz das pastas que
# valem a pena guardar (o save, e a configuracao junto). O painel dispara, lista, baixa e
# restaura — e a restauracao para o servidor, extrai e religa, porque o jogo com o mundo
# trocado embaixo dele grava por cima do que acabou de voltar.


def backup_paths(server: Servidor) -> list[str]:
    return backups_rt.backup_paths(server, BACKUP_PATHS_MAX)


def backup_prefix(server: Servidor) -> str:
    return backups_rt.backup_prefix(server)


def _backup_ou_400(nome: str) -> str:
    """Confere o nome que voltou da tela antes de ele entrar num comando remoto."""
    try:
        return backups_rt.validate_backup_name(nome)
    except ValueError as exc:
        abort(400, str(exc))


def list_backups(server: Servidor) -> list[dict]:
    return backups_rt.list_backups(ssh_run, server, BACKUP_DIR, BACKUP_LIST_MAX)


@app.get("/servers/<int:sid>/backups")
@login_required
def backups(sid: int):
    server = _server_or_404(sid)
    caminhos = backup_paths(server)
    copias, erro = [], ""
    try:
        copias = list_backups(server)
    except RemoteError as exc:
        erro = str(exc)
    return render_template(
        "backups.html", server=server, copias=copias, erro=erro, caminhos=caminhos,
        backup_dir=BACKUP_DIR, manter=BACKUP_KEEP,
    )


def comando_de_backup(server: Servidor, caminhos: list[str], sufixo: str = "") -> str:
    return backups_rt.comando_de_backup(server, BACKUP_DIR, BACKUP_KEEP, caminhos, sufixo)


def delete_backup(server: Servidor, nome: str) -> str:
    return backups_rt.delete_backup(ssh_run, server, BACKUP_DIR, nome)


@app.post("/servers/<int:sid>/backups/criar")
@login_required
def backup_create(sid: int):
    """Dispara o backup. E operacao, nao administracao: o operador pode tirar copia."""
    server = _server_or_404(sid)
    caminhos = backup_paths(server)
    if not caminhos:
        flash("Este servidor nao tem o que guardar: preencha a pasta de configuracao"
              " ou os caminhos de backup no cadastro.", "error")
        return redirect(url_for("backups", sid=sid))
    job_id = start_job(
        "backup", server, session.get("username", "?"),
        remote_cmd=comando_de_backup(server, caminhos),
        command=", ".join(caminhos),
        timeout=BACKUP_TIMEOUT,
    )
    return redirect(url_for("job_detail", jid=job_id))


@app.post("/servers/<int:sid>/backups/restaurar")
@admin_required
def backup_restore(sid: int):
    """Volta o servidor para uma copia. Para o jogo, extrai e religa."""
    server = _server_or_404(sid)
    nome = _backup_ou_400(request.form.get("nome", ""))
    caminhos = backup_paths(server)

    # Copia de seguranca ANTES de extrair: restaurar e a operacao mais destrutiva do
    # painel, e sem isto quem escolhe o backup errado nao tem para onde voltar. Os dois
    # comandos vao num job so — se o backup falhar, o '&&' impede a restauracao.
    passos = []
    if caminhos:
        passos.append(comando_de_backup(server, caminhos, "-antes-de-restaurar"))
    passos.append(q("bash", "-lc", RESTORE_SCRIPT, "gp", BACKUP_DIR, nome, server["service"]))

    job_id = start_job(
        "restore-backup", server, session.get("username", "?"),
        remote_cmd=" && ".join(passos),
        command=nome,
        timeout=BACKUP_TIMEOUT,
    )
    invalidate_status(sid)
    return redirect(url_for("job_detail", jid=job_id))


@app.post("/servers/<int:sid>/backups/remover")
@admin_required
def backup_delete(sid: int):
    server = _server_or_404(sid)
    nome = _backup_ou_400(request.form.get("nome", ""))
    try:
        saida = delete_backup(server, nome)
    except RemoteError as exc:
        log_job("delete-backup", server, session.get("username", "?"),
                command=nome, output=str(exc), status="error")
        flash(f"Nao consegui apagar: {exc}", "error")
        return redirect(url_for("backups", sid=sid))
    log_job("delete-backup", server, session.get("username", "?"), command=nome, output=saida)
    flash(saida, "ok")
    return redirect(url_for("backups", sid=sid))


@app.get("/servers/<int:sid>/backups/baixar")
@admin_required
def backup_download(sid: int):
    """Tira a copia do container. Mesmo streaming do download de arquivo."""
    server = _server_or_404(sid)
    nome = _backup_ou_400(request.args.get("nome", ""))
    caminho = f"{BACKUP_DIR.rstrip('/')}/{nome}"
    try:
        info = stat_file(server, caminho)
    except RemoteError as exc:
        abort(400, str(exc))

    log_job("download-file", server, session.get("username", "?"),
            command=caminho, output=f"{info['size']} bytes")
    return app.response_class(
        stream_with_context(stream_remote_file(server, caminho)),
        mimetype="application/gzip",
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


def config_paths(server: Servidor) -> list[str]:
    """Arquivos de configuracao registrados no cadastro do servidor."""
    return [linha.strip() for linha in (server["config_files"] or "").splitlines() if linha.strip()]


def load_config_doc(server: Servidor, path: str) -> tuple[gameconf.ConfigFile, dict]:
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


def _config_alvo(arquivos: list[str], errors: list[str]) -> str:
    """Qual arquivo a tela Config abre: o pedido na URL, ou o primeiro registrado."""
    pedido = (request.args.get("file") or "").strip()
    if not pedido:
        return arquivos[0] if arquivos else ""
    try:
        alvo = clean_path(pedido)
    except ValueError as exc:
        errors.append(str(exc))
        return arquivos[0] if arquivos else ""
    # O caminho vem da URL: sem esta trava a tela Config seria um leitor de arquivo
    # qualquer do container (como root), justo o que o operador nao tem permissao de
    # abrir. Para ele valem so os arquivos que um admin ja registrou no servidor.
    if alvo not in arquivos and not is_admin():
        abort(403, "Operador so abre os arquivos de configuracao ja registrados neste servidor.")
    return alvo


def _config_sugestoes(server: Servidor, arquivos: list[str], alvo: str,
                      errors: list[str]) -> list | None:
    """Candidatos a arquivo de configuracao no container; None = nem vale procurar.

    Sem nenhum arquivo registrado a tela ja chega com a lista pronta: e o caminho de
    "informar qual e o arquivo" sem sair navegando por pastas. Procurar e listar pasta
    do container, entao so admin faz.
    """
    if not is_admin():
        return None
    if request.args.get("descobrir") != "1" and (arquivos or alvo):
        return None
    # `pasta` deixa procurar noutro lugar que nao a pasta de config do cadastro. E o
    # que a tela de Arquivos oferecia com um botao proprio; agora e um parametro
    # desta busca, que e a unica que existe.
    padrao = server["config_path"] or FILE_DEFAULT_PATH
    try:
        raiz = clean_path(request.args.get("pasta", "") or padrao)
    except ValueError as exc:
        errors.append(str(exc))
        raiz = padrao
    try:
        return find_config_files(server, raiz)
    except RemoteError as exc:
        errors.append(str(exc))
        return []


@app.get("/servers/<int:sid>/config")
@login_required
def config_quick(sid: int):
    _files_guard()
    server = _server_or_404(sid)
    arquivos = config_paths(server)
    errors: list[str] = []
    alvo = _config_alvo(arquivos, errors)

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

    sugestoes = _config_sugestoes(server, arquivos, alvo, errors)

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
        edit = _edit_da_linha(form, i, nome_arquivo, erros)
        if edit is not None:
            edits.append(edit)
    return edits, erros


def _edit_da_linha(form, i: int, nome_arquivo: str, erros: list[str]) -> gameconf.Edit | None:
    """Uma linha do formulario vira uma alteracao — ou nada.

    Nada acontece em tres casos: linha de "adicionar configuracao" deixada em branco,
    campo que ninguem tocou (comparado com o `orig.N` escondido) e valor que o catalogo
    recusou. Os tres estao aqui juntos porque sao a mesma pergunta: "esta linha tem algo
    para gravar?".
    """
    chave = (form.get(f"key.{i}", "") or "").strip()
    if not chave:
        return None

    valor = (form.get(f"val.{i}", "") or "").replace("\r", "")
    ident = urllib.parse.unquote((form.get(f"id.{i}", "") or "").strip())
    if ident and valor == (form.get(f"orig.{i}", "") or "").replace("\r", ""):
        return None  # campo intocado: nao reescreve a linha

    spec = gamefields.describe(nome_arquivo, chave) if nome_arquivo else None
    if spec:
        problema = spec.validate(valor)
        if problema:
            erros.append(f"{spec.label or chave}: {problema}")
            return None
        valor = spec.from_display(valor)

    return gameconf.Edit(
        id=ident,
        section=urllib.parse.unquote(form.get(f"sec.{i}", "") or ""),
        key=chave,
        value=valor,
    )


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
    job_ou_403(job)
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
    job_ou_403(job)
    return jsonify(
        {
            "status": job["status"],
            "exit_code": job["exit_code"],
            "output": job["output"],
            "finished_at": job["finished_at"],
        }
    )


# ------------------------------------------------------------------- broker
#
# Criar instancia de jogo e abrir porta no firewall. Quem tem as credenciais de Proxmox e
# OPNsense e o broker (broker/); aqui o painel so PEDE, acompanha e cadastra o resultado.

# Formulario de jogo novo em gamepanel.services.broker_service; acompanhamento da
# operacao em gamepanel.tasks.broker_jobs.
BROKER_RECEITAS = broker_service.BROKER_RECEITAS


def broker_required(view):
    """Rota que so existe quando o deploy ligou o broker. Empilha DEPOIS de
    `admin_required`: o operador leva o 403 de administrador, e so o admin descobre que o
    recurso esta desligado.

    Exige tambem o segundo fator DA PESSOA, sempre — independente de `GAMEPANEL_REQUIRE_2FA`
    (que e sobre o painel inteiro). O broker cria e apaga container no Proxmox e abre porta
    no OPNsense; se a sessao de um admin for roubada (XSS, proxy malicioso, celular
    destravado), o 2FA e a unica coisa que ainda separa "ver a tela" de "destruir
    infraestrutura". Sem ele o pedido nem chega a `broker_client`."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not ALLOW_BROKER:
            abort(403, "O broker esta desligado neste painel (GAMEPANEL_ALLOW_BROKER=0).")
        usuario = usuario_logado()
        if not usuario or not usuario["totp_enabled"]:
            if request.path.startswith("/api/"):
                return jsonify({"error": "ative a verificacao em duas etapas em Conta para "
                                         "usar o broker"}), 403
            flash("O broker so pode ser usado por quem tem a verificacao em duas etapas "
                  "ativa: ative-a em Conta.", "error")
            return redirect(url_for("account_2fa"))
        return view(*args, **kwargs)

    return wrapper


def _dispara(tarefa) -> None:
    """Roda `tarefa` numa thread. Existe para os testes trocarem por uma execucao direta."""
    threading.Thread(target=tarefa, daemon=True).start()


def _atualiza_job(job_id: int, **campos) -> None:
    # Conexao propria: quem chama esta vivo numa thread fora do contexto do request. Os
    # NOMES das colunas vem dos chamadores (fixos); so os valores viajam como parametro.
    conn = _connect()
    try:
        with conn:
            conn.execute(
                f"UPDATE jobs SET {', '.join(c + '=?' for c in campos)} WHERE id=?",
                (*campos.values(), job_id),
            )
    finally:
        conn.close()


def _fecha_job(job_id: int, status: str, saida: str, codigo: int | None = None,
               server_id: int | None = None) -> None:
    campos: dict = {"status": status, "exit_code": codigo, "output": saida.strip()[-200000:],
                    "finished_at": now_iso()}
    if server_id is not None:
        campos["server_id"] = server_id
    _atualiza_job(job_id, **campos)


def _broker_job_deps() -> broker_jobs.BrokerJobDeps:
    """Montado na chamada: `BROKER_POLL` e `BROKER_FALHAS_MAX` sao trocados pelos testes
    antes de acompanhar a operacao, e um bundle congelado no import nao veria a troca."""
    return broker_jobs.BrokerJobDeps(
        atualiza_job=_atualiza_job, fecha_job=_fecha_job, ensure_server=ensure_server,
        servidor_do_deploy=ServidorDoDeploy, connect=_connect, poll=BROKER_POLL,
        falhas_max=BROKER_FALHAS_MAX, timeout=JOB_TIMEOUT,
    )


def _cadastra_servidor_do_broker(r: dict) -> int:
    return broker_jobs.cadastra_servidor(_broker_job_deps(), r)


def acompanha_operacao(job_id: int, op_id: str, dormir=time.sleep) -> None:
    broker_jobs.acompanha_operacao(_broker_job_deps(), job_id, op_id, dormir)


def start_broker_job(action: str, username: str, op_id: str, comando: str) -> int:
    conn = db()
    with conn:
        cur = conn.execute(
            "INSERT INTO jobs (server_id, target, action, status, command, username,"
            " created_at, broker_op) VALUES (NULL, 'broker', ?, 'running', ?, ?, ?, ?)",
            (action, comando, username, now_iso(), op_id),
        )
    job_id = _id_inserido(cur)
    _dispara(lambda: acompanha_operacao(job_id, op_id))
    return job_id


def retoma_jobs_do_broker() -> int:
    """Depois de um restart do painel, volta a acompanhar as operacoes que ainda estavam
    rodando no broker. Sem isto o job ficaria 'running' para sempre, e o servidor recem
    criado nunca seria cadastrado."""
    if not ALLOW_BROKER:
        return 0
    conn = _connect()
    try:
        pendentes = conn.execute(
            "SELECT id, broker_op FROM jobs WHERE status = 'running' AND broker_op != ''"
        ).fetchall()
    finally:
        conn.close()
    for job in pendentes:
        _dispara(lambda jid=job["id"], op=job["broker_op"]: acompanha_operacao(jid, op))
    return len(pendentes)


def _registra_acao_do_broker(action: str, username: str, comando: str, saida: str,
                             status: str = "ok") -> int:
    """Deixa no historico uma acao curta do broker (desativar, remover, jogo novo)."""
    conn = db()
    with conn:
        cur = conn.execute(
            "INSERT INTO jobs (server_id, target, action, status, exit_code, output, command,"
            " username, created_at, finished_at) VALUES (NULL, 'broker', ?, ?, ?, ?, ?, ?, ?, ?)",
            (action, status, 0 if status == "ok" else 1, saida[-200000:], comando,
             username, now_iso(), now_iso()),
        )
    return _id_inserido(cur)


def _ator() -> str:
    return session.get("username", "")


_jogo_do_form = broker_service.jogo_do_form


@app.route("/catalogo", methods=["GET"])
@admin_required
@broker_required
def catalog():
    try:
        jogos = broker_client.catalogo()
    except broker_client.BrokerError as erro:
        flash(f"Broker: {erro.mensagem}", "error")
        jogos = []
    return render_template("catalogo.html", jogos=jogos, receitas=BROKER_RECEITAS, form={},
                           modelos=MODELOS_DE_JOGO)


@app.get("/api/catalogo/sugestoes")
@admin_required
@broker_required
def api_catalog_suggestions():
    """Busca por nome ou App ID numa lista FIXA (gerada do LinuxGSM, no repositorio): nada aqui
    vai a internet, e a consulta so seleciona entre entradas conhecidas."""
    achados = busca_de_jogos.buscar(request.args.get("q", ""))
    return jsonify({"resultados": [busca_de_jogos.resultado(s) for s in achados],
                    "fonte": busca_de_jogos.FONTE})


@app.post("/catalogo/novo")
@admin_required
@broker_required
def catalog_new():
    dados, erros = _jogo_do_form(request.form)
    if not erros:
        try:
            broker_client.adicionar_jogo(dados, _ator())
        except broker_client.BrokerError as erro:
            erros.append(f"Broker: {erro.mensagem}")
    if erros:
        for erro in erros:
            flash(erro, "error")
        try:
            jogos = broker_client.catalogo()
        except broker_client.BrokerError:
            jogos = []
        return render_template("catalogo.html", jogos=jogos, receitas=BROKER_RECEITAS,
                               form=request.form, modelos=MODELOS_DE_JOGO), 400
    _registra_acao_do_broker("broker-jogo", _ator(), dados.get("chave", ""), "Jogo adicionado ao catalogo.")
    flash(f"Jogo {dados.get('nome', dados.get('chave', ''))} adicionado ao catalogo.", "ok")
    return redirect(url_for("catalog"))


@app.get("/instancias")
@admin_required
@broker_required
def instances_list():
    try:
        instancias = broker_client.instancias()
        jogos = [j for j in broker_client.catalogo() if j.get("criavel")]
    except broker_client.BrokerError as erro:
        flash(f"Broker: {erro.mensagem}", "error")
        instancias, jogos = [], []
    ligados = {
        r["broker_id"]: r
        for r in db().execute("SELECT id, name, broker_id FROM servers WHERE broker_id > 0")
    }
    return render_template("instancias.html", instancias=instancias, jogos=jogos, servidores=ligados)


@app.post("/instancias/nova")
@admin_required
@broker_required
def instance_new():
    jogo = (request.form.get("jogo") or "").strip()
    nome = (request.form.get("nome") or "").strip()
    try:
        resposta = broker_client.criar(jogo, nome, _ator())
    except broker_client.BrokerError as erro:
        flash(f"Broker: {erro.mensagem}", "error")
        return redirect(url_for("instances_list"))
    op_id = str(resposta.get("operacao_id", ""))
    if not op_id:
        flash("Broker: resposta sem identificador de operacao.", "error")
        return redirect(url_for("instances_list"))
    job_id = start_broker_job("broker-criar", _ator(), op_id, f"{jogo}: {nome}")
    return redirect(url_for("job_detail", jid=job_id))


@app.post("/instancias/<int:iid>/desativar")
@admin_required
@broker_required
def instance_deactivate(iid: int):
    try:
        broker_client.desativar(iid, _ator())
    except broker_client.BrokerError as erro:
        _registra_acao_do_broker("broker-desativar", _ator(), f"instancia {iid}", erro.mensagem, "error")
        flash(f"Broker: {erro.mensagem}", "error")
    else:
        _registra_acao_do_broker("broker-desativar", _ator(), f"instancia {iid}",
                                 "Portas fechadas no firewall e container parado.")
        flash("Instancia desativada: portas fechadas e container parado.", "ok")
    return redirect(url_for("instances_list"))


@app.post("/instancias/<int:iid>/remover")
@admin_required
@broker_required
def instance_remove(iid: int):
    confirma = (request.form.get("confirma") or "").strip()
    somente_banco = request.form.get("somente_banco") == "1"
    try:
        broker_client.remover(iid, confirma, _ator(), somente_banco)
    except broker_client.BrokerError as erro:
        _registra_acao_do_broker("broker-remover", _ator(), f"instancia {iid}", erro.mensagem, "error")
        flash(f"Broker: {erro.mensagem}", "error")
        return redirect(url_for("instances_list"))
    conn = db()
    with conn:
        # O servidor do painel aponta para um container que deixou de existir.
        conn.execute("DELETE FROM servers WHERE broker_id = ?", (iid,))
    _registra_acao_do_broker(
        "broker-remover", _ator(), f"instancia {iid}",
        "So o registro foi esquecido." if somente_banco else "Container destruido e servidor removido do painel.")
    flash("Instancia removida.", "ok")
    return redirect(url_for("instances_list"))


# ------------------------------------------------------------- agendamentos


def _inteiro(valor, minimo: int, maximo: int, padrao: int) -> int:
    bruto = (valor or "").strip()
    if bruto.lstrip("-").isdigit() and minimo <= int(bruto) <= maximo:
        return int(bruto)
    return padrao


def _form_agendamento(form, errors: list[str]) -> dict:
    acao = (form.get("action", "") or "").strip()
    if acao not in SCHEDULE_ACTIONS:
        errors.append("Escolha o que a tarefa deve fazer.")
        acao = "restart"
    kind = (form.get("kind", "") or "").strip()
    if kind not in SCHEDULE_KINDS:
        errors.append("Escolha quando a tarefa deve rodar.")
        kind = "diario"

    hora = _inteiro(form.get("hour"), 0, 23, -1)
    minuto = _inteiro(form.get("minute"), 0, 59, -1)
    if kind != "intervalo" and (hora < 0 or minuto < 0):
        errors.append("Horario invalido (use hora 0-23 e minuto 0-59).")
    horas = _inteiro(form.get("every_hours"), 1, EVERY_HOURS_MAX, -1)
    if kind == "intervalo" and horas < 0:
        errors.append(f"Intervalo invalido (de 1 a {EVERY_HOURS_MAX} horas).")

    return {
        "action": acao,
        "kind": kind,
        "hour": max(0, hora),
        "minute": max(0, minuto),
        "weekday": _inteiro(form.get("weekday"), 0, 6, 0),
        "every_hours": max(1, horas),
    }


def _agendamento_ou_404(aid: int) -> sqlite3.Row:
    sched = db().execute("SELECT * FROM schedules WHERE id = ?", (aid,)).fetchone()
    if not sched:
        abort(404)
    return sched


def _proxima_ocorrencia(sched, agora: datetime) -> datetime:
    """Quando esta tarefa roda da proxima vez.

    'intervalo' conta a partir da ultima execucao; diario e semanal somam um passo a
    ocorrencia anterior. `ocorrencia_anterior` so devolve None para 'intervalo', que
    nunca chega na segunda metade - mas a checagem fica explicita, porque a alternativa
    e um `TypeError` numa tela que so quebra para quem tem agendamento cadastrado.
    """
    if sched["kind"] == "intervalo":
        ultimo = _parse_dt(sched["last_run"]) or agora
        return ultimo + timedelta(hours=int(sched["every_hours"]))

    anterior = ocorrencia_anterior(sched, agora) or agora
    return anterior + timedelta(days=7 if sched["kind"] == "semanal" else 1)


@app.get("/servers/<int:sid>/agendamentos")
@login_required
def schedules(sid: int):
    server = _server_or_404(sid)
    conn = db()
    tarefas = conn.execute(
        "SELECT * FROM schedules WHERE server_id = ? ORDER BY id", (sid,)
    ).fetchall()
    agora = agora_local()
    # A tela mostra a proxima vez que cada tarefa roda: sem isso "todo dia as 5h" nao
    # deixa claro se ela ja rodou hoje ou se ainda vai rodar.
    proximas = {}
    for t in tarefas:
        proximas[t["id"]] = _proxima_ocorrencia(t, agora).strftime(FORMATO_DATA_CURTA)
    return render_template(
        "schedules.html", server=server, tarefas=tarefas, proximas=proximas,
        acoes=SCHEDULE_ACTIONS, job_labels=JOB_LABELS, dias=DIAS_SEMANA,
        rotulo=rotulo_agendamento, agora=agora, max_horas=EVERY_HOURS_MAX,
    )


@app.post("/servers/<int:sid>/agendamentos")
@admin_required
def schedule_new(sid: int):
    _server_or_404(sid)
    errors: list[str] = []
    dados = _form_agendamento(request.form, errors)
    if errors:
        for err in errors:
            flash(err, "error")
        return redirect(url_for("schedules", sid=sid))

    # 'intervalo' comeca a contar de agora: sem isto, "a cada 6h" dispararia no instante
    # em que fosse salvo, o que ninguem espera de um agendamento.
    inicio = agora_local().isoformat() if dados["kind"] == "intervalo" else ""
    conn = db()
    with conn:
        conn.execute(
            "INSERT INTO schedules (server_id, action, kind, hour, minute, weekday,"
            " every_hours, enabled, last_run, created_at) VALUES (?,?,?,?,?,?,?,1,?,?)",
            (sid, dados["action"], dados["kind"], dados["hour"], dados["minute"],
             dados["weekday"], dados["every_hours"], inicio, now_iso()),
        )
    flash(f"{job_label(dados['action'])} agendado.", "ok")
    return redirect(url_for("schedules", sid=sid))


@app.post("/agendamentos/<int:aid>/alternar")
@admin_required
def schedule_toggle(aid: int):
    sched = _agendamento_ou_404(aid)
    conn = db()
    with conn:
        conn.execute("UPDATE schedules SET enabled = ? WHERE id = ?",
                     (0 if sched["enabled"] else 1, aid))
    flash("Tarefa desligada." if sched["enabled"] else "Tarefa ligada.", "ok")
    return redirect(url_for("schedules", sid=sched["server_id"]))


@app.post("/agendamentos/<int:aid>/remover")
@admin_required
def schedule_delete(aid: int):
    sched = _agendamento_ou_404(aid)
    conn = db()
    with conn:
        conn.execute("DELETE FROM schedules WHERE id = ?", (aid,))
    flash("Tarefa removida.", "ok")
    return redirect(url_for("schedules", sid=sched["server_id"]))


@app.post("/agendamentos/<int:aid>/rodar")
@admin_required
def schedule_run(aid: int):
    """Roda a tarefa agora, sem esperar a hora — e como se confere se ela funciona."""
    sched = _agendamento_ou_404(aid)
    job_id = dispara_agendamento(db(), sched)
    if not job_id:
        flash("Nao consegui disparar (servidor sem caminhos de backup?).", "error")
        return redirect(url_for("schedules", sid=sched["server_id"]))
    return redirect(url_for("job_detail", jid=job_id))


# ---------------------------------------------------------- graficos de uso
#
# As amostras viram COORDENADAS aqui, no servidor: a tela recebe um SVG ja pronto e
# continua legivel sem JavaScript. O JS por cima so acrescenta a mira e o balaozinho —
# nenhum valor depende dele (a ponta de cada linha tem rotulo, e ha a tabela embaixo).

# Duas amostras separadas por mais que isto viram um BURACO na linha, nao um traco reto
# atravessando: servidor que passou duas horas fora do ar nao "andou em linha reta".
# Desenho dos graficos em gamepanel.services.chart_service; os nomes seguem aqui porque
# a rota, o template e os testes chamam por eles.
CHART_TICKS = chart_service.CHART_TICKS
CHART_RANGES = chart_service.CHART_RANGES
CHART_CPU = chart_service.CHART_CPU
CHART_MEM = chart_service.CHART_MEM
_teto_limpo = chart_service.teto_limpo


def monta_grafico(amostras, series, teto: float, inicio, fim, formato_tempo: str) -> dict:
    # `SAMPLE_EVERY` entra aqui porque e configuracao do painel: e ele que diz a partir
    # de que buraco entre duas amostras a linha do grafico deve ser cortada.
    return chart_service.monta_grafico(
        amostras, series, teto, inicio, fim, formato_tempo, SAMPLE_EVERY)


@app.get("/servers/<int:sid>/graficos")
@login_required
def charts(sid: int):
    """CPU, memoria e jogadores ao longo do tempo.

    Sao DOIS graficos e nao um: porcentagem e contagem de gente nao cabem no mesmo eixo,
    e forcar as duas escalas num plot so inventa uma relacao que nao existe nos dados.
    """
    server = _server_or_404(sid)
    validas = [h for h, _ in CHART_RANGES]
    try:
        horas = int(request.args.get("h", "24"))
    except ValueError:
        horas = 24
    if horas not in validas:
        horas = 24

    fim = datetime.now(timezone.utc)
    inicio = fim - timedelta(hours=horas)
    linhas = db().execute(
        "SELECT taken_at, cpu_pct, mem_pct, players FROM samples"
        " WHERE server_id = ? AND taken_at >= ? ORDER BY taken_at",
        (sid, inicio.isoformat()),
    ).fetchall()

    amostras = []
    for linha in linhas:
        quando = _parse_dt(linha["taken_at"])
        if quando:
            amostras.append((quando, {"cpu": linha["cpu_pct"], "mem": linha["mem_pct"],
                                      "players": linha["players"]}))

    formato = "%d/%m" if horas > 48 else "%H:%M"
    uso = monta_grafico(
        amostras,
        [{"chave": "cpu", "rotulo": "CPU", "cor": CHART_CPU, "sufixo": "%"},
         {"chave": "mem", "rotulo": "Memoria", "cor": CHART_MEM, "sufixo": "%"}],
        100, inicio, fim, formato,
    )
    pico = max((v["players"] for _, v in amostras if v["players"] is not None), default=0)
    jogadores = monta_grafico(
        amostras,
        [{"chave": "players", "rotulo": "Jogadores", "cor": CHART_CPU}],
        _teto_limpo(pico), inicio, fim, formato,
    )

    # A tabela e o par acessivel do grafico: mesmos numeros, sem depender de cor nem de
    # passar o mouse. Do mais novo para o mais velho, que e como se procura um pico.
    tabela = [
        {"quando": q.astimezone().strftime(FORMATO_DATA_CURTA), **v}
        for q, v in reversed(amostras)
    ][:200]

    return render_template(
        "charts.html", server=server, uso=uso, jogadores=jogadores, tabela=tabela,
        horas=horas, faixas=CHART_RANGES, total=len(amostras), pico=pico,
        a_cada=int(SAMPLE_EVERY / 60), guarda_dias=SAMPLES_KEEP_DAYS,
        cores={"cpu": CHART_CPU, "mem": CHART_MEM},
    )


# --------------------------------------------------------------- historico


@app.get("/historico")
@login_required
def history():
    """Tudo o que aconteceu no painel, de todos os servidores.

    O historico por servidor mostra os ultimos 15; e aqui que se responde "quem mexeu
    nisso" e "o que o agendador andou fazendo".
    """
    conn = db()
    servers = conn.execute(SQL_ALL_SERVERS).fetchall()
    nomes = {int(s["id"]): s["name"] for s in servers}

    filtro_srv = (request.args.get("servidor", "") or "").strip()
    filtro_acao = (request.args.get("acao", "") or "").strip()
    filtro_user = (request.args.get("usuario", "") or "").strip()[:80]
    try:
        pagina = max(0, int(request.args.get("p", "0")))
    except ValueError:
        pagina = 0

    onde, valores = ["1 = 1"], []
    if filtro_srv.isdigit():
        onde.append("server_id = ?")
        valores.append(int(filtro_srv))
    if filtro_acao in JOB_LABELS:
        onde.append("action = ?")
        valores.append(filtro_acao)
    if filtro_user:
        onde.append("username = ?")
        valores.append(filtro_user)

    corte, escondidas = filtro_de_papel()
    sql_onde = " AND ".join(onde) + corte
    valores.extend(escondidas)

    # Pede um a mais que o tamanho da pagina: e como se sabe se existe proxima sem contar
    # a tabela inteira.
    linhas = conn.execute(
        f"SELECT * FROM jobs WHERE {sql_onde} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*valores, HISTORY_PAGE + 1, pagina * HISTORY_PAGE),
    ).fetchall()
    tem_mais = len(linhas) > HISTORY_PAGE
    jobs = linhas[:HISTORY_PAGE]

    usuarios = [r[0] for r in conn.execute(
        f"SELECT DISTINCT username FROM jobs WHERE username <> '' {corte} ORDER BY username",
        escondidas,
    ).fetchall()]

    return render_template(
        "history.html", jobs=jobs, servers=servers, nomes=nomes, usuarios=usuarios,
        acoes=sorted(JOB_LABELS), filtro_srv=filtro_srv, filtro_acao=filtro_acao,
        filtro_user=filtro_user, pagina=pagina, tem_mais=tem_mais,
        manter_dias=JOBS_KEEP_DAYS,
    )


# ------------------------------------------------------------- acesso / conta


@app.get("/ssh-key")
@login_required
def ssh_key():
    return render_template("ssh_key.html", pubkey=public_key())


@app.post("/account/idioma")
@login_required
def account_language():
    """Guarda o idioma da tela para ESTA pessoa.

    Por usuario, e nao por sessao: quem trabalha em ingles nao quer reescolher a cada
    login, e duas pessoas no mesmo painel podem preferir idiomas diferentes.
    """
    escolhido = i18n.idioma_valido(request.form.get("lang"))
    with db() as conn:
        conn.execute("UPDATE users SET lang = ? WHERE id = ?", (escolhido, session["uid"]))
    # O `g` desta requisicao ja guardou o idioma antigo, e o flash abaixo e lido na
    # PROXIMA (depois do redirect) — entao ele ja sai no idioma novo.
    g._idioma = escolhido
    flash(traduzir("account.language.changed"), "ok")
    return redirect(url_for("account"))


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
                conn.execute(SQL_SET_PASSWORD, (hash_password(new), session["uid"]))
            flash("Senha alterada.", "ok")
            return redirect(url_for("dashboard"))
    return render_template("account.html", segundo_fator=_estado_do_2fa(),
                           exige_2fa=REQUIRE_2FA, broker_ligado=ALLOW_BROKER)


def _estado_do_2fa() -> dict:
    row = db().execute(
        "SELECT totp_enabled, totp_recovery FROM users WHERE id = ?", (session["uid"],)
    ).fetchone()
    try:
        restantes = len(json.loads(row["totp_recovery"] or "[]"))
    except ValueError:
        restantes = 0
    return {"ativo": bool(row["totp_enabled"]), "codigos_restantes": restantes}


def _guarda_o_segundo_fator(uid: int, segredo: str, passo: int) -> list[str]:
    """Liga o 2FA e devolve os codigos de recuperacao EM TEXTO, a unica vez em que existem."""
    codigos = totp.new_recovery_codes()
    conn = db()
    with conn:
        conn.execute(
            "UPDATE users SET totp_secret = ?, totp_enabled = 1, totp_last_step = ?,"
            " totp_recovery = ? WHERE id = ?",
            (segredo, passo, json.dumps([totp.hash_recovery_code(c) for c in codigos]), uid),
        )
    return codigos


def _senha_e_codigo_conferem(uid: int) -> tuple[sqlite3.Row | None, str]:
    """Para desligar o 2FA ou pedir codigos novos: a senha E um codigo. Quem esta logado ja
    provou os dois no login, mas uma sessao esquecida aberta nao pode desligar a protecao."""
    row = db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    chave = f"2fa|{row['username'].lower()}"
    if _lockout_remaining(chave, LOCKOUT_2FA_TENTATIVAS, LOCKOUT_2FA_JANELA):
        return None, "Muitas tentativas. Espere alguns minutos."
    if not verify_password(request.form.get("senha", ""), row["password_hash"]):
        _record_fail(chave)
        return None, "Senha incorreta."
    if not _confere_segundo_fator(row, request.form.get("codigo", "")):
        _record_fail(chave)
        return None, "Codigo invalido ou ja usado."
    _clear_fails(chave)
    return row, ""


@app.route("/account/2fa", methods=["GET", "POST"])
@login_required
def account_2fa():
    """Ativar o segundo fator: mostra o segredo, confere UM codigo do aplicativo e so entao liga."""
    if _estado_do_2fa()["ativo"]:
        return redirect(url_for("account"))
    if request.method == "POST":
        segredo = session.get("totp_pendente", "")
        passo = totp.verify(segredo, request.form.get("codigo", ""), time.time()) if segredo else None
        if passo is None:
            flash("Codigo incorreto. Confira o horario do celular e tente de novo.", "error")
        else:
            codigos = _guarda_o_segundo_fator(session["uid"], segredo, passo)
            session.pop("totp_pendente", None)
            flash("Verificacao em duas etapas ativada.", "ok")
            return render_template("account_2fa_codigos.html", codigos=codigos)
    # O segredo fica na SESSAO (cookie assinado) ate ser confirmado; recarregar a pagina mostra
    # o mesmo, e abandonar a tela nao deixa nada meio ligado no banco.
    segredo = session.get("totp_pendente") or totp.new_secret()
    session["totp_pendente"] = segredo
    endereco = totp.uri(segredo, session.get("username", ""), "Painel de Jogos")
    return render_template(
        "account_2fa.html", segredo=totp.group(segredo), endereco=endereco,
        qr_svg=qr.svg(endereco, label="QR code da verificacao em duas etapas"))


@app.post("/account/2fa/desativar")
@login_required
def account_2fa_off():
    if REQUIRE_2FA:
        flash("Este painel exige o segundo fator: nao da para desativar.", "error")
        return redirect(url_for("account"))
    row, erro = _senha_e_codigo_conferem(session["uid"])
    if erro:
        flash(erro, "error")
        return redirect(url_for("account"))
    _apaga_o_segundo_fator(row["id"])
    flash("Verificacao em duas etapas desativada.", "ok")
    return redirect(url_for("account"))


@app.post("/account/2fa/codigos")
@login_required
def account_2fa_codes():
    """Codigos de recuperacao novos: os antigos deixam de valer."""
    row, erro = _senha_e_codigo_conferem(session["uid"])
    if erro:
        flash(erro, "error")
        return redirect(url_for("account"))
    codigos = totp.new_recovery_codes()
    conn = db()
    with conn:
        conn.execute("UPDATE users SET totp_recovery = ? WHERE id = ?",
                     (json.dumps([totp.hash_recovery_code(c) for c in codigos]), row["id"]))
    flash("Codigos novos gerados: os antigos deixaram de valer.", "ok")
    return render_template("account_2fa_codigos.html", codigos=codigos)


def _apaga_o_segundo_fator(uid: int) -> None:
    conn = db()
    with conn:
        conn.execute(
            "UPDATE users SET totp_secret = '', totp_enabled = 0, totp_last_step = 0,"
            " totp_recovery = '' WHERE id = ?", (uid,))


# ------------------------------------------------------------------ alertas


@app.get("/alertas")
@admin_required
def alerts():
    conn = db()
    return render_template(
        "alerts.html", cfg=webhook_config(conn), eventos=ALERT_EVENTS,
        padrao=limpa_eventos(ALERT_DEFAULT), do_env=bool(WEBHOOK_URL_PADRAO),
        monitor=int(MONITOR_EVERY), disco_a_cada=int(DISK_CHECK_EVERY / 60),
        # O piso do relogio conta: o alerta nao pode chegar mais rapido que a volta dele.
        jogadores_a_cada=int(max(PLAYER_CHECK_EVERY, SCHEDULE_TICK)),
        quieto=int(ALERT_QUIET), limite_hooks=WEBHOOK_MAX,
        mudo_voltas=MUTE_ROUNDS, log_a_cada=int(LOG_CHECK_EVERY),
        pendencias=alertas_sem_base(conn), diario=alertas_recentes(conn),
        streams=streams_vivos(),
    )


def alertas_sem_base(conn: sqlite3.Connection) -> dict:
    """Eventos ligados que nao tem em quais servidores olhar.

    Alerta ligado e mudo e pior do que alerta desligado: a pessoa marca 'jogo nao
    responde', nenhum servidor tem consulta configurada, e o silencio do canal passa a
    ser lido como "esta tudo bem".
    """
    ligados = webhook_config(conn)["eventos"]
    if not ligados & set(ALERT_PRECISA_CONFIG):
        return {}
    servidores = conn.execute(SQL_ALL_SERVERS).fetchall()
    com_consulta = sum(1 for s in servidores if player_source(s) in ("a2s", "http"))
    com_jogadores = sum(1 for s in servidores if player_source(s))
    com_regex = sum(1 for s in servidores if _valor_guardado(s, "error_re"))
    faltando = {}
    if ("travou" in ligados or "respondeu" in ligados) and not com_consulta:
        faltando["travou"] = ALERT_PRECISA_CONFIG["travou"]
    if ("jogador-entrou" in ligados or "jogador-saiu" in ligados) and not com_jogadores:
        faltando["jogador-entrou"] = ALERT_PRECISA_CONFIG["jogador-entrou"]
    if "erro-no-log" in ligados and not com_regex:
        faltando["erro-no-log"] = ALERT_PRECISA_CONFIG["erro-no-log"]
    return faltando


# Os limites em porcentagem da tela de Alertas: campo do formulario, chave no banco e
# como o aviso de recusa chama a coisa.
LIMITES_ALERTA = (
    ("disk_pct", "webhook_disk_pct", "disco cheio"),
    ("mem_pct", "webhook_mem_pct", "memoria cheia"),
    ("cpu_pct", "webhook_cpu_pct", "CPU alta"),
)


@app.post("/alertas")
@admin_required
def alerts_save():
    """So o que vale para todos os destinos: hoje, os limites de disco, memoria e CPU."""
    conn = db()
    novos = []
    for campo, chave, nome in LIMITES_ALERTA:
        # Campo que nem veio no formulario fica como esta. Tratar ausencia como erro
        # faria um formulario sem o campo derrubar um limite que ja estava certo.
        if campo not in request.form:
            continue
        valor = (request.form.get(campo, "") or "").strip()
        if not valor.isdigit() or not 50 <= int(valor) <= 100:
            flash(f"O aviso de {nome} vale de 50% a 100%.", "error")
            return redirect(url_for("alerts"))
        novos.append((chave, valor))
    # So grava depois de validar todos: meio salvo e pior que nada salvo, porque a tela
    # volta dizendo "recusado" enquanto um dos limites ja mudou por baixo.
    for chave, valor in novos:
        config_set(conn, chave, valor)
    _zera_linha_de_base()
    flash("Preferencias salvas.", "ok")
    return redirect(url_for("alerts"))


def _zera_linha_de_base() -> None:
    """A memoria do monitor fica velha quando a configuracao muda.

    Zerando, a proxima volta so ANOTA o estado atual em vez de disparar um alerta sobre
    o que ja estava daquele jeito antes da mudanca.
    """
    _estado_monitor.clear()


def _le_form_webhook() -> tuple:
    """Valida o formulario de um destino. Devolve (dados, erro)."""
    nome = (request.form.get("nome", "") or "").strip()[:60]
    url = (request.form.get("url", "") or "").strip()[:400]
    eventos = [e for e in request.form.getlist("eventos") if e in ALERT_EVENTS]
    ativo = 1 if request.form.get("ativo") else 0
    if url and not URL_RE.match(url):
        return None, "URL invalida (comece com http:// ou https://)."
    return {"nome": nome, "url": url, "eventos": ",".join(eventos), "ativo": ativo}, ""


@app.post("/alertas/destinos")
@admin_required
def alerts_hook_new():
    conn = db()
    quantos = conn.execute("SELECT COUNT(*) AS n FROM webhooks").fetchone()["n"]
    if quantos >= WEBHOOK_MAX:
        flash(f"Limite de {WEBHOOK_MAX} destinos atingido.", "error")
        return redirect(url_for("alerts"))
    dados, erro = _le_form_webhook()
    if erro or not dados["url"]:
        flash(erro or "Informe a URL do webhook.", "error")
        return redirect(url_for("alerts"))
    with conn:
        conn.execute(
            "INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
            " VALUES (?, ?, ?, ?, ?)",
            (dados["nome"] or "Destino", dados["url"], dados["eventos"],
             dados["ativo"], now_iso()),
        )
    _zera_linha_de_base()
    flash("Destino adicionado.", "ok")
    return redirect(url_for("alerts"))


@app.post("/alertas/destinos/<int:hid>")
@admin_required
def alerts_hook_save(hid: int):
    conn = db()
    atual = conn.execute("SELECT url FROM webhooks WHERE id = ?", (hid,)).fetchone()
    if not atual:
        flash("Destino nao encontrado.", "error")
        return redirect(url_for("alerts"))
    dados, erro = _le_form_webhook()
    if erro:
        flash(erro, "error")
        return redirect(url_for("alerts"))
    # Campo de URL em branco quer dizer "mantem a que ja esta la". A tela mostra a URL
    # mascarada, entao nao ha o que reenviar: so quem digitar uma nova a troca.
    url = dados["url"] or atual["url"]
    with conn:
        conn.execute(
            "UPDATE webhooks SET nome = ?, url = ?, eventos = ?, ativo = ? WHERE id = ?",
            (dados["nome"] or "Destino", url, dados["eventos"], dados["ativo"], hid),
        )
    _zera_linha_de_base()
    flash("Destino salvo.", "ok")
    return redirect(url_for("alerts"))


@app.post("/alertas/destinos/<int:hid>/remover")
@admin_required
def alerts_hook_del(hid: int):
    conn = db()
    with conn:
        conn.execute("DELETE FROM webhooks WHERE id = ?", (hid,))
    flash("Destino removido.", "ok")
    return redirect(url_for("alerts"))


@app.post("/alertas/destinos/<int:hid>/testar")
@admin_required
def alerts_hook_test(hid: int):
    """Manda uma mensagem agora para UM destino, para conferir se a URL esta certa."""
    conn = db()
    row = conn.execute(
        "SELECT nome, url FROM webhooks WHERE id = ?", (hid,)
    ).fetchone()
    if not row or not row["url"]:
        flash("Destino nao encontrado.", "error")
        return redirect(url_for("alerts"))
    # Se ha uma URL digitada no formulario, testa ELA: o ponto do botao e conferir a URL
    # nova antes de gravar, e nao repetir o teste da que ja estava salva.
    digitada = (request.form.get("url", "") or "").strip()[:400]
    if digitada and not URL_RE.match(digitada):
        flash("URL invalida (comece com http:// ou https://).", "error")
        return redirect(url_for("alerts"))
    erro = envia_webhook(
        digitada or row["url"],
        f"**Teste do painel de jogos**\nSe voce esta lendo isto, os alertas funcionam."
        f" ({session.get('username', '?')})",
    )
    nome = row["nome"] or "destino"
    flash(
        f"{nome}: {erro}" if erro else f"Mensagem enviada para {nome} - confira o canal.",
        "error" if erro else "ok",
    )
    return redirect(url_for("alerts"))


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
        "SELECT id, username, role, created_at, totp_enabled FROM users ORDER BY role, username"
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
        conn.execute(SQL_SET_PASSWORD, (hash_password(request.form.get("new", "")), uid))
    flash(f"Senha de '{alvo['username']}' redefinida.", "ok")
    return redirect(url_for("users_list"))


@app.post("/usuarios/<int:uid>/2fa/desligar")
@admin_required
def user_2fa_off(uid: int):
    """Celular perdido e codigos de recuperacao perdidos: o admin desliga o 2FA da pessoa, que
    entra so com a senha e ativa de novo. Nao vale para si mesmo (use a tela Conta)."""
    alvo = _usuario_ou_404(uid)
    if uid == session.get("uid"):
        flash("Para desligar o seu proprio 2FA use a tela Conta.", "error")
    else:
        _apaga_o_segundo_fator(uid)
        flash(f"Verificacao em duas etapas de '{alvo['username']}' desligada.", "ok")
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


@app.after_request
def _cabecalhos_de_seguranca(resp):
    """O painel da poder de root nos containers: nao pode ser embutido em outra pagina.

    Sem X-Frame-Options um site qualquer poe o painel num iframe invisivel e captura os
    cliques de quem esta logado (clickjacking) — e os botoes daqui param servidor.
    O Referrer-Policy impede que o endereco de uma tela do painel saia junto com um
    clique para fora.
    """
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


# ------------------------------------------------- aplicativo instalavel (PWA)

# Pastas cujo conteudo o painel consegue servir sem rede depois de instalado.
CASCO_PASTAS = ("css", "js", "icons")


def _arquivos_do_casco() -> tuple[list[str], int]:
    """URLs do casco do aplicativo e a marca de versao dele.

    A versao e o mtime mais recente entre esses arquivos. E o que faz um deploy
    chegar ao celular: byte novo no CSS -> versao nova -> arquivo do service worker
    diferente -> o navegador instala e descarta o cache velho. Sem isso, quem
    instalou o painel continuaria vendo a tela da semana passada.
    """
    urls: list[str] = []
    marca = 0
    for pasta in CASCO_PASTAS:
        raiz = os.path.join(app.static_folder or "", pasta)
        for base, _dirs, arquivos in os.walk(raiz):
            for nome in sorted(arquivos):
                caminho = os.path.join(base, nome)
                relativo = os.path.relpath(caminho, app.static_folder).replace(os.sep, "/")
                urls.append(static_url(relativo))
                marca = max(marca, int(os.path.getmtime(caminho)))
    return urls, marca


@app.get("/manifest.webmanifest")
def manifest():
    """Ficha do aplicativo: nome, icones, cor e tela inicial.

    Sai de um template (e nao de um arquivo estatico) para os caminhos dos icones
    virem do proprio Flask — inclusive a marca de versao do `static_url`.
    """
    resp = app.response_class(
        render_template("manifest.webmanifest.jinja"),
        mimetype="application/manifest+json",
    )
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/sw.js")
def service_worker():
    """O service worker, servido da RAIZ de proposito.

    O escopo de um service worker e a pasta em que ele mora: em /static/sw.js ele so
    enxergaria /static/ e nao veria a navegacao do painel. Por isso ele nao e um
    arquivo estatico — e uma rota.
    """
    precache, versao = _arquivos_do_casco()
    resp = app.response_class(
        render_template("sw.js.jinja", versao=versao, precache=precache),
        mimetype="text/javascript",
    )
    # Sem isto o proprio arquivo do worker ficaria em cache e o painel nunca
    # descobriria que existe uma versao nova dele.
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.get("/offline")
def offline():
    """Tela de "sem conexao", guardada no aparelho junto com o casco.

    Nao exige login: ela e servida do cache, sem passar pelo servidor, e nao mostra
    dado nenhum — so explica o que aconteceu e oferece "tentar de novo".
    """
    return render_template("offline.html")


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
    # Os dois tetos sao bem diferentes, e cair no 413 sem saber em qual deles nao ajuda
    # ninguem: o editor carrega o arquivo inteiro num textarea, o upload nao.
    if request.endpoint in BIG_BODY_ENDPOINTS:
        message = (
            f"Arquivo grande demais para o envio (limite de {_human_size(FILE_UPLOAD_MAX)})."
            " Para mandar um maior, suba o GAMEPANEL_UPLOAD_MAX do painel — conferindo"
            " antes se ha esse espaco livre no container do painel."
        )
    else:
        message = f"Conteudo grande demais (o editor aceita ate {FILE_MAX_BYTES // 1024} KB por arquivo)."
    return render_template(TPL_ERROR, code=413, message=message), 413


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
            conn.execute(SQL_SET_PASSWORD, (hash_password(password), row["id"]))
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


class ServidorDoDeploy(NamedTuple):
    """Os dados de um servidor vindos do deploy, num objeto so.

    Eram quinze parametros soltos. Quinze posicoes e o tipo de assinatura em que um
    `join_re` vai parar no lugar do `leave_re` e ninguem percebe ate a contagem de
    jogadores comecar a mentir. Como tupla nomeada, o campo tem nome no ponto de
    chamada e o objeto viaja inteiro entre as funcoes abaixo.
    """

    name: str
    host: str
    service: str
    ssh_port: int = 22
    ssh_user: str = "root"
    game_port: str = ""
    notes: str = ""
    config_path: str = ""
    config_files: str = ""
    backup_paths: str = ""
    join_re: str = ""
    leave_re: str = ""
    log_path: str = ""
    query_port: int = 0
    player_source: str = ""
    # Instancia do broker que originou este servidor (0 = cadastro manual/deploy antigo).
    broker_id: int = 0


def _insere_servidor(conn: sqlite3.Connection, dados: ServidorDoDeploy) -> None:
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service,"
        " game_port, notes, config_path, config_files, backup_paths,"
        " query_port, player_source, join_re, leave_re, log_path, broker_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (dados.name, dados.host, dados.ssh_port, dados.ssh_user, dados.service,
         dados.game_port, dados.notes, dados.config_path, dados.config_files,
         dados.backup_paths, dados.query_port, dados.player_source,
         dados.join_re, dados.leave_re, dados.log_path, dados.broker_id, now_iso()),
    )


def _junta_arquivos_de_config(guardados: str, novos: str) -> str:
    """Os arquivos ja cadastrados mais os do deploy, sem repetir e sem perder nenhum."""
    lista = [p for p in (guardados or "").splitlines() if p.strip()]
    for novo in novos.splitlines():
        if novo.strip() and novo.strip() not in lista:
            lista.append(novo.strip())
    return "\n".join(lista[:CONFIG_FILES_MAX])


def _atualiza_servidor(conn: sqlite3.Connection, atual, dados: ServidorDoDeploy) -> None:
    """Redeploy: o container manda no que e dele, o painel manda no que e escolha.

    Nome, servico, portas e caminho de config vem do deploy — sao fatos do container.
    Ja caminhos de backup, forma de contar jogadores e padroes do log costumam ser
    afinados na tela, e um redeploy nao pode apaga-los.
    """
    conn.execute(
        "UPDATE servers SET name=?, ssh_user=?, service=?, game_port=?,"
        " notes=?, config_path=?, config_files=?, backup_paths=?,"
        " query_port=?, player_source=?, join_re=?, leave_re=?, log_path=?"
        " WHERE id=?",
        (
            dados.name, dados.ssh_user, dados.service, dados.game_port,
            dados.notes or atual["notes"],
            dados.config_path or atual["config_path"],
            _junta_arquivos_de_config(atual["config_files"], dados.config_files),
            atual["backup_paths"] or dados.backup_paths,
            dados.query_port,
            atual["player_source"] or dados.player_source,
            atual["join_re"] or dados.join_re,
            atual["leave_re"] or dados.leave_re,
            atual["log_path"] or dados.log_path,
            atual["id"],
        ),
    )


def ensure_server(dados: ServidorDoDeploy) -> bool:
    """Cadastra (ou atualiza) um servidor sem passar pela tela. Devolve True se criou.

    E por aqui que o deploy registra o container recem-criado no painel — inclusive o
    arquivo de configuracao do jogo, para a tela "Configuracao" ja abrir pronta.
    """
    init_db()
    conn = _connect()
    try:
        with conn:
            atual = conn.execute(
                "SELECT * FROM servers WHERE host = ? AND ssh_port = ?",
                (dados.host, dados.ssh_port),
            ).fetchone()
            if atual is None:
                _insere_servidor(conn, dados)
                return True
            _atualiza_servidor(conn, atual, dados)
            return False
    finally:
        conn.close()


init_db()

# Sob o gunicorn este modulo e IMPORTADO — e o momento certo de subir o relogio. Pela
# linha de comando ele e o __main__ e isto nao roda: um `--register-server` no meio de um
# deploy nao pode disparar a tarefa agendada de passagem (e o processo morre em seguida,
# deixando o job pendurado em 'running').
if __name__ != "__main__":
    start_scheduler()
    retoma_jobs_do_broker()


if __name__ == "__main__":
    # A linha de comando mora em gamepanel/cli.py; o rodape aqui continua existindo
    # porque o README e o CLAUDE.md documentam `python3 .../app.py --reset-2fa USUARIO`,
    # e quem precisa desse comando esta trancado do lado de fora do painel.
    cli.main(cli.CliDeps(
        init_db=init_db, connect=_connect, ensure_admin_user=ensure_admin_user,
        ensure_server=ensure_server, servidor_do_deploy=ServidorDoDeploy,
        start_scheduler=start_scheduler, retoma_jobs_do_broker=retoma_jobs_do_broker,
        app=app, papeis=ROLES,
    ))
