#!/usr/bin/env python3
"""Painel administrativo dos servers de jogos.

Roda num container proprio e fala SSH *direto* com cada container de jogo — o host
Proxmox nao entra no caminho, o painel nao tem acesso a ele nem conhece `pct`.

Cada servidor cadastrado e um destino SSH (host/porta/usuario). Para o painel alcancar
um container, aquele container precisa ter sshd e a chave publica do painel autorizada
(veja a pagina "Acesso SSH" do painel).

Dependencias: python3-flask (apt). Hash de senha e sessao usam apenas a stdlib.
"""
from __future__ import annotations

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

# Rodando como SCRIPT (`python -m gamepanel.app` ou pelo caminho do arquivo), este modulo
# se chama `__main__` — e `gamepanel.app` nao esta em `sys.modules`. Quando um blueprint
# faz `from gamepanel import app as panel`, o Python importa o arquivo DE NOVO, do zero;
# essa segunda copia chega ao rodape, registra os blueprints outra vez e encontra o
# primeiro deles ainda pela metade ("partially initialized module ... has no attribute
# 'bp'"). Registrar o modulo sob o nome de import faz o blueprint achar esta copia, que e
# a que tem o `app` de verdade.
if __name__ == "__main__":  # pragma: no cover - so vale fora do import normal
    sys.modules.setdefault("gamepanel.app", sys.modules[__name__])

# markupsafe vem junto com o Jinja, que vem junto com o python3-flask do apt: nao e
# dependencia nova. E o mesmo escape que o autoescape do template usa.
from markupsafe import Markup, escape

from gamepanel import cli, config, i18n, version
from gamepanel import navigation as ui
from gamepanel.blueprints import register_all
from gamepanel.games import config_format as gameconf
from gamepanel.games import registry as game_fields
from gamepanel.integrations import broker_client, webhook_client
from gamepanel.persistence import schema
from gamepanel.persistence.repositories import alerts as alerts_repo
from gamepanel.persistence.repositories import jobs as jobs_repo
from gamepanel.persistence.repositories import samples as samples_repo
from gamepanel.persistence.repositories import settings as settings_repo
from gamepanel.persistence.repositories import users as users_repo
from gamepanel.persistence.repositories import schedules as schedules_repo
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.runtime import a2s, http_probe, log_probe, port_probe

# Apelido: ha uma rota `terminal()` neste mesmo modulo (a tela /servers/<id>/terminal),
# e o nome `terminal` sem apelido acabaria REBATIZADO por ela — o import ficaria valendo
# so ate a definicao da rota, silenciosamente (mypy pegou isso: "Name already defined").
# Apelidos pelo mesmo motivo: ha rotas `files()` (`/servers/<id>/files`) e
# `backups()` (`/servers/<id>/backups`) neste modulo.
from gamepanel.runtime import backups as backups_rt
from gamepanel.runtime import files as files_rt
from gamepanel.runtime import ssh as ssh_transport
from gamepanel.runtime import terminal as term_runtime
from gamepanel.security import csrf, passwords, totp
from gamepanel.services import (
    alert_service,
    auth_service,
    broker_service,
    chart_service,
    job_service,
    metrics_service,
    parallel,
    player_service,
    schedule_service,
    server_service,
    status_service,
)
from gamepanel.tasks import broker_jobs, log_stream, scheduler, ticker

# O terminal interativo depende de PTY (so existe em POSIX). Em outros sistemas o
# resto do painel continua funcionando e a tela do terminal responde 503.
HAVE_PTY = term_runtime.HAVE_PTY
from flask import (
    Flask,
    abort,
    flash,
    g,
    has_app_context,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# Um servidor cadastrado, como o resto do painel o enxerga.
#
# Ou e a linha do SQLite, ou uma COPIA dela em dict - e a copia nao e detalhe de
# implementacao: uma `sqlite3.Row` pertence a conexao que a produziu, e conexao de
# SQLite nao atravessa thread. Toda tarefa longa (um update de jogo leva quase uma hora)
# roda com `dict(server)` em vez da Row; ver `start_job`. As duas formas respondem a
# `server["host"]`, que e tudo o que estas funcoes precisam.
ServerRow = sqlite3.Row | Mapping[str, Any]


# ---------------------------------------------------------------- configuracao

# Uma leitura so, no import, com TODOS os problemas listados de uma vez (ver
# `config.py`). Os nomes de modulo abaixo continuam existindo porque os testes
# trocam `panel.X` por falso: ler `settings.x` direto neles faria a troca deixar
# de valer em silencio.
settings = config.load()

DB_PATH = settings.db_path
SECRET_FILE = settings.secret_file
SSH_KEY = settings.ssh_key
# Gravavel: as host keys dos containers sao aprendidas no primeiro acesso (accept-new).
KNOWN_HOSTS = settings.known_hosts
# Onde ficam os sockets de conexao reaproveitada do SSH. Ao lado do known_hosts, e nao no
# /tmp: o socket da acesso a uma sessao ja autenticada nos containers de jogo, e /tmp e
# espaco compartilhado — pasta do proprio painel, com 0700, fecha essa porta.
SSH_CONTROL_DIR = settings.ssh_control_dir
# Quanto a conexao mestre fica de pe depois que o comando dela termina. E o que faz a
# volta seguinte do monitor pegar carona em vez de pagar outro aperto de mao; 60s cobre
# com folga o ritmo do monitor (15s a 60s) sem deixar conexao ociosa pendurada por horas.
SSH_CONTROL_PERSIST = settings.ssh_control_persist

# Comandos rapidos (status, logs) x comandos longos (update baixa o jogo inteiro).
QUICK_TIMEOUT = 20
JOB_TIMEOUT = settings.job_timeout
STATUS_TTL = 8.0
# Medidores de CPU/memoria/disco/rede: cada leitura custa uma ida de SSH de ~1s.
METRICS_TTL = settings.metrics_ttl

# Console web: executa comandos como root DENTRO do container de jogo escolhido.
# E a funcionalidade mais poderosa do painel — desligue com GAMEPANEL_ALLOW_SHELL=0.
ALLOW_SHELL = settings.allow_shell
SHELL_TIMEOUT = settings.shell_timeout
SHELL_MAX_LEN = 4000

# Terminal interativo: sessao SSH viva com PTY, teclado ligado no shell do container.
# Herda o ALLOW_SHELL (e o mesmo poder do console, so que interativo).
TERM_MAX_SESSIONS = settings.term_max_sessions
TERM_IDLE_TIMEOUT = settings.term_idle_timeout
TERM_BUFFER_BYTES = 512 * 1024
TERM_POLL_WAIT = 20.0  # long-poll: segura a resposta ate chegar saida nova

# Broker de provisionamento: cria instancias de jogo e abre portas no firewall. O painel
# nao guarda credencial de Proxmox/OPNsense, so o token do broker. DESLIGADO por padrao: quem
# liga (GAMEPANEL_ALLOW_BROKER=1) precisa apontar URL, arquivo do token e, em https, a
# impressao SHA-256 do certificado. Sem isso o recurso nao aparece em lugar nenhum.
BROKER_URL = settings.broker_url
BROKER_TOKEN_FILE = settings.broker_token_file
BROKER_CERT_SHA256 = settings.broker_cert_sha256
BROKER_POLL = settings.broker_poll
# Voltas seguidas sem resposta do broker antes de dar o job por perdido.
BROKER_FAILURES_MAX = 15
# Nomes de MODULO, e nao `settings.x` direto dentro de `_configure_broker`: os testes
# trocam `panel.X` por falso para exercitar cada configuracao ruim, e uma leitura do
# `settings` ali dentro ignoraria a troca.
BROKER_REQUESTED = settings.allow_broker
DEV = settings.dev


def _configure_broker() -> bool:
    """Liga o cliente do broker. Qualquer configuracao ruim DESLIGA o recurso (e loga o
    motivo) em vez de derrubar o painel: o resto dele nao depende disto."""
    if not BROKER_REQUESTED:
        return False
    try:
        with open(BROKER_TOKEN_FILE, encoding="utf-8") as file_path:
            token = file_path.read().strip()
        broker_client.configure(BROKER_URL, token, BROKER_CERT_SHA256,
                                 allow_http=DEV)
    except (OSError, ValueError) as failure:
        print(f"[painel] broker DESLIGADO: {failure}", file=sys.stderr)
        return False
    return True


ALLOW_BROKER = _configure_broker()

# Editor de arquivos: le/grava arquivos de configuracao do jogo pelo mesmo SSH.
ALLOW_FILES = settings.allow_files
# 1 = quem nao ativou o segundo fator so alcanca a tela de ativacao. Desligado por padrao: ligar
# ANTES de cada admin ter o aplicativo no celular tranca todo mundo fora do painel.
REQUIRE_2FA = settings.require_2fa
# Limite para EDITAR (o arquivo inteiro vai para um textarea e volta num POST).
FILE_MAX_BYTES = settings.file_max_bytes
# Acima do limite de edicao o painel ainda mostra o fim do arquivo, so para leitura.
FILE_PREVIEW_BYTES = settings.file_preview_bytes
# Download nao passa por memoria (vai em streaming), entao o teto e bem maior.
# 0 = sem limite.
FILE_DOWNLOAD_MAX = settings.file_download_max
DOWNLOAD_CHUNK = 256 * 1024
# Teto do corpo de um request: o arquivo editado sobe percent-encoded (ate 3x) + folga.
REQUEST_LIMIT = max(4 * 1024 * 1024, FILE_MAX_BYTES * 4 + 65536)
# Raizes onde o navegador de arquivos pode entrar. "/" = sem restricao.
FILE_ROOTS = settings.file_roots
FILE_DEFAULT_PATH = settings.file_default_path
FILE_LIST_MAX = 800
# Upload: o arquivo sobe em multipart e desce por SSH em streaming, sem passar inteiro
# pela memoria do painel — por isso o teto aqui e bem maior que o do editor, que carrega
# tudo num textarea. 0 = sem limite.
#
# Cuidado ao aumentar: o Werkzeug guarda o corpo do multipart num arquivo temporario do
# CONTAINER DO PAINEL antes de a view ver um byte. Subir 2 GB exige 2 GB livres la — e o
# CT do painel costuma ser pequeno. 512 MB cobre mod e save sem esse risco.
FILE_UPLOAD_MAX = settings.file_upload_max
UPLOAD_CHUNK = 256 * 1024

# Backup: tar.gz das pastas que valem a pena guardar (save + configuracao do jogo),
# criado DENTRO do container e guardado la. O painel nao vira deposito de save — ele
# dispara, lista, baixa e restaura.
BACKUP_DIR = settings.backup_dir
# Quantas copias manter por servidor; as mais antigas saem sozinhas. 0 = nunca apagar.
BACKUP_KEEP = settings.backup_keep
BACKUP_TIMEOUT = settings.backup_timeout
BACKUP_PATHS_MAX = 8
BACKUP_LIST_MAX = 100

# Agendamento: tarefas que o painel dispara sozinho (reiniciar de madrugada, backup
# diario). O relogio e o do CONTAINER DO PAINEL — se as horas nao baterem com as suas,
# o que esta errado e o TZ dele.
# Este e o piso de TODOS os avisos do painel: nada pode chegar mais rapido do que a volta
# do relogio. Ele mesmo custa quase nada (as quatro tarefas tem cada uma o seu proprio
# ritmo la dentro e saem na hora quando nao e a vez delas), entao 15s da folga para o
# alerta de jogador sem multiplicar SSH de ninguem.
SCHEDULE_TICK = settings.schedule_tick
# Tarefa atrasada demais nao dispara. Se o painel passou a noite fora do ar, ninguem quer
# o "reiniciar as 5h" caindo as 14h, no meio da partida: ela espera a proxima ocorrencia.
SCHEDULE_GRACE = settings.schedule_grace
# Nome que aparece no historico no lugar do usuario, quando quem disparou foi o relogio.
SCHEDULE_USER = "agendador"

# Retencao do historico: cada job guarda ate 200 KB de saida, e um backup diario sozinho
# ja poe 365 linhas por ano no banco. 0 desliga a limpeza.
JOBS_KEEP_DAYS = settings.jobs_keep_days
JOBS_PURGE_EVERY = 3600.0
HISTORY_PAGE = 60

# Amostras para os graficos de uso. Cada uma custa uma leitura de medidores — a chamada
# mais cara do painel (o script remoto dorme 0,5s para tirar duas amostras de CPU) —,
# entao o intervalo e generoso: 5 min dao 288 pontos por dia, de sobra para o grafico.
SAMPLE_EVERY = settings.sample_every
SAMPLES_KEEP_DAYS = settings.samples_keep_days

# Alertas: o painel avisa por webhook (Discord, Slack, o que aceitar um POST de JSON)
# quando um servidor cai, some do SSH, enche o disco ou quando uma tarefa agendada falha.
# A URL fica no banco (tela "Alertas"); esta variavel so serve de valor inicial, para o
# deploy poder deixar tudo pronto.
DEFAULT_WEBHOOK_URL = settings.webhook_url
WEBHOOK_TIMEOUT = settings.webhook_timeout
# O Cloudflare na frente do Discord devolve 403 (erro 1010) para o User-Agent padrao do
# urllib ("Python-urllib/3.x"), antes mesmo do pedido chegar no webhook. Mandar um
# User-Agent proprio resolve, e nenhum outro destino se incomoda com ele.
WEBHOOK_UA = settings.webhook_ua
# Teto de destinos. Cada alerta vira um POST por destino, em serie, dentro da volta do
# monitor — uma lista sem fim faria a volta esperar por todos eles.
WEBHOOK_MAX = settings.webhook_max
# De quanto em quanto tempo o painel confere o estado de cada servidor. Cada volta custa
# uma ida de SSH por servidor — nao adianta descer muito.
MONITOR_EVERY = settings.monitor_every
# Jogador entrando e a unica coisa que alguem espera ver "agora" — quem recebe o aviso
# costuma querer entrar junto, e um minuto depois ja e tarde. Por isso ele tem relogio
# proprio, mais curto que o do estado.
PLAYER_CHECK_EVERY = settings.player_check_every
# ...mas so vale para quem responde de graca. A2S e HTTP saem de dentro do container sem
# nada extra; a contagem por LOG e outra historia: cada consulta e uma ida de SSH que
# arrasta ate LOG_SCAN_MAX linhas para o painel aplicar o regex. Nesse ritmo curto isso
# seriam megabytes por minuto por servidor, para achar duas linhas novas. Quem conta por
# log fica no relogio do estado ate existir leitura incremental ou log em streaming.
PLAYER_FAST_SOURCES = {"a2s", "http"}
# Quem conta por log ganha tempo real por outro caminho: uma conexao SSH longa rodando
# `journalctl -f`. Em vez de perguntar "tem alguem novo?" de minuto em minuto, o painel
# fica ouvindo e reage a linha no instante em que ela sai.
LOG_STREAM = settings.log_stream
# Uma entrada e uma saida no mesmo segundo (alguem trocando de servidor, um grupo
# entrando junto) nao podem virar uma releitura do log cada. A primeira linha dispara,
# as seguintes dessa janela pegam carona na mesma conferida.
LOG_STREAM_DEBOUNCE = settings.log_stream_debounce
# Depois de a conexao cair, quanto esperar antes de tentar de novo. Servidor desligado
# nao pode virar um laco de SSH a cada segundo.
LOG_STREAM_RETRY = settings.log_stream_retry
# O disco sai dos medidores, que custam bem mais caro (o script remoto dorme 0,5s para
# tirar duas amostras). Ele nao enche em um minuto, entao a conferida e espacada.
DISK_CHECK_EVERY = settings.disk_check_every
# Uma acao do painel (parar, reiniciar, atualizar) derruba o servidor de proposito. Nesta
# janela depois dela, queda nao vira alerta — senao todo restart pelo botao viraria susto.
ALERT_QUIET = settings.alert_quiet

# Padroes usados pelo botao "procurar arquivos de config".
CONFIG_GLOBS = ("*.ini", "*.cfg", "*.conf", "*.json", "*.yaml", "*.yml", "*.properties", "*.txt")
# Quantos arquivos de configuracao um servidor pode ter registrados para a tela "Config".
CONFIG_FILES_MAX = 8
# Teto de campos no formulario da tela "Config": acima disso o arquivo quase certamente
# nao e configuracao (um log casa com "chave=valor" em varias linhas).
CONFIG_SETTINGS_MAX = 600

# Formato de data curto do painel ("17/09 05:00"). Estava escrito a mao em tres
# telas; uma delas com um espaco a mais bastaria para a lista parecer desalinhada.
SHORT_DATE_FORMAT = "%d/%m %H:%M"

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
# O VALOR e a coluna `role` no banco: mudar "operador" para "operator" rebaixaria todo
# operador ja cadastrado a "papel desconhecido". So o nome da constante e traduzido.
ROLE_OPERATOR = "operador"
ROLES = (ROLE_ADMIN, ROLE_OPERATOR)
# Chave de catalogo, nao o texto: quem le a tela escolhe o idioma (`i18n`).
ROLE_LABELS = {
    ROLE_ADMIN: "role.admin",
    ROLE_OPERATOR: "role.operator",
}
PASSWORD_MIN = passwords.MIN_LENGTH

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
if DEV:
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
    schema.init_db(DB_PATH, DEFAULT_WEBHOOK_URL, ALERT_DEFAULT, now_iso)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------- senhas


# Apelidos: o algoritmo mora em `security/passwords.py`, mas os testes trocam
# `panel.X` por falso e os templates chamam `csrf_token()` pelo nome — manter os dois
# aqui e o que faz as duas coisas continuarem valendo.
hash_password = passwords.hash_password
verify_password = passwords.verify_password


# ------------------------------------------------------- auth / csrf / brute force

LOCKOUT_TRIES = 5
LOCKOUT_WINDOW = 300.0
# O chute de 6 digitos tem 3 numeros validos em 10^6: por isso a trava do codigo e por
# USUARIO (nao por IP, que um atacante troca) e mais longa que a da senha.
LOCKOUT_2FA_TRIES = 5
LOCKOUT_2FA_WINDOW = 900.0

# A chave da trava da senha e `ip|usuario` e a do codigo e `2fa|usuario`: instancias
# separadas porque os limites diferem, e nao porque as chaves colidiriam.
login_lockout = auth_service.Lockout(LOCKOUT_TRIES, LOCKOUT_WINDOW)
totp_lockout = auth_service.Lockout(LOCKOUT_2FA_TRIES, LOCKOUT_2FA_WINDOW)


def logged_user() -> sqlite3.Row | None:
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
        row = users_repo.for_session(db(), uid)
    g._user = row
    return row


def is_admin() -> bool:
    row = logged_user()
    return row is not None and row["role"] == ROLE_ADMIN


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if logged_user() is None:
            # Conta apagada com a sessao ainda aberta: o cookie continua assinado e
            # valido, entao sem conferir o banco ela seguiria funcionando ate expirar.
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    """Rotas que dao poder de root no container ou mexem em quem tem acesso."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            abort(403, i18n.Message("error.admin_only"))
        return view(*args, **kwargs)

    return login_required(wrapper)


def csrf_token() -> str:
    return csrf.token(session)


# Rotas que recebem corpo grande. O teto geral (MAX_CONTENT_LENGTH) e apertado porque o
# editor manda o arquivo percent-encoded dentro de um formulario; o upload precisa de bem
# mais que isso.
#
# Este hook tem de vir ANTES do _check_csrf no arquivo: a ordem de registro e a ordem de
# execucao, e e o _check_csrf quem toca em request.form primeiro — o teto e conferido na
# hora em que o corpo e lido, entao ajustar so la dentro da view chegaria tarde (413).
BIG_BODY_ENDPOINTS = {"files.upload"}


@app.before_request
def _body_cap():
    if request.endpoint in BIG_BODY_ENDPOINTS:
        request.max_content_length = (FILE_UPLOAD_MAX + UPLOAD_CHUNK) if FILE_UPLOAD_MAX else None


@app.before_request
def _check_csrf():
    if request.method != "POST":
        return None
    if not csrf.matches(session, request.form, request.headers):
        abort(400, i18n.Message("error.csrf_invalid"))
    return None


# Com GAMEPANEL_REQUIRE_2FA=1 quem ainda nao ativou o segundo fator so alcanca isto.
ENDPOINTS_WITHOUT_2FA = frozenset({
    "auth.login", "auth.login_2fa", "auth.logout", "account.two_factor",
    "health.health", "static",
    "pwa.manifest", "pwa.service_worker", "pwa.offline",
})


@app.before_request
def _requires_second_factor():
    if not REQUIRE_2FA or request.endpoint in ENDPOINTS_WITHOUT_2FA or request.endpoint is None:
        return None
    user = logged_user()
    if user is None or user["totp_enabled"]:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "ative a verificacao em duas etapas em Conta"}), 403
    flash(translate("flash.two_factor_required_here"), "error")
    return redirect(url_for("account.two_factor"))


def static_url(name: str) -> str:
    """URL de um arquivo estatico com a marca do mtime.

    Sem isto, um deploy que muda o css/components.css ou o js/terminal.js continua
    servindo o que o navegador guardou — e o relato chega como "a tela quebrou depois
    da atualizacao".

    Aceita caminho com subpasta ("css/tokens.css"): a arvore de estaticos e organizada
    em css/, js/ e icons/.
    """
    try:
        mark = int(os.path.getmtime(os.path.join(app.static_folder or "", name)))
    except OSError:
        mark = 0
    return url_for("static", filename=name, v=mark)


DEFAULT_LANG = i18n.valid_language(settings.lang)


def current_language() -> str:
    """O idioma DESTE pedido, decidido uma vez e guardado no `g`.

    A ordem e de preferencia: o que a pessoa escolheu na Conta vence tudo; sem escolha
    (ou sem ninguem logado, como na tela de login) vale o que o navegador pede; e o
    ultimo recurso e o padrao do deploy.

    FORA de pedido nao ha pessoa nem navegador, e o `g` nem existe: o monitor e o
    agendador rodam em thread propria, e o alerta que sai dali e escrito para o canal da
    equipe, nao para quem esta com a tela aberta. Ali vale o padrao do deploy. Sem este
    portao, traduzir uma mensagem de alerta derrubaria a volta inteira do monitor com
    "Working outside of application context" — e alerta que quebra e servidor caido que
    ninguem fica sabendo.
    """
    if not has_app_context():
        return DEFAULT_LANG
    chosen_one = getattr(g, "_language", None)
    if chosen_one is not None:
        return chosen_one
    user = logged_user()
    from_user = _stored_value(user, "lang") if user else ""
    if from_user:
        chosen_one = i18n.valid_language(from_user)
    elif request:
        chosen_one = i18n.from_header(request.headers.get("Accept-Language"))
    else:
        chosen_one = DEFAULT_LANG
    g._language = chosen_one
    return chosen_one


def translate(key: str, **fields: object) -> str:
    """O `_()` das telas e das mensagens: a frase daquela chave, no idioma
    deste pedido."""
    return i18n.translate(key, current_language(), **fields)


def error_text(exc: BaseException) -> str:
    """O que a excecao tem a dizer, preservando a CHAVE quando ela veio de uma.

    `str(exc)` colapsaria uma `i18n.Mensagem` em texto solto, e com ela a chance de
    mostrar a frase no idioma de quem esta olhando. Um `except` pega qualquer excecao,
    inclusive as que nascem fora daqui (`OSError`, `json`), e essas seguem por `str`.
    """
    if exc.args and isinstance(exc.args[0], i18n.Message):
        return exc.args[0]
    return str(exc)

def label_for_db(key: str) -> str:
    """A frase daquela chave no idioma do DEPLOY, nao no de quem esta com a tela aberta.

    Para texto que vai ser GRAVADO (a coluna `command` de um job, por exemplo). O
    historico e lido depois, por outra pessoa, talvez noutro idioma: se cada registro
    saisse no idioma de quem clicou, a mesma acao apareceria escrita de tres jeitos na
    mesma lista, e filtrar por ela deixaria de funcionar.
    """
    return i18n.translate(key, DEFAULT_LANG)


def translate_html(key: str, **fields: object) -> Markup:
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
    return Markup(i18n.translate(  # noqa: S704
        key, current_language(), **{name: escape(value) for name, value in fields.items()}
    ))


def labels_of(labels: dict[str, str]) -> dict[str, str]:
    """Traduz uma tabela de rotulos de uma vez, para a tela receber texto pronto.

    As tabelas (`ALERT_EVENTS`, `JOB_LABELS`, `ROLE_LABELS`, ...) guardam a CHAVE do
    catalogo e nao a frase: a chave e o que vai para o banco e para o `<option value=>`,
    e ela nao pode mudar so porque alguem corrigiu uma virgula no texto.
    """
    return {key: translate(label) for key, label in labels.items()}

@app.context_processor
def _inject():
    user = logged_user()
    return {
        "csrf_token": csrf_token,
        # `_` e o nome de sempre para traduzir numa tela; `_h` e o irmao para a frase
        # que traz marcacao (ver `traduzir_html`).
        "_": translate,
        "_h": translate_html,
        "current_language": current_language(),
        "languages": i18n.LANGUAGES,
        "static_url": static_url,
        "current_user": user["username"] if user else None,
        # As telas escondem o que o operador nao pode abrir. Quem manda e o
        # @admin_required na rota; isto aqui e so para nao mostrar botao que da 403.
        "is_admin": bool(user) and user["role"] == ROLE_ADMIN,
        "role_label": translate(ROLE_LABELS[user["role"]]) if user else "",
        "job_label": job_label,
        # Que codigo esta servindo esta tela. Vai no rodape, e nao so no /health, porque
        # quem abre um chamado ("a tela nao atualizou") esta olhando a TELA — e a
        # resposta cabe numa linha que ele consegue ler em voz alta.
        "app_version": version.BUILD.version,
        "allow_shell": ALLOW_SHELL,
        "allow_term": ALLOW_SHELL and HAVE_PTY,
        "allow_files": ALLOW_FILES,
        "allow_broker": ALLOW_BROKER,
        # A tela precisa saber se a contagem esta ligada, e ela pode vir da porta de
        # consulta OU do log — nao da para olhar so o query_port.
        "player_source": player_source,
        # Quais acoes a API daquele servidor aceita (vazio na maioria dos jogos).
        "player_actions": player_actions,
        "action_label": labels_of(PLAYER_ACTION_LABELS),
        **_navigation_context(),
    }


def _navigation_context() -> dict:
    """O mapa da interface, ja filtrado para quem esta logado e para este deploy.

    Os templates nao decidem mais o que existe no menu: eles desenham o que vier
    daqui. Antes, a lista de telas de um servidor estava escrita a mao em seis
    templates diferentes, cada um com um subconjunto proprio — e era por isso que
    "Graficos" existia numa tela e nao na outra.
    """
    admin = is_admin()
    sections = ui.visible_sections(admin=admin, arquivos=ALLOW_FILES, shell=ALLOW_SHELL)
    has_pty = ALLOW_SHELL and HAVE_PTY
    slash, account = ui.nav_desktop(admin=admin, broker=ALLOW_BROKER)
    return {
        "nav_main": ui.visible_items(ui.NAV_MAIN, admin=admin, broker=ALLOW_BROKER),
        "nav_secondary": ui.visible_items(ui.NAV_SECONDARY, admin=admin, broker=ALLOW_BROKER),
        "nav_active": ui.active_nav_for(request.endpoint),
        "nav_desktop_bar": slash,
        "nav_desktop_account": account,
        "nav_active_desktop": ui.active_desktop_nav_for(request.endpoint),
        "server_sections": sections,
        "section_endpoint": lambda section: ui.section_endpoint(section, tem_pty=has_pty),
        "power_actions": ui.actions_in_group(ui.GROUP_POWER),
        "maintenance_actions": ui.actions_in_group(ui.GROUP_MAINTENANCE),
        "card_power": ui.card_power,
        "remaining_power": ui.remaining_power,
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


def in_parallel(tasks: dict, timeout: float = 40.0) -> dict:
    """Roda varias leituras remotas ao mesmo tempo; devolve {nome: (valor, erro)}.

    Cada uma custa a sua ida de SSH, e elas nao dependem umas das outras — em serie a
    tela paga a soma, e com um servidor fora do ar paga a soma dos timeouts.

    Nada aqui pode tocar no `g` do Flask (a conexao por request nao atravessa thread).
    As funcoes usadas na tela de detalhe ou nao falam com o banco, ou abrem conexao
    propria — o `http_login` da contagem por API e o caso, e ele ja faz assim.
    """
    output: dict = {}
    lock = threading.Lock()

    def work(name, call):
        try:
            value, failure = call(), ""
        except (RemoteError, QueryError) as exc:
            value, failure = None, str(exc)
        with lock:
            output[name] = (value, failure)

    threads = [threading.Thread(target=work, args=(n, f), daemon=True)
               for n, f in tasks.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    for name in tasks:
        output.setdefault(name, (None, MSG_TIMEOUT))
    return output


# ------------------------------------------------------------- jogadores (A2S)
#
# Implementacao real em gamepanel.runtime.a2s (extraida na Fase 4). Os nomes abaixo
# continuam existindo neste modulo de proposito - QueryError em particular e usado por
# `raise`/`except` em todo o resto de app.py (HTTP, log, acoes de jogador), e
# `pytest.raises(panel.QueryError)` em test_players.py precisa continuar achando a
# MESMA classe.
QUERY_TIMEOUT = settings.query_timeout
PLAYERS_TTL = settings.players_ttl

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
HTTP_TIMEOUT = settings.http_timeout
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
_has_login = player_service._has_login


def http_json(server: ServerRow, url: str, auth: str, body: str, exigir_json: bool = True):
    # HTTP_TIMEOUT lido na hora da chamada, nao congelado - mesmo cuidado do SshClient
    # (runtime/ssh.py) e do query_players (runtime/a2s.py).
    return http_probe.http_json(ssh_output, server, url, auth, body, HTTP_TIMEOUT, exigir_json)


def _stored_value(server: ServerRow, coluna: str) -> str:
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


def http_login(server: ServerRow) -> str:
    return player_service.http_login(_player_deps(), server)


def call_game_api(server: ServerRow, url: str, body: str = "",
                      exigir_json: bool = True):
    return player_service.call_game_api(_player_deps(), server, url, body, exigir_json)


def players_from_http(server: ServerRow) -> dict:
    return player_service.players_from_http(_player_deps(), server)


# ------------------------------------------- acoes sobre quem esta jogando
#
# Catalogo e regra em gamepanel.services.player_service; aqui ficam so os nomes que a
# tela, as rotas e os testes ja usam.

PLAYER_MSG_MAX = player_service.PLAYER_MSG_MAX
PLAYER_ACTION_LABELS = player_service.PLAYER_ACTION_LABELS
BASE_MARK = player_service.BASE_MARK
PLAYER_MARK = player_service.PLAYER_MARK
MESSAGE_MARK = player_service.MESSAGE_MARK
API_ACTIONS = player_service.API_ACTIONS
actions_api = player_service.actions_api
player_actions = player_service.player_actions
_fill = player_service._fill


def run_player_action(server: ServerRow, action: str, player: str, message: str) -> str:
    return player_service.player_action(_player_deps(), server, action, player, message)


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
valid_log_path = log_probe.valid_log_path


# ------------------------------------------- descobrir como contar jogadores
#
# Implementacao real em gamepanel.runtime.port_probe (Fase 4). Nomes preservados aqui
# pelos mesmos dois motivos de sempre: teste direto por nome (`panel._portas_do_texto`,
# `panel._sem_repetir`, `panel._com_dono`, `panel._resume_genericos`) e uso por rotas
# que ainda nao foram extraidas.
QUERY_PORT_GUESSES = port_probe.QUERY_PORT_GUESSES
API_PORT_GUESSES = port_probe.API_PORT_GUESSES
HTTP_PROBE_TIMEOUT = settings.http_probe_timeout
HTTP_PROBE_PORTS_MAX = port_probe.HTTP_PROBE_PORTS_MAX
_ports_from_text = port_probe._ports_from_text
_without_repeats = port_probe._without_repeats
_with_owner = port_probe._with_owner
_summarize_generic = port_probe._summarize_generic


def candidate_ports(server: ServerRow) -> tuple[list[int], list[int], dict, str]:
    return port_probe.candidate_ports(ssh_output, server, server["game_port"])


def probe_http_ports(server: ServerRow, ports: list[int]) -> tuple[list[dict], list[int], str]:
    return port_probe.probe_http_ports(ssh_output, server, ports, HTTP_PROBE_TIMEOUT)


def probe_ports(host: str, ports: list[int]) -> list[dict]:
    return port_probe.probe_ports(host, ports, QUERY_TIMEOUT)


def read_log_lines(server: ServerRow, limit: int = LOG_SCAN_MAX) -> list[str]:
    return log_probe.read_log_lines(
        ssh_output, server, server["service"], _stored_value(server, "log_path"), limit,
    )


def players_from_log(server: ServerRow) -> dict:
    return player_service.players_from_log(_player_deps(), server)


# O MESMO objeto do service (nao uma copia): a fixture `banco` dos testes limpa a
# contagem guardada por este nome, e um dicionario diferente aqui deixaria o cache de
# verdade intacto entre os casos.
_players_cache = player_service._players_cache
invalidate_players = player_service.invalidate
player_source = player_service.player_source


def server_players(server: ServerRow, force: bool = False) -> dict:
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


def server_metrics(server: ServerRow, force: bool = False) -> dict:
    return metrics_service.server_metrics(
        ssh_output, server, FILE_DEFAULT_PATH, METRICS_TTL, force)


def all_metrics(servers) -> dict[int, dict]:
    # `server_metrics` entra por lambda para o nome ser resolvido neste modulo a cada
    # chamada — e o que mantem a troca por um falso valendo dentro do paralelo.
    return parallel.per_server(
        lambda srv: server_metrics(srv), servers, 35, {"error": MSG_TIMEOUT})


# --------------------------------------------------------------- status cache

_status_cache = status_service._status_cache
invalidate_status = status_service.invalidate


def server_status(server: ServerRow, force: bool = False) -> dict:
    return status_service.server_status(ssh_output, server, STATUS_TTL, force)


def all_status(servers) -> dict[int, dict]:
    return parallel.per_server(
        lambda srv: server_status(srv), servers, QUICK_TIMEOUT + 5,
        {"reachable": False, "service": "desconhecido", "error": MSG_TIMEOUT},
    )


# ------------------------------------------------------------------- jobs

# O que cada acao RODA no container. Como ela se apresenta (rotulo, icone, grupo,
# peso visual) e outra responsabilidade, e mora no `ui.py` — aqui ficam so os
# comandos, que e o que este modulo tem para dizer sobre elas.
COMMANDS = {
    "start": lambda s: q("systemctl", "start", s["service"]),
    "restart": lambda s: q("systemctl", "restart", s["service"]),
    "stop": lambda s: q("systemctl", "stop", s["service"]),
    "update": lambda s: "/usr/local/bin/update-game",
    "check-update": lambda s: "/usr/local/bin/check-game-update",
}

# As duas listas nao podem divergir em silencio: uma acao com botao e sem comando da
# 500 no clique, e uma com comando e sem botao e codigo morto que ninguem percebe.
assert set(COMMANDS) == set(ui.BY_KEY), "ui.ACOES e COMANDOS fora de sincronia"

# Forma antiga, montada a partir das duas: chave -> (rotulo, comando, confirma).
# Continua sendo o que `start_job` e o historico consomem.
ACTIONS = {
    key: (ui.BY_KEY[key].label, command, ui.BY_KEY[key].confirm)
    for key, command in COMMANDS.items()
}

# Os rotulos das acoes de botao vem do `ui`; os das acoes que nascem de outras telas
# (console, editor, broker) vem do `job_service`, junto da lista de quem pode le-las.
JOB_LABELS = job_service.labels(
    {key: label for key, (label, _cmd, _c) in ACTIONS.items()})
JOB_ACTIONS_ADMIN = job_service.ADMIN_ONLY_ACTIONS


def job_label(action: str) -> str:
    """O nome da acao na tela. `JOB_LABELS` guarda CHAVE, nunca texto pronto:
    o historico e uma tela como as outras e segue o idioma de quem a abriu.
    """
    return translate(JOB_LABELS.get(action, action))


def job_or_403(job: sqlite3.Row) -> None:
    """Barra o operador na saida de um job que ele nao teria permissao de disparar."""
    if job_service.is_restricted(job["action"]) and not is_admin():
        abort(403, i18n.Message("error.job_admin_only"))


def role_filter() -> tuple[str, tuple]:
    """Pedaco de WHERE que esconde do operador os jobs das acoes restritas."""
    return job_service.hidden_filter(is_admin())


def server_jobs(conn: sqlite3.Connection, sid: int, limit: int) -> list:
    """Historico do servidor ja filtrado pelo papel de quem esta olhando."""
    cut, values = role_filter()
    return jobs_repo.of_server(conn, sid, limit, cut, values)


def _inserted_id(cur: sqlite3.Cursor) -> int:
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
    server: ServerRow | dict,
    username: str,
    command: str = "",
    output: str = "",
    status: str = "ok",
) -> int:
    """Registra no historico algo que ja aconteceu (edicao de arquivo, sessao de
    terminal). Diferente de start_job, nao dispara nada — so deixa o rastro."""
    conn = db()
    with conn:
        return jobs_repo.record(conn, server, action, status, output, command,
                                username, now_iso())


def start_job(
    action: str,
    server: ServerRow,
    username: str,
    remote_cmd: str | None = None,
    command: str = "",
    timeout: int = JOB_TIMEOUT,
) -> int:
    # Resolvido AQUI, e nao dentro do `run()` la embaixo: o que a thread executa nao
    # pode depender de um parametro opcional que alguem mude no meio do caminho.
    remote_command: str = remote_cmd if remote_cmd is not None else ACTIONS[action][1](server)
    conn = db()
    with conn:
        job_id = jobs_repo.start(conn, server, action, command, username, now_iso())
    server_id = int(server["id"])
    # A thread nao pode usar a Row ligada a conexao do request: copia o que precisa.
    target = dict(server)

    def run():
        try:
            # Conexao propria: um update leva quase uma hora, e a mestre compartilhada
            # ficaria presa a ele — com o monitor inteiro dependendo de um comando que
            # pode cair no meio.
            proc = ssh_run(target, remote_command, timeout=timeout, multiplex=False)
            output = (proc.stdout or "") + (proc.stderr or "")
            status = "ok" if proc.returncode == 0 else "error"
            code = proc.returncode
        except RemoteError as exc:
            output, status, code = str(exc), "error", None
        # Conexao propria: esta thread vive fora do contexto do request.
        conn2 = _connect()
        with conn2:
            jobs_repo.finish(conn2, job_id, status, code, output, now_iso())
        # Falha de tarefa AGENDADA vira alerta: e a unica que ninguem esta olhando. Quem
        # clicou o botao ja esta com o resultado na tela.
        if status == "error" and username == SCHEDULE_USER:
            try:
                notify(conn2, "job-falhou",
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

# O VALOR e chave de catalogo; a CHAVE e o que vai para o banco e para o webhook.
# Trocar o texto de um evento nao pode mexer no que ja esta gravado em `alertas`.
ALERT_EVENTS = {
    "caiu": "event.server_stopped",
    "voltou": "event.server_back",
    "quebrou": "event.game_failed",
    "reiniciando": "event.restart_loop",
    "travou": "event.game_mute",
    "respondeu": "event.game_answering",
    "jogador-entrou": "event.player_joined",
    "jogador-saiu": "event.player_left",
    "erro-no-log": "event.log_error",
    "inacessivel": "event.lost_contact",
    "acessivel": "event.contact_back",
    "job-falhou": "event.scheduled_task_failed",
    "disco-cheio": "event.disk_almost_full",
    "memoria-alta": "event.memory_almost_full",
    "cpu-alta": "event.cpu_high",
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
RESOURCE_EVENTS = {"disco-cheio", "memoria-alta", "cpu-alta"}
# Quantas linhas do diario de alertas ficam guardadas.
ALERT_LOG_KEEP = settings.alert_log_keep

# Quantas voltas seguidas o jogo precisa ficar mudo antes do alerta. Uma consulta A2S e
# UDP: um pacote perdido e rotina, e alertar no primeiro silencio encheria o canal de
# susto falso.
MUTE_ROUNDS = settings.mute_rounds
# O log e o unico destes que custa uma ida de SSH propria, entao tem o seu intervalo.
LOG_CHECK_EVERY = settings.log_check_every
# Quantas linhas do fim do log olhar em cada passada.
LOG_ERR_LINES = 200
# Teto de um alerta de log por servidor nesta janela. A expressao vem da tela e um '.'
# distraido casa com tudo — sem esta trava, um engano de digitacao vira uma enxurrada.
LOG_ERR_COOLDOWN = settings.log_err_cooldown


def config_get(conn: sqlite3.Connection, key: str, padrao: str = "") -> str:
    return settings_repo.get(conn, key, padrao)


def config_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        settings_repo.set_value(conn, key, value)


def clean_events(raw: str) -> set:
    """Filtra pela lista conhecida: evento que saiu do codigo nao volta pelo banco."""
    return {e for e in (raw or "").split(",") if e in ALERT_EVENTS}


def webhook_list(conn: sqlite3.Connection) -> list:
    """Todos os destinos, na ordem de cadastro, com os eventos ja como conjunto."""
    lines_of = alerts_repo.all_webhooks(conn)
    return [
        {
            "id": r["id"],
            "name": r["name"] or "Sem nome",
            "url": r["url"],
            "url_curta": mask_url(r["url"]),
            "events": clean_events(r["events"]),
            "enabled": bool(r["enabled"]),
        }
        for r in lines_of
    ]


def webhook_config(conn: sqlite3.Connection) -> dict:
    """Estado dos alertas: os destinos, o que o conjunto deles cobre, e o limite do disco.

    'eventos' e a UNIAO dos destinos ligados — e o que o monitor usa para decidir se vale
    a pena olhar alguma coisa. Quem recebe o que se resolve depois, destino a destino.
    """
    try:
        disk = int(config_get(conn, "webhook_disk_pct", str(DISK_PCT_DEFAULT)))
    except ValueError:
        disk = DISK_PCT_DEFAULT
    try:
        memory = int(config_get(conn, "webhook_mem_pct", str(MEM_PCT_DEFAULT)))
    except ValueError:
        memory = MEM_PCT_DEFAULT
    try:
        cpu = int(config_get(conn, "webhook_cpu_pct", str(CPU_PCT_DEFAULT)))
    except ValueError:
        cpu = CPU_PCT_DEFAULT
    targets = webhook_list(conn)
    covered = set()
    for d in targets:
        if d["enabled"] and d["url"]:
            covered |= d["events"]
    return {
        "targets": targets,
        "active": [d for d in targets if d["enabled"] and d["url"]],
        "events": covered,
        "disk": min(100, max(50, disk)),
        "memory": min(100, max(50, memory)),
        "cpu": min(100, max(50, cpu)),
    }


mask_url = webhook_client.mask_url


def send_webhook(url: str, text: str) -> str:
    # Nome proprio (e nao `webhook_client.envia` direto nas chamadas) porque a fixture
    # `webhooks` do conftest troca ESTE nome por um capturador — todo teste de alerta
    # depende disso para ver o que sairia por HTTP sem nada sair de verdade.
    return webhook_client.send(url, text, WEBHOOK_TIMEOUT, WEBHOOK_UA)


def notify(conn: sqlite3.Connection, event: str, title: str, detail: str = "") -> bool:
    """Manda o alerta para cada destino que pediu esse evento.

    Devolve se saiu para ALGUEM. Um destino fora do ar (Discord de pe, Slack caido) nao
    cala os outros: cada um e tentado e cada falha vai para o log com o nome do destino,
    entao da para saber qual deles esta quebrado sem adivinhar.
    """
    targets = [d for d in webhook_list(conn)
             if d["enabled"] and d["url"] and event in d["events"]]
    if not targets:
        # Registrado de proposito: "o alerta disparou e ninguem pediu por ele" e a causa
        # mais comum de canal mudo, e e indistinguivel de "nao aconteceu nada" para quem
        # so olha o Discord. No diario as duas viram coisas diferentes.
        _record_alert(conn, event, title, detail, "", "sem-destino")
        return False
    text = f"**{title}**"
    if detail:
        text += f"\n{detail}"
    left = False
    for target in targets:
        failure = send_webhook(target["url"], text)
        if failure:
            app.logger.warning(
                "alerta '%s' nao saiu para '%s': %s", event, target["name"], failure
            )
            _record_alert(conn, event, title, detail, target["name"],
                             "falhou", failure)
        else:
            left = True
            _record_alert(conn, event, title, detail, target["name"], "enviado")
    return left


def _record_alert(conn: sqlite3.Connection, event: str, title: str, detail: str,
                     target: str, status: str, error: str = "") -> None:
    """Grava uma linha do diario.

    Engole o proprio erro de proposito: o diario existe para explicar o alerta, e seria
    absurdo ele impedir o alerta de sair. No pior caso fica sem registro, nunca sem envio.
    """
    try:
        with conn:
            alerts_repo.log(conn, now_iso(), event, title, detail, target, status, error)
    except sqlite3.Error:
        app.logger.exception("nao consegui gravar no diario de alertas")


def recent_alerts(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    """As ultimas linhas do diario, da mais nova para a mais velha."""
    return [dict(l) for l in alerts_repo.recent(conn, limit)]


def _recent_job(conn: sqlite3.Connection, sid: int) -> bool:
    """Teve acao do painel neste servidor ha pouco?

    Reiniciar pelo botao derruba o servico por alguns segundos, e isso NAO e uma queda.
    Sem esta janela, todo restart e todo update viraria alerta.
    """
    cut = (datetime.now(timezone.utc) - timedelta(seconds=ALERT_QUIET)).isoformat()
    return jobs_repo.acted_since(conn, sid, cut)


# server_id -> ultimo estado visto. Fica so na memoria de proposito: reiniciar o painel
# refaz a linha de base, e ninguem recebe um alerta de algo que ja estava assim.
_monitor_state: dict[int, dict] = {}
# Um relogio por ritmo (ver `tasks/ticker.py`). Instancia e nao variavel solta porque o
# `conftest.py` precisa zerar todos entre um teste e o outro, e um `global` a mais e um
# nome a mais para ele errar em silencio.
monitor_tick = ticker.Ticker()
state_tick = ticker.Ticker()
resource_tick = ticker.Ticker()
log_tick = ticker.Ticker()


def _alert_deps() -> alert_service.AlertDeps:
    """As pecas que as regras de alerta pedem, montadas na hora da chamada.

    Na hora, e nao no import: `server_players`, `server_metrics` e `notifica` sao nomes
    deste modulo, e os testes de alerta trocam os dois primeiros por falsos a cada caso
    — um bundle congelado no import passaria por cima da troca em silencio.
    """
    return alert_service.AlertDeps(
        notify=notify, recent_job=_recent_job, player_source=player_source,
        server_players=server_players, server_metrics=server_metrics,
        read_log_lines=read_log_lines, stored_value=_stored_value,
        human_size=_human_size, monitor_state=_monitor_state,
        logger=app.logger, mute_rounds=MUTE_ROUNDS, log_err_lines=LOG_ERR_LINES,
        log_err_cooldown=LOG_ERR_COOLDOWN,
    )


def _state_alert(conn, server, state, anterior) -> None:
    alert_service.state_alert(_alert_deps(), conn, server, state, anterior)


def _restart_alert(conn, server, state, anterior) -> None:
    alert_service.restart_alert(_alert_deps(), conn, server, state, anterior)


def _mute_alert(conn, server, state, anterior) -> None:
    alert_service.mute_alert(_alert_deps(), conn, server, state, anterior)


def _log_alert(conn, server, anterior) -> None:
    alert_service.log_alert(_alert_deps(), conn, server, anterior)


def _disk_alert(conn, server, cfg) -> None:
    alert_service.disk_alert(_alert_deps(), conn, server, cfg)


def _memory_alert(conn, server, cfg) -> None:
    alert_service.memory_alert(_alert_deps(), conn, server, cfg)


def _cpu_alert(conn, server, cfg) -> None:
    alert_service.cpu_alert(_alert_deps(), conn, server, cfg)


# Evento de recurso -> quem confere. Os tres leem o MESMO medidor e andam no mesmo
# relogio; como tabela, ligar um quarto (rede, por exemplo) e acrescentar uma linha,
# nao mais um `if` dentro do laco do monitor.
#
# Aponta para as funcoes DESTE modulo, nao para as do service: a tabela captura o
# objeto no import, e e por estes nomes que os testes chamam.
RESOURCE_ALERTS = {
    "disco-cheio": _disk_alert,
    "memoria-alta": _memory_alert,
    "cpu-alta": _cpu_alert,
}


def _players_alert(conn, server, service, anterior, cfg) -> None:
    alert_service.players_alert(_alert_deps(), conn, server, service, anterior, cfg)


_players_reading = alert_service.players_reading
_online_text = alert_service.online_text


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
# MESMO _monitor_state[sid], e sem isto os dois poderiam avisar a mesma entrada.
_players_locks: dict[int, threading.Lock] = {}
_players_locks_lock = threading.Lock()


def players_lock(sid: int) -> threading.Lock:
    with _players_locks_lock:
        return _players_locks.setdefault(sid, threading.Lock())


def _log_stream_deps() -> log_stream.LogStreamDeps:
    return log_stream.LogStreamDeps(
        ssh_argv=ssh_argv, monitor_state=_monitor_state,
        invalidate_players=invalidate_players, connect=_connect,
        webhook_config=webhook_config, players_lock=players_lock,
        players_alert=_players_alert, logger=app.logger,
        debounce=LOG_STREAM_DEBOUNCE, retry=LOG_STREAM_RETRY,
    )


class _LogStream(log_stream.LogStream):
    """A conexao de log com as pecas do painel ja ligadas.

    Subclasse (e nao `functools.partial`) para continuar sendo uma CLASSE de dois
    argumentos: o supervisor a troca por um dublê nos testes, e ha teste que a constroi
    direto para conferir que um regex torto faz a thread desistir.
    """

    def __init__(self, server, signature):
        super().__init__(_log_stream_deps(), server, signature)


def _player_line(line: str, entrar, sair) -> bool:
    return log_stream.player_line(line, entrar, sair)


def _stream_signature(server) -> tuple:
    return log_stream.stream_signature(server, _stored_value)


def wanted_streams(servers, cfg) -> dict[int, tuple]:
    return log_stream.wanted_streams(
        servers, cfg, LOG_STREAM, player_source, _stored_value)


# `_LogStream` vai por lambda: o nome e resolvido neste modulo a cada abertura, que e o
# que deixa o teste do supervisor troca-lo por um dublê sem SSH.
_supervisor = log_stream.Supervisor(lambda server, signature: _LogStream(server, signature))
# O MESMO dicionario do supervisor: a fixture do teste o limpa por este nome.
_streams = _supervisor.open_ones


def live_streams() -> int:
    return _supervisor.alive_ids()


def supervise_streams() -> int:
    """Liga, desliga e ressuscita as conexoes de log. Devolve quantas ficaram registradas."""
    conn = db()
    servers = servers_repo.all_ordered(conn)
    return _supervisor.sync(servers, wanted_streams(servers, webhook_config(conn)))


class _Rhythm(NamedTuple):
    """O que ESTA volta do monitor vai conferir.

    Nem tudo anda no mesmo passo, e a razao e custo: a contagem de jogadores pergunta
    direto ao jogo (barato), estado/mudez/restart custam um SSH por servidor, disco,
    memoria e CPU saem de um medidor caro que vale ler junto, e o log custa uma ida de
    SSH so dele. Separar essa decisao do laco e o que fez a funcao de monitorar caber
    na cabeca: aqui e "o que vence agora", la e "o que fazer com cada servidor".
    """

    see_state: bool
    wants_players: bool
    resources: set
    see_log: bool


def _monitor_rhythm(cfg: dict, now: float, force: bool) -> _Rhythm | None:
    """Decide o que vence nesta volta e adianta os relogios. None = ainda nao e hora."""
    # O passo do monitor e o do alerta mais apressado que esteja LIGADO. Com jogadores
    # ligados a volta fica curta; sem eles nada muda em relacao a antes.
    wants_players = bool(cfg["events"] & {"jogador-entrou", "jogador-saiu"})
    step = min(MONITOR_EVERY, PLAYER_CHECK_EVERY) if wants_players else MONITOR_EVERY
    if not monitor_tick.due(now, step, force):
        return None
    monitor_tick.mark(now)

    # ...mas so a contagem de jogadores anda nesse passo curto. Estado do servico, mudez
    # e restart continuam no ritmo antigo: cada um deles custa SSH por servidor, e
    # acelerar tudo junto multiplicaria essa conta por quatro sem necessidade.
    see_state = state_tick.due(now, MONITOR_EVERY, force)
    if see_state:
        state_tick.mark(now)

    # Um relogio so para disco, memoria e CPU: os tres leem o mesmo medidor, e dar um
    # ritmo proprio a cada um multiplicaria as idas de SSH sem enxergar nada novo.
    resource_wins = resource_tick.due(now, DISK_CHECK_EVERY, force)
    resources = cfg["events"] & RESOURCE_EVENTS if resource_wins else set()
    # Anota so quando ALGO foi lido: sem alerta de recurso ligado, deixar a janela correr
    # faria a proxima volta com um deles ligado esperar o intervalo inteiro de novo.
    if resources:
        resource_tick.mark(now)

    # O log e o unico que custa uma ida de SSH so dele, entao anda no seu proprio ritmo.
    see_log = "erro-no-log" in cfg["events"] and log_tick.due(now, LOG_CHECK_EVERY, force)
    if see_log:
        log_tick.mark(now)

    return _Rhythm(see_state, wants_players, resources, see_log)


def _short_round(conn, server, anterior, cfg, rhythm: _Rhythm) -> None:
    """A volta de 15s: so jogadores, e sem tocar no SSH.

    O servico que interessa aqui e "estava de pe na ultima olhada de verdade", e isso
    ja esta guardado. Se ele tiver caido desde entao, a consulta ao proprio jogo falha
    e `_alerta_de_jogadores` sai sem avisar nada — o atraso de um estado velho nao
    inventa alerta.

    Contagem por log fica de fora: ela custa SSH, e pagar isso a cada 15s so para reler
    o mesmo log inteiro nao se sustenta. Esses servers continuam avisando no ritmo
    da volta completa.
    """
    if not rhythm.wants_players or anterior is None:
        return
    if player_source(server) not in PLAYER_FAST_SOURCES:
        return
    with players_lock(int(server["id"])):
        _players_alert(conn, server, anterior.get("service", ""), anterior, cfg)


def _server_alerts(conn, server, state, anterior, cfg, rhythm: _Rhythm) -> None:
    """Os alertas que so fazem sentido com o container ALCANCAVEL."""
    if "reiniciando" in cfg["events"]:
        _restart_alert(conn, server, state, anterior)
    else:
        # Sem o evento ligado o contador ainda precisa acompanhar, senao ligar o alerta
        # no meio do dia renderia um "loop" falso com tudo o que se acumulou enquanto
        # ele estava desligado.
        anterior["restarts"] = int(state.get("restarts") or 0)

    # Este custa uma sondagem no jogo (UDP ou HTTP) — nao vale a pena pagar por ela com
    # o evento desligado.
    if cfg["events"] & {"travou", "respondeu"}:
        _mute_alert(conn, server, state, anterior)

    if rhythm.wants_players:
        # Com stream de log ligado esta chamada vira rede de seguranca: se ele tiver
        # caido, ninguem fica sem aviso — so mais devagar. O lock e o que impede os dois
        # de avisarem a mesma entrada.
        with players_lock(int(server["id"])):
            _players_alert(conn, server, state["service"], anterior, cfg)

    if rhythm.see_log:
        _log_alert(conn, server, anterior)

    for event, check_it in RESOURCE_ALERTS.items():
        if event in rhythm.resources:
            check_it(conn, server, cfg)


def monitor_servers(force: bool = False) -> int:
    """Confere o estado de todo mundo e dispara o que mudou. Devolve quantos olhou."""
    conn = db()
    cfg = webhook_config(conn)
    # Sem nenhum destino ligado pedindo algum evento, a volta inteira seria SSH gasto
    # para produzir um alerta que ninguem receberia.
    if not cfg["events"]:
        return 0

    rhythm = _monitor_rhythm(cfg, time.monotonic(), force)
    if rhythm is None:
        return 0

    servers = servers_repo.all_ordered(conn)
    for server in servers:
        sid = int(server["id"])
        previous = _monitor_state.get(sid)

        if not rhythm.see_state:
            _short_round(conn, server, previous, cfg, rhythm)
            continue

        state = server_status(server)
        if previous is None:
            # Primeira olhada: so anota. Alertar aqui encheria o canal de "esta parado"
            # toda vez que o painel reiniciasse. Vale para o contador de restarts do
            # mesmo jeito: o que interessa e quanto ele sobe DAQUI para a frente.
            _monitor_state[sid] = {"reachable": state["reachable"],
                                    "service": state["service"],
                                    "restarts": int(state.get("restarts") or 0)}
            continue

        _state_alert(conn, server, state, previous)
        if state["reachable"]:
            _server_alerts(conn, server, state, previous, cfg, rhythm)
        # Depois dos alertas: eles precisam comparar com o estado ANTERIOR, e atualizar
        # antes faria toda mudanca desaparecer no meio do caminho.
        previous.update(reachable=state["reachable"], service=state["service"])

    _forget_removed_servers(servers)
    return len(servers)


def _forget_removed_servers(servers) -> None:
    """Servidor removido do painel nao pode ficar guardando estado para sempre."""
    alive_ids = {int(s["id"]) for s in servers}
    for dead_one in [k for k in _monitor_state if k not in alive_ids]:
        _monitor_state.pop(dead_one, None)


# -------------------------------------------------------- amostras de uso

sample_tick = ticker.Ticker()


def collect_samples(force: bool = False) -> int:
    """Guarda uma linha de CPU/memoria/jogadores por servidor. Devolve quantas gravou."""
    now_ts = time.monotonic()
    if not sample_tick.due(now_ts, SAMPLE_EVERY, force):
        return 0
    sample_tick.mark(now_ts)

    conn = db()
    stamp = now_iso()
    lines_of = []
    for server in servers_repo.all_ordered(conn):
        data = server_metrics(server)
        if data.get("error"):
            # Container fora do ar nao vira linha: um buraco no grafico e a informacao
            # certa, e zero seria mentira (nao foi "usou 0% de CPU").
            continue
        count = None
        if player_source(server):
            try:
                playing = server_players(server)
                count = None if playing.get("error") else playing.get("players")
            except (QueryError, RemoteError):
                count = None
        lines_of.append((
            int(server["id"]), stamp, data.get("cpu_pct"),
            (data.get("mem") or {}).get("pct"), count,
        ))

    if lines_of:
        with conn:
            samples_repo.insert_many(conn, lines_of)
    return len(lines_of)


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
WEEKDAYS = schedule_service.WEEKDAYS
EVERY_HOURS_MAX = schedule_service.EVERY_HOURS_MAX
local_now = schedule_service.local_now
schedule_label = schedule_service.schedule_label
previous_occurrence = schedule_service.previous_occurrence
# Usado tambem pelas rotas de agendamento e pelo grafico, fora desta secao.
_parse_dt = schedule_service._parse_dt


def is_due(sched, now: datetime) -> bool:
    return schedule_service.is_due(sched, now, SCHEDULE_GRACE)


def fire_schedule(conn: sqlite3.Connection, sched) -> int:
    """Coloca a tarefa para rodar. Devolve o id do job (0 quando nao deu para disparar)."""
    server = servers_repo.by_id(conn, sched["server_id"])
    if not server:
        return 0
    if sched["action"] == "backup":
        paths = backup_paths(server)
        if not paths:
            return 0  # sem o que guardar: nao adianta acordar o container
        remote, limit = backup_command(server, paths), BACKUP_TIMEOUT
    else:
        remote, limit = ACTIONS[sched["action"]][1](server), JOB_TIMEOUT
    job_id = start_job(
        sched["action"], server, SCHEDULE_USER, remote_cmd=remote,
        command=f"agendado: {schedule_label(sched)}", timeout=limit,
    )
    invalidate_status(int(server["id"]))
    return job_id


def run_schedules() -> int:
    """Uma passada do relogio. Devolve quantas tarefas disparou."""
    now_ts = local_now()
    conn = db()
    fired = 0
    for sched in schedules_repo.enabled(conn):
        if sched["action"] not in SCHEDULE_ACTIONS or not is_due(sched, now_ts):
            continue
        # Marca ANTES de disparar: se o job demorar (um update leva quase uma hora), a
        # proxima volta do relogio nao pode achar que a tarefa ainda esta vencida.
        with conn:
            schedules_repo.mark_run(conn, sched["id"], now_ts.isoformat())
        if fire_schedule(conn, sched):
            fired += 1
    return fired


cleanup_tick = ticker.Ticker()


def clean_history(force: bool = False) -> int:
    """Apaga o que envelheceu — jobs e amostras. Devolve quantos JOBS sairam.

    As duas limpezas andam juntas porque tem a mesma razao de existir (o banco do painel
    nao pode crescer para sempre) e o mesmo relogio de hora em hora; so os prazos mudam,
    porque uma amostra e minuscula perto da saida de um job.
    """
    now_ts = time.monotonic()
    if not cleanup_tick.due(now_ts, JOBS_PURGE_EVERY, force):
        return 0
    cleanup_tick.mark(now_ts)
    conn = db()

    if SAMPLES_KEEP_DAYS:
        old_ones = (datetime.now(timezone.utc)
                  - timedelta(days=SAMPLES_KEEP_DAYS)).isoformat()
        with conn:
            samples_repo.delete_older_than(conn, old_ones)

    # O diario se mede em linhas, nao em dias: o que se quer dele e "as ultimas N", e um
    # prazo em dias deixaria a tela vazia justo num painel quieto, que e quando a duvida
    # "sera que isso ainda funciona?" aparece.
    with conn:
        alerts_repo.trim_log(conn, ALERT_LOG_KEEP)

    if not JOBS_KEEP_DAYS:
        return 0
    cut = (datetime.now(timezone.utc) - timedelta(days=JOBS_KEEP_DAYS)).isoformat()
    with conn:
        return jobs_repo.delete_older_than(conn, cut)


def _clock_failure(name: str) -> None:
    """Anota no log do processo E no diario de alertas.

    O diario e o que a pessoa consegue ver: o traceback no stderr do gunicorn so aparece
    para quem sabe procurar, e a queixa que traz alguem ate aqui e sempre a mesma — "nao
    chega nada no Discord".
    """
    app.logger.exception("falha na tarefa '%s' do relogio", name)
    try:
        _record_alert(db(), "", f"a tarefa '{name}' do relogio falhou",
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
        (("agendamentos", run_schedules),
         ("monitor", monitor_servers),
         ("log-em-tempo-real", supervise_streams),
         ("amostras", collect_samples),
         ("limpeza", clean_history)),
        _clock_failure,
    )


def _with_context() -> None:
    # Contexto de aplicacao: e o que faz o db() desta thread funcionar como o das rotas
    # (conexao propria, fechada no fim pelo teardown).
    with app.app_context():
        _scheduler_tick()


_clock = scheduler.Clock(SCHEDULE_TICK, _with_context, app.logger)


def start_scheduler() -> None:
    _clock.start()


# ------------------------------------------------------------------- rotas


def safe_target(raw: str) -> str:
    r"""Para onde voltar depois do login. Vazio quando o destino nao e do painel.

    Comecar com "/" nao basta: para o navegador "//evil.com" e "/\evil.com" sao enderecos
    ABSOLUTOS, e mandariam quem acabou de digitar a senha para fora do painel.
    """
    target = (raw or "").strip()
    if not target.startswith("/") or target[:2] in ("//", "/\\"):
        return ""
    if any(c in target for c in "\r\n\t"):
        return ""
    return target


# Tempo para digitar o codigo depois de acertar a senha.
PRE_2FA_SECONDS = 300


def _open_session(row: sqlite3.Row, next_one: str = ""):
    session.clear()
    session["uid"] = row["id"]
    session["username"] = row["username"]
    session.permanent = True
    csrf_token()
    return redirect(next_one or url_for("dashboard.index"))


def _check_second_factor(row: sqlite3.Row, typed: str) -> bool:
    """Codigo do aplicativo OU um codigo de recuperacao (que se gasta). Vale so uma vez."""
    conn = db()
    step = totp.verify(row["totp_secret"], typed, time.time(), row["totp_last_step"])
    if step is not None:
        with conn:
            # O `WHERE` faz do UPDATE o portao: dois pedidos com o mesmo codigo ao mesmo tempo
            # nao passam os dois (o segundo nao encontra a linha com passo menor).
            return users_repo.spend_step(conn, row["id"], step)
    try:
        stored = json.loads(row["totp_recovery"] or "[]")
    except ValueError:
        stored = []
    leftover = totp.consume(typed, stored)
    if leftover is None:
        return False
    with conn:
        return users_repo.spend_recovery(
            conn, row["id"], json.dumps(leftover), row["totp_recovery"])


def _port_tab(server: ServerRow) -> dict:
    """Aba 1: dispara A2S em cada porta UDP que o container esta escutando."""
    candidates, _tcp, owners, warning_text = candidate_ports(server)
    ports = _with_owner(probe_ports(server["host"], candidates[:12]), owners, "udp")
    # Porta aberta pelo processo do jogo e que nao respondeu A2S e uma conclusao, nao um
    # erro: o jogo simplesmente nao publica consulta. Sem essa contagem a tela so diria
    # "sem resposta" e deixaria a duvida entre "porta errada" e "nao existe consulta".
    from_game = [p for p in ports if p["origem"] == "detectada" and not p["infra"]]
    return {
        "portas": ports,
        "aviso": warning_text,
        "udp_do_jogo": len(from_game),
        "udp_mudas": bool(from_game) and not any(p["ok"] for p in from_game),
    }


def _http_tab(server: ServerRow, http: dict, should_test: bool) -> dict:
    """Aba 2: quais portas TCP falam HTTP, e o teste da URL escolhida."""
    _udp, candidates, owners, warning_text = candidate_ports(server)
    found, silent_ones, probe_failure = probe_http_ports(server, candidates)
    _with_owner(found, owners, "tcp")
    silent_ones = _with_owner([{"port": p} for p in silent_ones], owners, "tcp")
    output = {"achados": found, "mudas": silent_ones, "aviso": warning_text or probe_failure,
             # Achado que vale um clique: porta que respondeu numa rota conhecida. Sem
             # nenhum, a tela explica que a API costuma vir desligada de fabrica.
             "tem_api": any(not a.get("generico") for a in found),
             "teste_http": None, "erro_http": ""}
    if not should_test:
        return output
    try:
        # O teste usa os valores do FORMULARIO, nao os do banco: e o unico jeito de
        # conferir o login antes de salvar. Por isso monta-se uma linha temporaria.
        temporary_path = dict(server)
        temporary_path.update(http)
        if (http.get("http_login_url") or "").strip() and (http.get("http_token_path") or "").strip():
            token = http_login(temporary_path)
            auth = f"bearer:{token}"
        else:
            auth = http["http_auth"]
        data = http_json(server, http["http_url"], auth, http["http_body"])
        test_value = read_players_json(data, http["http_list_path"], http["http_count_path"])
        # A resposta crua ajuda a preencher os caminhos quando a busca automatica erra.
        test_value["amostra"] = json.dumps(data, indent=2, ensure_ascii=False)[:4000]
        output["teste_http"] = test_value
    except QueryError as exc:
        output["erro_http"] = str(exc)
    return output


def _log_tab(server: ServerRow, join_re: str, leave_re: str, log_path: str,
             should_test: bool) -> dict:
    """Aba 3: linhas do log com cara de entrada/saida e o teste dos padroes."""
    output = {"amostras": [], "teste": None, "erro_log": ""}
    try:
        # O caminho vem do FORMULARIO, nao do banco: e o unico jeito de conferir um
        # arquivo novo (o .ADM do DayZ, por exemplo) antes de salvar.
        temporary_path = dict(server)
        temporary_path["log_path"] = log_path
        lines_of = read_log_lines(temporary_path)
        keys = re.compile("|".join(LOG_HINT_WORDS), re.I)
        samples = [ln for ln in lines_of if keys.search(ln)][-120:]
        output["amostras"] = samples
        if not should_test:
            return output
        join_pattern = compile_pattern(join_re, "pattern.join")
        if not join_pattern:
            raise QueryError("informe o padrao da linha de entrada")
        leave_pattern = compile_pattern(leave_re, "pattern.leave")
        test_value = _apply_log_events(lines_of, join_pattern, leave_pattern)
        test_value["casaram"] = [
            ln for ln in samples
            if join_pattern.search(ln[:LOG_LINE_MAX]) or (leave_pattern and leave_pattern.search(ln[:LOG_LINE_MAX]))
        ][-20:]
        output["teste"] = test_value
    except (RemoteError, QueryError) as exc:
        output["erro_log"] = str(exc)
    return output


def _enable_a2s_count(conn, sid: int):
    """Consulta UDP direta (A2S). Devolve um redirect quando o formulario esta errado."""
    port = request.form.get("query_port", "0")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        flash(translate("flash.bad_port"), "error")
        return redirect(url_for("players.setup", sid=sid))
    with conn:
        servers_repo.use_query_port(conn, sid, int(port))
    flash(translate("flash.count_on_by_query", port=port), "ok")
    return None


def _enable_http_count(conn, sid: int):
    """API HTTP do proprio jogo."""
    errors: list[str] = []
    fields = _http_fields(request.form, errors)
    if errors or not fields["http_url"]:
        flash(translate(errors[0]) if errors else translate("flash.need_api_url"), "error")
        return redirect(url_for("players.setup", sid=sid, aba="http"))
    with conn:
        servers_repo.use_http(conn, sid, fields)
    if fields["http_login_url"]:
        flash(translate("flash.count_on_by_api_login"), "ok")
    else:
        flash(translate("flash.count_on_by_api"), "ok")
    return None


def _enable_log_count(conn, sid: int):
    """Ultimo recurso: as linhas de entrada e saida no log do servidor."""
    errors: list[str] = []
    entry = _pattern(request.form.get("join_re"), "entrada", errors)
    output = _pattern(request.form.get("leave_re"), "saida", errors)
    path = _log_path(request.form.get("log_path"), errors)
    if errors or not entry:
        flash(translate(errors[0]) if errors else translate("flash.need_join_pattern"), "error")
        return redirect(url_for("players.setup", sid=sid, aba="log"))
    with conn:
        servers_repo.use_log(conn, sid, entry, output, path)
    flash(translate("flash.count_on_by_log"), "ok")
    return None


# Fonte de contagem -> quem grava a escolha. Uma fonte nova (RCON, por exemplo) e uma
# funcao e uma linha aqui; a rota abaixo nao muda.
COUNT_SOURCES = {
    "a2s": _enable_a2s_count,
    "http": _enable_http_count,
    "log": _enable_log_count,
}


# Validacao do formulario em gamepanel.services.server_service. Os limites ficam aqui
# (sao configuracao do painel) e viajam num bundle; `clean_path` vai junto porque ja
# carrega as raizes permitidas (GAMEPANEL_FILE_ROOTS).
UNIT_RE = server_service.UNIT_RE
HOST_RE = server_service.HOST_RE
USER_RE = server_service.USER_RE
JSON_PATH_RE = server_service.JSON_PATH_RE


def _form_limits() -> server_service.FormLimits:
    return server_service.FormLimits(
        config_files_max=CONFIG_FILES_MAX, backup_paths_max=BACKUP_PATHS_MAX,
        http_url_max=HTTP_URL_MAX, http_body_max=HTTP_BODY_MAX,
        http_path_max=HTTP_PATH_MAX, re_max_len=RE_MAX_LEN,
        player_sources=PLAYER_SOURCES,
    )


def _form_server(form) -> tuple[dict, list[str]]:
    return server_service.form_server(form, clean_path, _form_limits())


# Os tres tambem sao usados pelo assistente de contagem (abas HTTP e log), fora do
# formulario de cadastro.
_log_path = server_service._log_path


def _pattern(value: str | None, label: str, errors: list[str]) -> str:
    return server_service._pattern(value, label, RE_MAX_LEN, errors)


def _http_fields(form, errors: list[str]) -> dict:
    return server_service._http_fields(form, _form_limits(), errors)


# Colunas que o formulario preenche, na mesma ordem do INSERT/UPDATE abaixo. Manter a
# lista em um lugar so evita o classico "acrescentei a coluna e esqueci de um dos SQLs".
# O nome das colunas mora no repositorio; aqui fica so o apelido que os blueprints
# ja usavam (a troca por `panel.X` e o que faz o `monkeypatch` dos testes valer).
SERVER_FIELDS = servers_repo.EDITABLE_FIELDS


# O cursor e uma chave opaca do journald ("s=...;i=...;b=..."): validada aqui porque
# volta do navegador e entra num comando remoto.
CURSOR_RE = re.compile(r"^[A-Za-z0-9=;:._-]{1,400}$")
LOG_FOLLOW_MAX = 500


def _log_lines_arg(raw: str | None, default: int = 80) -> int:
    try:
        return max(10, min(500, int(raw or "")))
    except (TypeError, ValueError):
        return default


def read_logs(server: ServerRow, lines: int, cursor: str = "") -> tuple[str, str]:
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


# ------------------------------------------------------------------ console


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
            open_ones = tuple(_terms.values())
        for term in open_ones:
            idle = now - term.last_seen
            # Sessao encerrada fica um pouco no ar para o navegador ler a saida final.
            if idle > TERM_IDLE_TIMEOUT or (not term.alive and idle > 60):
                term.close()
                with _terms_lock:
                    _terms.pop(term.id, None)


def _ensure_reaper() -> None:
    """Liga o coletor de sessoes ociosas na primeira vez que alguem abre um terminal.

    A trava de "so uma vez" mora aqui, e nao no blueprint, porque `_reaper_started` e
    `_terms_lock` sao do mesmo estado: um `global` do outro lado do pacote leria a copia
    do modulo do blueprint e ligaria uma thread nova a cada aba aberta. Quem chama ja
    esta com `_terms_lock` na mao.
    """
    global _reaper_started
    if not _reaper_started:
        threading.Thread(target=_reap_terms, daemon=True).start()
        _reaper_started = True


def _term_of_user(tid: str) -> TermSession:
    if not TERM_ID_RE.match(tid or ""):
        abort(404)
    with _terms_lock:
        term = _terms.get(tid)
    # Sessao de outro usuario e tratada como inexistente.
    if not term or term.uid != session.get("uid"):
        abort(404, i18n.Message("error.terminal_session_gone"))
    term.last_seen = time.time()
    return term


def _terminal_guard():
    if not ALLOW_SHELL:
        abort(403, i18n.Message("error.terminal_disabled"))
    if not HAVE_PTY:
        abort(503, i18n.Message("error.terminal_no_pty"))


# ------------------------------------------------- editor de configuracoes


def clean_path(raw: str) -> str:
    return files_rt.clean_path(raw, FILE_ROOTS)


def parent_of(path: str) -> str:
    return files_rt.parent_of(path)


@app.template_filter("level")
def _bar_level(pct: float | None) -> str:
    """Classe da barra: perto do teto ela muda de cor (mesma regra do metrics.js)."""
    if pct is None:
        return ""
    if pct >= 92:
        return " hot"
    if pct >= 80:
        return " warn"
    return ""


@app.template_filter("duration")
def _human_uptime(seconds: float | None) -> str:
    total = int(seconds or 0)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}min"
    if minutes:
        return f"{minutes}min"
    # Jogador que acabou de entrar: "0min" nao diz nada.
    return f"{total}s"


@app.template_filter("filesize")
def _human_size(num: int | None) -> str:
    """1536 -> '1.5 KB'. Um save de jogo em bytes crus nao diz nada para ninguem."""
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _files_guard():
    if not ALLOW_FILES:
        abort(403, i18n.Message("error.files_disabled"))


def _server_or_404(sid: int) -> sqlite3.Row:
    server = servers_repo.by_id(db(), sid)
    if not server:
        abort(404)
    return server


def list_dir(server: ServerRow, path: str) -> tuple[list[dict], bool]:
    return files_rt.list_dir(ssh_run, server, path, FILE_LIST_MAX)


def stat_file(server: ServerRow, path: str) -> dict:
    return files_rt.stat_file(ssh_run, server, path)


def read_file(server: ServerRow, path: str) -> dict:
    return files_rt.read_file(ssh_run, server, path, FILE_MAX_BYTES, FILE_PREVIEW_BYTES)


RESTORE_SCRIPT = backups_rt.RESTORE_SCRIPT

# $1 = destino final. O conteudo vem CRU pela entrada padrao (sem base64: o arquivo pode
# ter gigabytes, e codificar inflaria 33% a toa).
UPLOAD_SCRIPT = files_rt.UPLOAD_SCRIPT


def ssh_stream_in(server, remote_cmd: str, source, timeout: int) -> str:
    return files_rt.ssh_stream_in(ssh_argv, server, remote_cmd, source, timeout, UPLOAD_CHUNK)


def find_config_files(server: ServerRow, root: str) -> list[dict]:
    return files_rt.find_config_files(ssh_run, server, root, CONFIG_GLOBS)


def write_file(server: ServerRow, path: str, data: bytes) -> str:
    return files_rt.write_file(ssh_run, server, path, data)


def delete_file(server: ServerRow, path: str) -> str:
    return files_rt.delete_file(ssh_run, server, path)


def _attachment_header(name: str) -> str:
    """Content-Disposition que aguenta acento e aspas no nome do arquivo."""
    ascii_name = re.sub(r'[^A-Za-z0-9._-]', "_", name) or "arquivo"
    quoted = urllib.parse.quote(name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def stream_remote_file(server: ServerRow, path: str):
    return files_rt.stream_remote_file(ssh_argv, server, path, DOWNLOAD_CHUNK)


# ------------------------------------------------------------------ upload


# ------------------------------------------------------------------ backup
#
# O backup mora DENTRO do container do jogo, nao no painel: e um tar.gz das pastas que
# valem a pena guardar (o save, e a configuracao junto). O painel dispara, lista, baixa e
# restaura — e a restauracao para o servidor, extrai e religa, porque o jogo com o mundo
# trocado embaixo dele grava por cima do que acabou de voltar.


def backup_paths(server: ServerRow) -> list[str]:
    return backups_rt.backup_paths(server, BACKUP_PATHS_MAX)


def backup_prefix(server: ServerRow) -> str:
    return backups_rt.backup_prefix(server)


def _backup_or_400(name: str) -> str:
    """Confere o nome que voltou da tela antes de ele entrar num comando remoto."""
    try:
        return backups_rt.validate_backup_name(name)
    except ValueError as exc:
        abort(400, str(exc))


def list_backups(server: ServerRow) -> list[dict]:
    return backups_rt.list_backups(ssh_run, server, BACKUP_DIR, BACKUP_LIST_MAX)


def backup_command(server: ServerRow, paths: list[str], suffix: str = "") -> str:
    return backups_rt.backup_command(server, BACKUP_DIR, BACKUP_KEEP, paths, suffix)


def delete_backup(server: ServerRow, name: str) -> str:
    return backups_rt.delete_backup(ssh_run, server, BACKUP_DIR, name)


# ------------------------------------------------- edicao rapida de config
#
# Mesmo motor de leitura/gravacao da tela "Arquivos", so que o arquivo chega na tela
# como formulario: um campo por chave. Quem sabe o que quer mudar (nome do servidor,
# senha de admin, numero de jogadores) nao precisa achar o arquivo nem contar virgula.


def config_paths(server: ServerRow) -> list[str]:
    """Arquivos de configuracao registrados no cadastro do servidor."""
    return [line.strip() for line in (server["config_files"] or "").splitlines() if line.strip()]


def load_config_doc(server: ServerRow, path: str) -> tuple[gameconf.ConfigFile, dict]:
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


def _save_config_files(sid: int, paths: list[str]) -> None:
    conn = db()
    with conn:
        servers_repo.set_config_files(conn, sid, paths)


def _target_config(arquivos: list[str], errors: list[str]) -> str:
    """Qual arquivo a tela Config abre: o pedido na URL, ou o primeiro registrado."""
    request_body = (request.args.get("file") or "").strip()
    if not request_body:
        return arquivos[0] if arquivos else ""
    try:
        target = clean_path(request_body)
    except ValueError as exc:
        errors.append(str(exc))
        return arquivos[0] if arquivos else ""
    # O caminho vem da URL: sem esta trava a tela Config seria um leitor de arquivo
    # qualquer do container (como root), justo o que o operador nao tem permissao de
    # abrir. Para ele valem so os arquivos que um admin ja registrou no servidor.
    if target not in arquivos and not is_admin():
        abort(403, i18n.Message("error.operator_reads_registered_only"))
    return target


def _suggestion_config(server: ServerRow, arquivos: list[str], alvo: str,
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
    fallback = server["config_path"] or FILE_DEFAULT_PATH
    try:
        root = clean_path(request.args.get("pasta", "") or fallback)
    except ValueError as exc:
        errors.append(str(exc))
        root = fallback
    try:
        return find_config_files(server, root)
    except RemoteError as exc:
        errors.append(str(exc))
        return []


@app.template_filter("ident")
def _ident(value: str) -> str:
    """Identificador de secao/chave dentro do formulario.

    Os ids do gameconf usam \\x1f para separar niveis; percent-encoded eles atravessam
    o HTML sem virar caractere de controle solto no meio de um atributo.
    """
    return urllib.parse.quote(value or "", safe="")


def enrich_settings(doc: gameconf.ConfigFile, file_name: str) -> None:
    """Anexa a descricao do catalogo a cada campo lido do arquivo.

    Campo sem entrada no catalogo fica exatamente como antes (texto livre): o objetivo
    e melhorar o que da para melhorar, nunca esconder chave que o jogo passou a usar.
    """
    for section in doc.sections:
        for s in section.settings:
            spec = game_fields.describe(file_name, s.key)
            s.spec = spec
            s.display_value = spec.to_display(s.value) if spec else s.value


def _edits_from_form(form, file_name: str = "") -> tuple[list[gameconf.Edit], list[str]]:
    """Monta a lista de alteracoes: so o que o usuario realmente mexeu.

    Devolve tambem os erros de validacao. O valor chega na unidade da TELA (minutos,
    multiplicador) e e convertido para a unidade do ARQUIVO (nanossegundos) aqui - por
    isso a conferencia acontece antes da conversao, para a mensagem falar a lingua de
    quem digitou.
    """
    total = form.get("n", "0")
    total = int(total) if total.isdigit() else 0
    edits: list[gameconf.Edit] = []
    failures: list[str] = []
    for i in range(min(total, 4000)):
        edit = _edit_from_row(form, i, file_name, failures)
        if edit is not None:
            edits.append(edit)
    return edits, failures


def _edit_from_row(form, i: int, file_name: str, errors: list[str]) -> gameconf.Edit | None:
    """Uma linha do formulario vira uma alteracao — ou nada.

    Nada acontece em tres casos: linha de "adicionar configuracao" deixada em branco,
    campo que ninguem tocou (comparado com o `orig.N` escondido) e valor que o catalogo
    recusou. Os tres estao aqui juntos porque sao a mesma pergunta: "esta linha tem algo
    para gravar?".
    """
    key = (form.get(f"key.{i}", "") or "").strip()
    if not key:
        return None

    value = (form.get(f"val.{i}", "") or "").replace("\r", "")
    ident = urllib.parse.unquote((form.get(f"id.{i}", "") or "").strip())
    if ident and value == (form.get(f"orig.{i}", "") or "").replace("\r", ""):
        return None  # campo intocado: nao reescreve a linha

    spec = game_fields.describe(file_name, key) if file_name else None
    if spec:
        problem = spec.validate(value)
        if problem:
            errors.append(f"{spec.label or key}: {problem}")
            return None
        value = spec.from_display(value)

    return gameconf.Edit(
        id=ident,
        section=urllib.parse.unquote(form.get(f"sec.{i}", "") or ""),
        key=key,
        value=value,
    )


# --------------------------------------------------------------------- jobs


# ------------------------------------------------------------------- broker
#
# Criar instancia de jogo e abrir porta no firewall. Quem tem as credenciais de Proxmox e
# OPNsense e o broker (broker/); aqui o painel so PEDE, acompanha e cadastra o resultado.

# Formulario de jogo novo em gamepanel.services.broker_service; acompanhamento da
# operacao em gamepanel.tasks.broker_jobs.
BROKER_RECIPES = broker_service.BROKER_RECIPES


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
            abort(403, i18n.Message("error.broker_disabled"))
        user = logged_user()
        if not user or not user["totp_enabled"]:
            if request.path.startswith("/api/"):
                return jsonify({"error": "ative a verificacao em duas etapas em Conta para "
                                         "usar o broker"}), 403
            flash(translate("flash.broker_needs_two_factor"), "error")
            return redirect(url_for("account.two_factor"))
        return view(*args, **kwargs)

    return wrapper


def _fire(task) -> None:
    """Roda `tarefa` numa thread. Existe para os testes trocarem por uma execucao direta."""
    threading.Thread(target=task, daemon=True).start()


def _update_job(job_id: int, **fields) -> None:
    # Conexao propria: quem chama esta vivo numa thread fora do contexto do request. Os
    # NOMES das colunas vem dos chamadores (fixos); so os valores viajam como parametro.
    conn = _connect()
    try:
        with conn:
            jobs_repo.set_fields(conn, job_id, fields)
    finally:
        conn.close()


def _finish_job(job_id: int, status: str, output: str, exit_code: int | None = None,
               server_id: int | None = None) -> None:
    fields: dict = {"status": status, "exit_code": exit_code, "output": output.strip()[-200000:],
                    "finished_at": now_iso()}
    if server_id is not None:
        fields["server_id"] = server_id
    _update_job(job_id, **fields)


def _broker_job_deps() -> broker_jobs.BrokerJobDeps:
    """Montado na chamada: `BROKER_POLL` e `BROKER_FAILURES_MAX` sao trocados pelos testes
    antes de acompanhar a operacao, e um bundle congelado no import nao veria a troca."""
    return broker_jobs.BrokerJobDeps(
        update_job=_update_job, close_job=_finish_job, ensure_server=ensure_server,
        deploy_server=DeployServer, connect=_connect, poll=BROKER_POLL,
        max_failures=BROKER_FAILURES_MAX, timeout=JOB_TIMEOUT,
    )


def _register_broker_server(r: dict) -> int:
    return broker_jobs.register_server(_broker_job_deps(), r)


def follow_operation(job_id: int, op_id: str, sleep=time.sleep) -> None:
    broker_jobs.follow_operation(_broker_job_deps(), job_id, op_id, sleep)


def start_broker_job(action: str, username: str, op_id: str, command: str) -> int:
    conn = db()
    with conn:
        job_id = jobs_repo.start_broker(conn, action, command, username, now_iso(), op_id)
    _fire(lambda: follow_operation(job_id, op_id))
    return job_id


def resume_broker_jobs() -> int:
    """Depois de um restart do painel, volta a acompanhar as operacoes que ainda estavam
    rodando no broker. Sem isto o job ficaria 'running' para sempre, e o servidor recem
    criado nunca seria cadastrado."""
    if not ALLOW_BROKER:
        return 0
    conn = _connect()
    try:
        pending_ones = jobs_repo.running_broker_ops(conn)
    finally:
        conn.close()
    for job in pending_ones:
        _fire(lambda jid=job["id"], op=job["broker_op"]: follow_operation(jid, op))
    return len(pending_ones)


def _log_broker_action(action: str, username: str, command: str, output: str,
                             status: str = "ok") -> int:
    """Deixa no historico uma acao curta do broker (desativar, remover, jogo novo)."""
    conn = db()
    with conn:
        return jobs_repo.record_broker(
            conn, action, status, output, command, username, now_iso())


def _actor() -> str:
    return session.get("username", "")


_game_from_form = broker_service.game_from_form


# ------------------------------------------------------------- agendamentos


def _bounded_int(value, minimum: int, maximum: int, default: int) -> int:
    raw = (value or "").strip()
    if raw.lstrip("-").isdigit() and minimum <= int(raw) <= maximum:
        return int(raw)
    return default


def _schedule_form(form, errors: list[str]) -> dict:
    action = (form.get("action", "") or "").strip()
    if action not in SCHEDULE_ACTIONS:
        errors.append(i18n.Message("flash.schedule_pick_action"))
        action = "restart"
    kind = (form.get("kind", "") or "").strip()
    if kind not in SCHEDULE_KINDS:
        errors.append(i18n.Message("flash.schedule_pick_kind"))
        kind = "diario"

    hour = _bounded_int(form.get("hour"), 0, 23, -1)
    minute = _bounded_int(form.get("minute"), 0, 59, -1)
    if kind != "intervalo" and (hour < 0 or minute < 0):
        errors.append(i18n.Message("flash.schedule_bad_time"))
    hours = _bounded_int(form.get("every_hours"), 1, EVERY_HOURS_MAX, -1)
    if kind == "intervalo" and hours < 0:
        errors.append(i18n.Message("flash.schedule_bad_interval", max=EVERY_HOURS_MAX))

    return {
        "action": action,
        "kind": kind,
        "hour": max(0, hour),
        "minute": max(0, minute),
        "weekday": _bounded_int(form.get("weekday"), 0, 6, 0),
        "every_hours": max(1, hours),
    }


def _schedule_or_404(aid: int) -> sqlite3.Row:
    sched = schedules_repo.by_id(db(), aid)
    if not sched:
        abort(404)
    return sched


def _next_occurrence(sched, now: datetime) -> datetime:
    """Quando esta tarefa roda da proxima vez.

    'intervalo' conta a partir da ultima execucao; diario e semanal somam um passo a
    ocorrencia anterior. `ocorrencia_anterior` so devolve None para 'intervalo', que
    nunca chega na segunda metade - mas a checagem fica explicita, porque a alternativa
    e um `TypeError` numa tela que so quebra para quem tem agendamento cadastrado.
    """
    if sched["kind"] == "intervalo":
        last_one = _parse_dt(sched["last_run"]) or now
        return last_one + timedelta(hours=int(sched["every_hours"]))

    previous = previous_occurrence(sched, now) or now
    return previous + timedelta(days=7 if sched["kind"] == "semanal" else 1)


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
_clean_ceiling = chart_service.clean_ceiling


def build_chart(amostras, series, teto: float, start, fim, time_format: str) -> dict:
    # `SAMPLE_EVERY` entra aqui porque e configuracao do painel: e ele que diz a partir
    # de que buraco entre duas amostras a linha do grafico deve ser cortada.
    return chart_service.build_chart(
        amostras, series, teto, start, fim, time_format, SAMPLE_EVERY)


# --------------------------------------------------------------- historico


# ------------------------------------------------------------- acesso / conta


def _two_factor_state() -> dict:
    row = users_repo.two_factor_state(db(), session["uid"])
    # Sessao de um usuario que foi APAGADO enquanto ela estava aberta. Dizer "desligado"
    # e o certo: nao ha o que desligar, e o `login_required` manda a pessoa para o login
    # na proxima volta. Antes daqui a linha estourava com TypeError.
    if row is None:
        return {"ativo": False, "codigos_restantes": 0}
    try:
        remaining_ones = len(json.loads(row["totp_recovery"] or "[]"))
    except ValueError:
        remaining_ones = 0
    return {"ativo": bool(row["totp_enabled"]), "codigos_restantes": remaining_ones}


def _store_second_factor(uid: int, secret: str, step: int) -> list[str]:
    """Liga o 2FA e devolve os codigos de recuperacao EM TEXTO, a unica vez em que existem."""
    codes = totp.new_recovery_codes()
    conn = db()
    with conn:
        users_repo.enable_two_factor(
            conn, uid, secret, step,
            json.dumps([totp.hash_recovery_code(c) for c in codes]))
    return codes


def _password_and_code_ok(uid: int) -> tuple[sqlite3.Row | None, str]:
    """Para desligar o 2FA ou pedir codigos novos: a senha E um codigo. Quem esta logado ja
    provou os dois no login, mas uma sessao esquecida aberta nao pode desligar a protecao."""
    row = users_repo.by_id(db(), uid)
    if row is None:
        # Mesma sessao orfa do `_two_factor_state`: sem usuario nao ha senha a conferir.
        return None, "Senha incorreta."
    key = f"2fa|{row['username'].lower()}"
    if totp_lockout.remaining(key):
        return None, "Muitas tentativas. Espere alguns minutos."
    if not verify_password(request.form.get("senha", ""), row["password_hash"]):
        totp_lockout.record_failure(key)
        return None, "Senha incorreta."
    if not _check_second_factor(row, request.form.get("codigo", "")):
        totp_lockout.record_failure(key)
        return None, "Codigo invalido ou ja usado."
    totp_lockout.clear(key)
    return row, ""


def _delete_second_factor(uid: int) -> None:
    conn = db()
    with conn:
        users_repo.disable_two_factor(conn, uid)


# ------------------------------------------------------------------ alertas


def alerts_without_baseline(conn: sqlite3.Connection) -> dict:
    """Eventos ligados que nao tem em quais servers olhar.

    Alerta ligado e mudo e pior do que alerta desligado: a pessoa marca 'jogo nao
    responde', nenhum servidor tem consulta configurada, e o silencio do canal passa a
    ser lido como "esta tudo bem".
    """
    bound = webhook_config(conn)["events"]
    if not bound & set(ALERT_PRECISA_CONFIG):
        return {}
    servers = servers_repo.all_ordered(conn)
    with_query = sum(1 for s in servers if player_source(s) in ("a2s", "http"))
    with_players = sum(1 for s in servers if player_source(s))
    with_regex = sum(1 for s in servers if _stored_value(s, "error_re"))
    missing_ones = {}
    if ("travou" in bound or "respondeu" in bound) and not with_query:
        missing_ones["travou"] = ALERT_PRECISA_CONFIG["travou"]
    if ("jogador-entrou" in bound or "jogador-saiu" in bound) and not with_players:
        missing_ones["jogador-entrou"] = ALERT_PRECISA_CONFIG["jogador-entrou"]
    if "erro-no-log" in bound and not with_regex:
        missing_ones["erro-no-log"] = ALERT_PRECISA_CONFIG["erro-no-log"]
    return missing_ones


# Os limites em porcentagem da tela de Alertas: campo do formulario, chave no banco e
# como o aviso de recusa chama a coisa.
ALERT_LIMITS = (
    ("disk_pct", "webhook_disk_pct", "disco cheio"),
    ("mem_pct", "webhook_mem_pct", "memoria cheia"),
    ("cpu_pct", "webhook_cpu_pct", "CPU alta"),
)


def _reset_baseline() -> None:
    """A memoria do monitor fica velha quando a configuracao muda.

    Zerando, a proxima volta so ANOTA o estado atual em vez de disparar um alerta sobre
    o que ja estava daquele jeito antes da mudanca.
    """
    _monitor_state.clear()


def _read_webhook_form() -> tuple:
    """Valida o formulario de um destino. Devolve (dados, erro)."""
    name = (request.form.get("name", "") or "").strip()[:60]
    url = (request.form.get("url", "") or "").strip()[:400]
    events = [e for e in request.form.getlist("events") if e in ALERT_EVENTS]
    enabled = 1 if request.form.get("enabled") else 0
    if url and not URL_RE.match(url):
        return None, "URL invalida (comece com http:// ou https://)."
    return {"name": name, "url": url, "events": ",".join(events), "enabled": enabled}, ""


# ------------------------------------------------------------------ usuarios


validate_password = passwords.validate_password


def count_admins(excluding: int = 0) -> int:
    """Quantos administradores sobrariam sem o usuario `excluding`."""
    return users_repo.count_admins_besides(db(), ROLE_ADMIN, excluding)


def _user_or_404(uid: int) -> sqlite3.Row:
    row = users_repo.identity(db(), uid)
    if not row:
        abort(404)
    return row


@app.after_request
def _security_headers(resp):
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


# ------------------------------------------------- aplicativo instalavel (PWA)

# Pastas cujo conteudo o painel consegue servir sem rede depois de instalado.
SHELL_FOLDERS = ("css", "js", "icons")


def _shell_files() -> tuple[list[str], str]:
    """URLs do casco do aplicativo e a marca de versao dele.

    E o que faz um deploy chegar ao celular: marca nova -> arquivo do service worker
    diferente -> o navegador instala e descarta o cache velho. Sem isso, quem instalou
    o painel continuaria vendo a tela da semana passada.

    Num release empacotado a marca e a VERSAO — ela responde "qual codigo este celular
    esta servindo?", que o mtime nao responde. Rodando do repositorio nao ha versao para
    marcar, entao vale o mtime mais recente dos estaticos: e o unico sinal que muda
    quando se salva um CSS sem empacotar nada.
    """
    urls: list[str] = []
    newest = 0
    for folder in SHELL_FOLDERS:
        root = os.path.join(app.static_folder or "", folder)
        for base, _dirs, files in os.walk(root):
            for name in sorted(files):
                path = os.path.join(base, name)
                relative = os.path.relpath(path, app.static_folder).replace(os.sep, "/")
                urls.append(static_url(relative))
                newest = max(newest, int(os.path.getmtime(path)))
    mark = str(newest) if version.BUILD.is_dev else version.BUILD.version
    return urls, mark


def _error_page(exc, code: int):
    """A descricao do `abort(...)` no idioma de quem esta olhando.

    `exc.description` e nao `str(exc)`: o segundo poe "403 Forbidden: " na frente (o
    template ja mostra o codigo em cima) e colapsa a `i18n.Message` numa `str` comum,
    que e o idioma do DEPLOY — a tela em ingles mostrava portugues.
    """
    return render_template(TPL_ERROR, code=code, message=translate(exc.description)), code


@app.errorhandler(400)
def _bad_request(exc):
    return _error_page(exc, 400)


@app.errorhandler(403)
def _forbidden(exc):
    return _error_page(exc, 403)


@app.errorhandler(404)
def _not_found(_exc):
    return render_template(
        TPL_ERROR, code=404, message=translate("error.not_found")), 404


@app.errorhandler(413)
def _too_large(_exc):
    # Os dois tetos sao bem diferentes, e cair no 413 sem saber em qual deles nao ajuda
    # ninguem: o editor carrega o arquivo inteiro num textarea, o upload nao.
    if request.endpoint in BIG_BODY_ENDPOINTS:
        message = translate("error.upload_too_large", limit=_human_size(FILE_UPLOAD_MAX))
    else:
        message = translate("error.content_too_large", kb=FILE_MAX_BYTES // 1024)
    return render_template(TPL_ERROR, code=413, message=message), 413


@app.errorhandler(503)
def _unavailable(exc):
    return _error_page(exc, 503)


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
        row = users_repo.id_by_username(conn, username)
        if row and role:
            users_repo.set_password_and_role(conn, row["id"], hash_password(password), role)
            print(f"Senha do usuario '{username}' redefinida; papel: {role}.")
        elif row:
            users_repo.set_password(conn, row["id"], hash_password(password))
            print(f"Senha do usuario '{username}' redefinida.")
        else:
            # Usuario criado pela linha de comando e admin por padrao: e o do deploy,
            # que precisa cadastrar servidor e criar os demais na tela.
            papel = role or ROLE_ADMIN
            users_repo.insert(conn, username, hash_password(password), papel, now_iso())
            print(f"Usuario '{username}' criado ({papel}).")
    conn.close()


class DeployServer(NamedTuple):
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


def _insert_server(conn: sqlite3.Connection, data: DeployServer) -> None:
    servers_repo.deploy_insert(
        conn,
        [getattr(data, c) for c in servers_repo.DEPLOY_FIELDS],
        now_iso(),
    )


def _merge_config_files(stored: str, incoming: str) -> str:
    """Os arquivos ja cadastrados mais os do deploy, sem repetir e sem perder nenhum."""
    listing = [p for p in (stored or "").splitlines() if p.strip()]
    for fresh in incoming.splitlines():
        if fresh.strip() and fresh.strip() not in listing:
            listing.append(fresh.strip())
    return "\n".join(listing[:CONFIG_FILES_MAX])


def _update_server(conn: sqlite3.Connection, current, data: DeployServer) -> None:
    """Redeploy: o container manda no que e dele, o painel manda no que e escolha.

    Nome, servico, portas e caminho de config vem do deploy — sao fatos do container.
    Ja caminhos de backup, forma de contar jogadores e padroes do log costumam ser
    afinados na tela, e um redeploy nao pode apaga-los.
    """
    # A ordem SEGUE `servers_repo.DEPLOY_UPDATE_FIELDS`: ali esta a lista de colunas, e
    # aqui so a decisao de quem vence em cada uma.
    servers_repo.deploy_update(
        conn,
        [
            data.name, data.ssh_user, data.service, data.game_port,
            data.notes or current["notes"],
            data.config_path or current["config_path"],
            _merge_config_files(current["config_files"], data.config_files),
            current["backup_paths"] or data.backup_paths,
            data.query_port,
            current["player_source"] or data.player_source,
            current["join_re"] or data.join_re,
            current["leave_re"] or data.leave_re,
            current["log_path"] or data.log_path,
        ],
        current["id"],
    )


def ensure_server(data: DeployServer) -> bool:
    """Cadastra (ou atualiza) um servidor sem passar pela tela. Devolve True se criou.

    E por aqui que o deploy registra o container recem-criado no painel — inclusive o
    arquivo de configuracao do jogo, para a tela "Configuracao" ja abrir pronta.
    """
    init_db()
    conn = _connect()
    try:
        with conn:
            current_one = servers_repo.by_address(conn, data.host, data.ssh_port)
            if current_one is None:
                _insert_server(conn, data)
                return True
            _update_server(conn, current_one, data)
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
    resume_broker_jobs()


# No fim do arquivo de proposito: cada blueprint faz `from gamepanel import app as
# panel` e chama `panel.X`, entao ela so pode ser importada depois que `X` existe.
register_all(app)


if __name__ == "__main__":
    # A linha de comando mora em gamepanel/cli.py; o rodape aqui continua existindo
    # porque o README e o CLAUDE.md documentam `python3 .../app.py --reset-2fa USUARIO`,
    # e quem precisa desse comando esta trancado do lado de fora do painel.
    cli.main(cli.CliDeps(
        init_db=init_db, connect=_connect, ensure_admin_user=ensure_admin_user,
        ensure_server=ensure_server, deploy_server=DeployServer,
        start_scheduler=start_scheduler, resume_broker_jobs=resume_broker_jobs,
        app=app, roles=ROLES,
    ))
