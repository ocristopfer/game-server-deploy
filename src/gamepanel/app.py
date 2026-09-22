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

from gamepanel import navigation as ui
from gamepanel.games import config_format as gameconf
from gamepanel.games import gamefields
from gamepanel.games.catalog import search as busca_de_jogos
from gamepanel.games.catalog.templates import MODELOS as MODELOS_DE_JOGO
from gamepanel.integrations import broker_client
from gamepanel.runtime import a2s
from gamepanel.runtime import ssh as ssh_transport
from gamepanel.security import qr, totp
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
  -- Pastas/arquivos (um por linha) que entram no backup. Vazio = usa o config_path.
  backup_paths TEXT NOT NULL DEFAULT '',
  query_port INTEGER NOT NULL DEFAULT 0,
  player_source TEXT NOT NULL DEFAULT '',
  join_re    TEXT NOT NULL DEFAULT '',
  leave_re   TEXT NOT NULL DEFAULT '',
  -- De onde ler o log para contar jogadores. Vazio = journalctl do servico. Preenchido,
  -- e um caminho (pode ter *) para um ARQUIVO dentro do container: varios jogos so
  -- escrevem o nome de quem entra em arquivo proprio, nunca na saida padrao. O DayZ e
  -- assim (profiles/*.ADM, ligado pelo -adminlog).
  log_path   TEXT NOT NULL DEFAULT '',
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
  -- Alerta "erro no log": expressao regular procurada nas ultimas linhas do log do jogo
  -- (o mesmo log da contagem — journalctl ou log_path). Vazia desliga a checagem.
  error_re   TEXT NOT NULL DEFAULT '',
  -- Id da instancia no broker (0 = servidor cadastrado a mao). E o que liga a tela de
  -- instancias ao servidor, e o que remover a instancia usa para apagar este cadastro.
  broker_id  INTEGER NOT NULL DEFAULT 0,
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
  finished_at TEXT,
  -- Operacao do broker que este job acompanha (vazio nos demais). Sobrevive a um restart
  -- do painel: e por ela que o acompanhamento e retomado.
  broker_op   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_jobs_server ON jobs(server_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);

CREATE TABLE IF NOT EXISTS schedules (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  -- CASCADE: tirar o servidor do painel leva junto o que estava agendado para ele.
  server_id   INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  action      TEXT NOT NULL,             -- restart | stop | start | update | backup
  -- 'diario' (hora fixa), 'semanal' (dia da semana + hora), 'intervalo' (a cada N horas)
  kind        TEXT NOT NULL,
  hour        INTEGER NOT NULL DEFAULT 5,
  minute      INTEGER NOT NULL DEFAULT 0,
  weekday     INTEGER NOT NULL DEFAULT 0,   -- 0 = segunda ... 6 = domingo
  every_hours INTEGER NOT NULL DEFAULT 6,
  enabled     INTEGER NOT NULL DEFAULT 1,
  -- Quando disparou pela ultima vez, em hora LOCAL com fuso (o mesmo relogio do
  -- agendamento). E o que impede a mesma ocorrencia de rodar duas vezes.
  last_run    TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sched_server ON schedules(server_id);

-- Uma linha por servidor a cada SAMPLE_EVERY: e o que permite responder "por que travou
-- ontem a noite" depois que a noite passou. CASCADE junto com o servidor.
CREATE TABLE IF NOT EXISTS samples (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  taken_at  TEXT NOT NULL,
  cpu_pct   REAL,
  mem_pct   REAL,
  players   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_samples ON samples(server_id, taken_at);

-- Configuracao que se muda pela tela e tem de sobreviver ao restart do painel (hoje so
-- os alertas). Fica aqui, e nao em variavel de ambiente, para nao exigir redeploy.
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

-- Destinos dos alertas. Cada linha e um canal (um Discord, um Slack, um endpoint
-- proprio) com a SUA lista de eventos: da para mandar tudo para o canal da equipe e so
-- 'servidor caiu' para o canal geral, sem os dois receberem a mesma coisa.
CREATE TABLE IF NOT EXISTS webhooks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  nome       TEXT NOT NULL DEFAULT '',
  url        TEXT NOT NULL,
  eventos    TEXT NOT NULL DEFAULT '',
  ativo      INTEGER NOT NULL DEFAULT 1,
  criado_em  TEXT NOT NULL DEFAULT ''
);

-- Diario de alertas: uma linha por TENTATIVA de envio, e tambem uma por alerta que
-- nasceu sem destino algum. Canal mudo tem duas causas opostas — nada aconteceu, ou
-- aconteceu e nao saiu — e do lado de fora elas sao identicas. Sem este registro a
-- unica saida e adivinhar.
CREATE TABLE IF NOT EXISTS alert_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  criado_em  TEXT NOT NULL,
  evento     TEXT NOT NULL DEFAULT '',
  titulo     TEXT NOT NULL DEFAULT '',
  detalhe    TEXT NOT NULL DEFAULT '',
  destino    TEXT NOT NULL DEFAULT '',
  -- 'enviado', 'falhou', 'sem-destino' ou 'erro-interno'
  status     TEXT NOT NULL DEFAULT '',
  erro       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_alert_log_id ON alert_log (id DESC);
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
    # Log em arquivo: sem esta coluna a contagem so enxergava o journalctl, e o nome do
    # jogador do DayZ (que so existe no .ADM) ficava fora de alcance.
    ("servers", "log_path", "ALTER TABLE servers ADD COLUMN log_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "config_files", "ALTER TABLE servers ADD COLUMN config_files TEXT NOT NULL DEFAULT ''"),
    # Backup: o que guardar de cada servidor. Cadastro antigo fica vazio e cai no
    # config_path, que e o comportamento que ele ja teria se a coluna sempre existisse.
    ("servers", "backup_paths", "ALTER TABLE servers ADD COLUMN backup_paths TEXT NOT NULL DEFAULT ''"),
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
    # Alerta de erro no log: a expressao e por servidor porque cada jogo grita de um
    # jeito. Vazia (o padrao) desliga a checagem — inclusive a ida de SSH dela.
    ("servers", "error_re", "ALTER TABLE servers ADD COLUMN error_re TEXT NOT NULL DEFAULT ''"),
    ("servers", "broker_id", "ALTER TABLE servers ADD COLUMN broker_id INTEGER NOT NULL DEFAULT 0"),
    # Segundo fator (TOTP). O segredo fica em texto porque o servidor precisa dele para conferir
    # o codigo; quem protege e o arquivo do banco (0600, dentro do CT). Os codigos de
    # recuperacao ficam so como hash (JSON com a lista). `totp_last_step` e o anti-repeticao.
    ("users", "totp_secret", "ALTER TABLE users ADD COLUMN totp_secret TEXT NOT NULL DEFAULT ''"),
    ("users", "totp_enabled", "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0"),
    ("users", "totp_last_step", "ALTER TABLE users ADD COLUMN totp_last_step INTEGER NOT NULL DEFAULT 0"),
    ("users", "totp_recovery", "ALTER TABLE users ADD COLUMN totp_recovery TEXT NOT NULL DEFAULT ''"),
    ("jobs", "broker_op", "ALTER TABLE jobs ADD COLUMN broker_op TEXT NOT NULL DEFAULT ''"),
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
        _migra_webhook_unico(conn)
    conn.close()


def _migra_webhook_unico(conn: sqlite3.Connection) -> None:
    """Leva o webhook antigo (settings.webhook_url) para a tabela de destinos.

    A marca 'webhooks_migrado' e o que impede a volta: sem ela, quem apagasse o unico
    destino veria o antigo renascer no restart seguinte.
    """
    ja = conn.execute(
        "SELECT 1 FROM settings WHERE key = 'webhooks_migrado'"
    ).fetchone()
    if ja:
        return
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('webhooks_migrado', '1')"
        " ON CONFLICT(key) DO NOTHING"
    )
    antigo = conn.execute(
        "SELECT value FROM settings WHERE key = 'webhook_url'"
    ).fetchone()
    # Sem nada no banco vale o do deploy: GAMEPANEL_WEBHOOK_URL era o valor inicial da
    # URL unica e continua sendo o do primeiro destino.
    url = (antigo["value"] if antigo else "").strip() or WEBHOOK_URL_PADRAO.strip()
    if not url:
        return
    ev = conn.execute(
        "SELECT value FROM settings WHERE key = 'webhook_events'"
    ).fetchone()
    conn.execute(
        "INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
        " VALUES (?, ?, ?, 1, ?)",
        ("Webhook", url, (ev["value"] if ev else ALERT_DEFAULT), now_iso()),
    )


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
            "SELECT id, username, role, created_at, totp_enabled FROM users WHERE id = ?", (uid,)
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


@app.context_processor
def _inject():
    usuario = usuario_logado()
    return {
        "csrf_token": csrf_token,
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

# De onde a contagem de jogadores pode sair. 'none' e o desligado explicito — diferente
# do vazio, que significa "cadastro antigo, deduza pela porta de consulta".
PLAYER_SOURCES = ("a2s", "http", "log", "none")

QueryError = a2s.QueryError
AuthError = a2s.AuthError


def query_players(host: str, port: int) -> dict:
    # Le QUERY_TIMEOUT na hora da chamada (nao um valor congelado no import): mesmo
    # motivo do SshClient em runtime/ssh.py.
    return a2s.query_players(host, port, timeout=QUERY_TIMEOUT)


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
      -H "$auth" -H 'Content-Type: application/json' \
      --data-binary "$corpo" "$url"
  elif [ -n "$corpo" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H 'Content-Type: application/json' --data-binary "$corpo" "$url"
  elif [ -n "$auth" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H "$auth" "$url"
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
    # Vem 'Nome: valor' pronto (nem toda API autentica por Authorization).
    nome, _, valor = auth.partition(":")
    req.add_header(nome.strip(), valor.strip())
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
    """Transforma o que esta no banco no cabecalho HTTP INTEIRO ('Nome: valor').

    Formatos: 'basic:usuario:senha', 'bearer:token', 'header:Nome: valor' e o valor solto.

    Devolve o cabecalho com nome e tudo, e nao so o valor, por causa das APIs que nao
    autenticam por Authorization — o WebQuery do TeamSpeak quer 'x-api-key'. Com so o
    valor na mao, o unico nome possivel seria o fixo no script remoto.

    O valor solto (cadastro antigo, de quando isto devolvia so o valor) continua saindo
    como Authorization: mudar isso calaria a contagem de quem ja tinha um token gravado.
    """
    texto = (guardado or "").strip()
    if not texto:
        return ""
    tipo, _, resto = texto.partition(":")
    if tipo.lower() == "basic":
        return "Authorization: Basic " + base64.b64encode(resto.encode()).decode()
    if tipo.lower() == "bearer":
        return "Authorization: Bearer " + resto
    # 'header:' e a saida para o resto do mundo. O que vem depois vai cru, com nome e
    # tudo, porque so quem cadastrou sabe como a API dela chama esse cabecalho.
    if tipo.lower() == "header" and ":" in resto:
        return resto.strip()
    return "Authorization: " + texto


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


def http_json(server: Servidor, url: str, auth: str, corpo: str, exigir_json: bool = True):
    """Chama a URL de dentro do container e devolve o JSON ja interpretado.

    `exigir_json=False` para quem so quer saber se deu certo: expulsar, banir e avisar
    respondem 200 com o corpo VAZIO, e ai "a resposta nao e JSON" seria um erro inventado
    em cima de uma acao que funcionou.
    """
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
        if not exigir_json:
            return {}
        amostra = texto.strip()[:120] or "(vazia)"
        raise QueryError(f"a resposta nao e JSON: {amostra}")


# Chaves que os jogos costumam usar. Comparadas sem maiusculas nem separadores, entao
# 'numConnectedPlayers', 'num_connected_players' e 'NUMCONNECTEDPLAYERS' sao a mesma.
LIST_KEYS = {"players", "playerlist", "onlineplayers", "connectedplayers", "clients"}
NAME_KEYS = ("name", "playername", "accountname", "username", "displayname", "nick", "clientnickname")
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


def _e_cliente_de_consulta(item) -> bool:
    """Conexao de ServerQuery, nao gente no canal.

    O TeamSpeak devolve na MESMA lista quem esta no voz (client_type 0) e as conexoes de
    consulta (client_type 1) — e uma delas e a do proprio painel, que acabou de perguntar.
    Sem tirar essas, o painel se contaria como usuario online e mandaria "entrou no jogo"
    sobre si mesmo a cada volta. Jogo que nao publica client_type nao e afetado.
    """
    if not isinstance(item, dict):
        return False
    tipo = {_slug(k): v for k, v in item.items()}.get("clienttype")
    if tipo is None:
        return False
    try:
        # O WebQuery manda tudo como string ("client_type": "1").
        return int(tipo) != 0
    except (TypeError, ValueError):
        return False


# Kick e ban pedem um identificador, nunca o nome: nome muda, repete e nao e chave.
ID_KEYS = ("userid", "playeruid", "playerid", "steamid", "accountid", "uid")


def _id_do_item(item) -> str:
    """Identificador do jogador, quando a API publica um. Vazio quando nao publica."""
    if not isinstance(item, dict):
        return ""
    por_slug = {_slug(k): v for k, v in item.items()}
    for chave in ID_KEYS:
        valor = por_slug.get(chave)
        if isinstance(valor, bool) or not isinstance(valor, (str, int)):
            continue
        if str(valor).strip():
            return str(valor).strip()
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


def _lista_do_json(dados, caminho_lista: str, caminho_contagem: str) -> list | None:
    """A lista de jogadores da resposta, ou None quando a API nao publica uma.

    Com o caminho da contagem preenchido e sem o da lista, nem se procura: quem
    informou onde esta o numero esta dizendo que lista nao ha.
    """
    if caminho_lista:
        lista = _json_walk(dados, caminho_lista)
        if not isinstance(lista, list):
            raise QueryError(f"'{caminho_lista}' nao aponta para uma lista")
    elif caminho_contagem:
        return None
    else:
        lista = _acha_lista(dados)

    if not isinstance(lista, list):
        return None
    # Antes de contar e de tirar nomes: o que sai daqui nao e jogador, e contaria como um.
    return [item for item in lista if not _e_cliente_de_consulta(item)]


def _contagem_do_json(dados, caminho_contagem: str, lista: list | None) -> int | None:
    """Quantos estao online, pelo caminho informado ou por chave conhecida.

    Devolve None quando ha lista: nesse caso quem conta e o tamanho dela.
    """
    if caminho_contagem:
        bruto = _json_walk(dados, caminho_contagem)
        if isinstance(bruto, list):
            return len(bruto)
        if isinstance(bruto, (int, float)) and not isinstance(bruto, bool):
            return int(bruto)
        raise QueryError(f"'{caminho_contagem}' nao e um numero nem uma lista")
    if lista is not None:
        return None
    achou = _acha_valor(dados, COUNT_KEYS, (int, float))
    return int(achou) if achou is not None else None


def _nomes_do_json(lista: list | None) -> list[dict]:
    """A lista no formato que as telas do painel esperam. Teto de 128 por resposta."""
    if lista is None:
        return []
    saida = []
    for item in lista[:128]:
        nome = _nome_do_item(item)
        if nome:
            saida.append({"name": nome, "id": _id_do_item(item), "since": "",
                          "score": 0, "seconds": 0})
    return saida


def read_players_json(dados, caminho_lista: str = "", caminho_contagem: str = "") -> dict:
    """Tira jogadores de um JSON qualquer.

    Sem caminhos preenchidos o painel procura sozinho uma lista de jogadores e, se nao
    houver, um numero em alguma chave conhecida (currentplayernum, numplayers, ...).
    """
    lista = _lista_do_json(dados, caminho_lista, caminho_contagem)
    quantos = _contagem_do_json(dados, caminho_contagem, lista)
    nomes = _nomes_do_json(lista)
    if quantos is None and lista is not None:
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


def _tem_login(server: Servidor) -> bool:
    """True quando o servidor esta configurado para obter o token sozinho."""
    try:
        return bool((server["http_login_url"] or "").strip()
                    and (server["http_token_path"] or "").strip())
    except (IndexError, KeyError):
        # Linha vinda de um SELECT sem as colunas novas (ou banco antes da migracao).
        return False


def _valor_guardado(server: Servidor, coluna: str) -> str:
    try:
        return (server[coluna] or "").strip()
    except (IndexError, KeyError):
        return ""


def http_login(server: Servidor) -> str:
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


def chama_api_do_jogo(server: Servidor, url: str, corpo: str = "",
                      exigir_json: bool = True):
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
        auth = f"bearer:{token}" if token else f"bearer:{http_login(server)}"
    else:
        auth = server["http_auth"]

    try:
        return http_json(server, url, auth, corpo, exigir_json)
    except AuthError:
        if not com_login:
            raise
        # Token expirado ou revogado: renova uma vez e repete. Se falhar de novo,
        # o erro sobe - ai o problema e a credencial, nao o prazo do token.
        return http_json(server, url, f"bearer:{http_login(server)}", corpo, exigir_json)


def players_from_http(server: Servidor) -> dict:
    if not (server["http_url"] or "").strip():
        raise QueryError("informe a URL da API do jogo")
    dados = chama_api_do_jogo(server, server["http_url"], server["http_body"])
    return read_players_json(dados, server["http_list_path"], server["http_count_path"])


# ------------------------------------------- acoes sobre quem esta jogando
#
# Expulsar, banir e avisar saem pela MESMA API que ja conta os jogadores — outra rota,
# mesma credencial. Nao ha padrao entre os jogos, entao vai um catalogo, reconhecido pela
# URL de contagem que o servidor ja tem cadastrada.
#
# Dos jogos que este repo instala, so o Palworld publica essas acoes (o Satisfactory nao
# tem kick na API). Jogo novo entra como mais uma entrada aqui, sem tocar no resto.

PLAYER_MSG_MAX = 200
PLAYER_ACTION_LABELS = {
    "announce": "Avisar todo mundo",
    "kick": "Expulsar",
    "ban": "Banir",
}

# Os marcadores do catalogo, como constantes: sao a interface entre a tabela abaixo e
# o `_preenche`, e escreve-los a mao em cada linha e como um deles vira "{mensagen}"
# num jogo so, sem ninguem notar ate alguem tentar expulsar alguem.
MARCA_BASE = "{base}"
MARCA_JOGADOR = "{jogador}"
MARCA_MENSAGEM = "{mensagem}"

API_ACOES = (
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


def api_de_acoes(server: Servidor) -> dict | None:
    """A API deste servidor aceita acoes? Devolve a entrada do catalogo, ou None."""
    if player_source(server) != "http":
        return None
    url = (server["http_url"] or "").strip()
    for entrada in API_ACOES:
        casa = entrada["url"].match(url)
        if casa:
            return {**entrada, "base": casa.group("base")}
    return None


def acoes_de_jogador(server: Servidor) -> list[str]:
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


def acao_de_jogador(server: Servidor, acao: str, jogador: str, mensagem: str) -> str:
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
    chama_api_do_jogo(server, _preenche(rota, api["base"], jogador, mensagem),
                      json.dumps(corpo), exigir_json=False)
    return PLAYER_ACTION_LABELS.get(acao, acao)


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
# $3 = caminho do arquivo de log (pode ter *). Vazio cai no journalctl do servico.
# Acompanha o log e vai cuspindo linha nova enquanto o SSH estiver de pe. `-n 0`/`tail -n
# 0` de proposito: o passado nao interessa aqui: quem sabe dizer quem esta online agora e
# a contagem normal, e este script so avisa que ACONTECEU alguma coisa. Assim o painel nao
# precisa reproduzir a maquina de estados do log em dois lugares diferentes.
LOG_FOLLOW_SCRIPT = r"""
set -u
unit=$1
alvo=${2:-}

if [ -n "$alvo" ]; then
  # Sem aspas para o shell expandir o '*' — o LOG_PATH_RE do painel e quem garante que
  # nao ha espaco, aspas, $ ou ';' aqui dentro.
  arq=$(ls -1t $alvo 2>/dev/null | head -n 1)
  [ -n "$arq" ] || { echo "nenhum arquivo de log casa com $alvo" >&2; exit 3; }
  # -F (e nao -f) para sobreviver a rotacao do arquivo.
  exec tail -n 0 -F -- "$arq"
fi

exec journalctl -u "$unit" -n 0 -f -o short-iso --no-pager
"""

LOG_PLAYERS_SCRIPT = r"""
set -u
unit=$1
max=$2
alvo=${3:-}

if [ -n "$alvo" ]; then
  # $alvo vai SEM aspas de proposito, para o shell do container expandir o '*'. Quem
  # garante que isso e seguro e o LOG_PATH_RE do painel, que so deixa passar caminho
  # absoluto com letras, numeros, . _ - / * ? — nada de espaco, aspas, $ ou ;.
  arq=$(ls -1t $alvo 2>/dev/null | head -n 1)
  [ -n "$arq" ] || { echo "nenhum arquivo de log casa com $alvo" >&2; exit 3; }
  [ -r "$arq" ] || { echo "sem permissao de leitura em $arq" >&2; exit 4; }
  tail -n "$max" -- "$arq"
  exit 0
fi

inicio=$(systemctl show -p ActiveEnterTimestamp --value "$unit" 2>/dev/null || true)
if [ -n "$inicio" ]; then
  journalctl -u "$unit" --since "$inicio" --no-pager -o short-iso 2>/dev/null | tail -n "$max"
else
  journalctl -u "$unit" --no-pager -o short-iso -n "$max" 2>/dev/null
fi
"""


def compile_pattern(raw: str | None, rotulo: str):
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


def _events_meio_nome(linhas, entrar, sair) -> dict:
    """Entrada com nome, saida sem — o caso do Satisfactory.

    O log diz que alguem saiu, mas nao diz quem. A CONTAGEM continua sendo a mesma de
    antes (entradas menos saidas, exata); a lista passa a mostrar os ultimos a entrar,
    tantos quantos a conta disser. E um palpite, e a tela avisa que e — mas jogar os
    nomes fora, que era o que o painel fazia, nao ajudava ninguem.
    """
    total = 0
    ordem: list[tuple[str, str]] = []
    for line in linhas:
        curta = line[:LOG_LINE_MAX]
        entrou = entrar.search(curta)
        if entrou:
            total += 1
            nome = (entrou.groupdict().get("name") or "").strip()
            if nome:
                # Reconexao volta para o fim da fila em vez de duplicar.
                ordem = [p for p in ordem if p[0] != nome]
                ordem.append((nome, _log_timestamp(line)))
            continue
        if sair and sair.search(curta):
            total = max(0, total - 1)
            if ordem:
                ordem.pop(0)  # sai quem esta ha mais tempo: o chute menos ruim
    lista = ordem[-total:] if total else []
    return {
        "players": total,
        "list": [{"name": n, "since": t, "score": 0, "seconds": 0} for n, t in lista],
        "aproximado": True,
    }


def _apply_log_events(linhas, entrar, sair) -> dict:
    """Reproduz os eventos do log em ordem e devolve quem ficou.

    Tres casos, do melhor para o pior: nome nos dois lados (sabe-se quem esta online),
    nome so na entrada (sabe-se quantos, e quem provavelmente), nome em lugar nenhum
    (so a contagem).
    """
    if not entrar.groupindex.get("name"):
        return _events_by_count(linhas, entrar, sair)
    if not sair or sair.groupindex.get("name"):
        return _events_by_name(linhas, entrar, sair)
    return _events_meio_nome(linhas, entrar, sair)


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


def _le_portas_abertas(raw: str, escutando: dict, donos: dict) -> None:
    """Preenche `escutando` e `donos` com o que o LISTEN_PORTS_SCRIPT devolveu.

    Cada linha e "<proto> <porta> <pid> <nome do processo>". Linha que nao tiver essa
    forma e ignorada sem reclamar: o script le /proc a unha, e um container estranho
    pode devolver algo que nao casa - deixar de listar uma porta e melhor do que
    derrubar o assistente inteiro.
    """
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


def candidate_ports(server: Servidor) -> tuple[list[int], list[int], dict, str]:
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
        _le_portas_abertas(raw, escutando, donos)
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


def probe_http_ports(server: Servidor, portas: list[int]) -> tuple[list[dict], list[int], str]:
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


# Caminho do arquivo de log. O '*' e permitido (o DayZ abre um .ADM por sessao), mas
# nada que o shell do container interprete como outra coisa: sem espaco, aspas, $, ; ou &.
LOG_PATH_RE = re.compile(r"^/[A-Za-z0-9._*?/-]{1,200}$")


def log_path_valido(bruto: str | None) -> str:
    """Confere o caminho do log antes de ele entrar num comando remoto."""
    caminho = (bruto or "").strip()
    if not caminho:
        return ""
    if not LOG_PATH_RE.match(caminho) or ".." in caminho:
        raise ValueError(
            "caminho de log invalido - use um caminho absoluto, sem espacos"
            " (o '*' e permitido, ex.: /opt/game/profiles/*.ADM)"
        )
    return caminho


def read_log_lines(server: Servidor, limite: int = LOG_SCAN_MAX) -> list[str]:
    """Linhas do log: de um arquivo, quando o servidor tem um; senao do journalctl.

    O limite e parametro porque os dois usos pedem tamanhos bem diferentes: a contagem de
    jogadores precisa do historico inteiro da subida (quem entrou e nao saiu), e a
    varredura de erro so quer o rabo do log, de minuto em minuto.
    """
    try:
        alvo = log_path_valido(_valor_guardado(server, "log_path"))
    except ValueError as exc:
        raise QueryError(str(exc))
    raw = ssh_output(
        server,
        q("bash", "-lc", LOG_PLAYERS_SCRIPT, "gp", server["service"], str(limite), alvo),
        timeout=60,
    )
    return raw.splitlines()


def players_from_log(server: Servidor) -> dict:
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


def player_source(server: Servidor) -> str:
    """Como contar os jogadores deste servidor: 'a2s', 'http', 'log' ou '' (desligado)."""
    escolhido = (server["player_source"] or "").strip()
    if escolhido in PLAYER_SOURCES:
        return "" if escolhido == "none" else escolhido
    # Cadastro antigo, anterior ao campo: porta de consulta preenchida = A2S.
    return "a2s" if int(server["query_port"] or 0) else ""


def server_players(server: Servidor, force: bool = False) -> dict:
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
    saida: dict = {"cpu_pct": None, "net_rx": None, "net_tx": None, "proc_cpu_pct": None}
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


def server_metrics(server: Servidor, force: bool = False) -> dict:
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


def server_status(server: Servidor, force: bool = False) -> dict:
    key = int(server["id"])
    now = time.monotonic()
    if not force:
        with _status_lock:
            cached = _status_cache.get(key)
        if cached and now - cached[0] < STATUS_TTL:
            return cached[1]

    state = {"reachable": False, "service": "desconhecido", "error": "",
             "sub": "", "restarts": 0, "result": ""}
    try:
        # `systemctl show` no lugar de `is-active`: mesma ida de SSH, mas traz junto o que
        # distingue "eu parei" de "quebrou" (Result) e o contador de restarts automaticos
        # (NRestarts), que e o unico jeito de enxergar um loop de crash — entre uma queda
        # e a proxima o `is-active` responde 'active' e o painel nunca via nada.
        # Ele sai com 0 mesmo para unidade que nao existe, entao nao precisa de '|| true'.
        raw = ssh_output(server, q(
            "systemctl", "show", server["service"],
            "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts", "-p", "Result",
        ))
        campos = {}
        for linha in raw.splitlines():
            chave, _, valor = linha.partition("=")
            campos[chave.strip()] = valor.strip()
        state["reachable"] = True
        state["service"] = campos.get("ActiveState") or "inactive"
        state["sub"] = campos.get("SubState", "")
        state["result"] = campos.get("Result", "")
        # NRestarts so existe no systemd >= 235; sem ele o loop de restart nao e
        # detectavel e o painel simplesmente nao avisa desse evento nesse servidor.
        try:
            state["restarts"] = int(campos.get("NRestarts", "0") or 0)
        except ValueError:
            state["restarts"] = 0
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


def mascara_url(url: str) -> str:
    """Deixa so o bastante para reconhecer o destino, sem expor o token.

    A URL de webhook e uma credencial: quem le a tela por cima do ombro (ou num
    screenshot colado num chat) nao deveria sair de la podendo escrever no canal.
    """
    if not url:
        return ""
    corte = url.split("://", 1)[-1]
    host, _, resto = corte.partition("/")
    if not resto:
        return host
    partes = [p for p in resto.split("/") if p]
    if len(partes) >= 2:
        # Discord: .../webhooks/<id>/<token>. O id identifica, o token e que e segredo.
        return f"{host}/.../{partes[-2]}/{'*' * 8}"
    return f"{host}/.../{'*' * 8}"


def envia_webhook(url: str, texto: str) -> str:
    """Faz o POST. Devolve "" quando deu certo, ou o motivo da falha.

    O corpo leva 'content' E 'text': o primeiro e o campo do Discord, o segundo o do
    Slack. Cada um le o seu e ignora o outro, entao a mesma chamada serve para os dois
    (e para qualquer coisa que aceite JSON).
    """
    if not URL_RE.match(url or ""):
        return "URL invalida (use http:// ou https://)"
    corpo = json.dumps({"content": texto, "text": texto}).encode("utf-8")
    pedido = urllib.request.Request(
        url,
        data=corpo,
        headers={"Content-Type": "application/json", "User-Agent": WEBHOOK_UA},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=WEBHOOK_TIMEOUT) as resp:
            resp.read(2048)
        return ""
    except urllib.error.HTTPError as exc:
        # O corpo da resposta e onde o destino diz o que nao gostou (o Discord manda um
        # JSON com 'message'). Sem ele, um 400 por payload torto e um 403 por bloqueio
        # do Cloudflare ficam com a mesma cara na tela.
        try:
            motivo = exc.read(300).decode("utf-8", "replace").strip().replace("\n", " ")
        # Resposta ja consumida/fechada.
        except Exception:  # noqa: BLE001
            motivo = ""
        return f"o webhook respondeu HTTP {exc.code}" + (f": {motivo}" if motivo else "")
    # Rede: DNS, TLS, timeout, recusa...
    except Exception as exc:  # noqa: BLE001
        return f"nao consegui chamar o webhook: {exc}"


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


def _alerta_de_estado(conn, server, estado, anterior) -> None:
    """Contato com o container e estado do servico.

    NAO recebe `cfg`: quem decide se um evento sai e o `notifica`, que le a
    configuracao por conta propria. Um parametro que ninguem usa vira ruido na
    assinatura e mentira na leitura ("ah, entao aqui olha a config").
    """
    sid, nome = int(server["id"]), server["name"]
    alvo = f"{server['ssh_user']}@{server['host']}"

    if estado["reachable"] != anterior["reachable"]:
        if estado["reachable"]:
            notifica(conn, "acessivel", f"{nome}: contato restabelecido", alvo)
        else:
            notifica(conn, "inacessivel", f"{nome}: painel perdeu contato",
                     f"{alvo}\n{estado.get('error') or 'sem detalhe'}")
        return  # sem contato nao da para falar do servico com honestidade

    if not estado["reachable"]:
        return
    if estado["service"] == anterior["service"]:
        return
    if estado["service"] == "active":
        notifica(conn, "voltou", f"{nome}: servidor voltou a rodar", alvo)
        return
    if anterior["service"] != "active":
        return

    # 'failed' e o systemd dizendo que o jogo quebrou (saiu com erro, estourou o limite de
    # restarts, foi morto pelo OOM). Nao passa pela janela de silencio: se alguem mandou
    # reiniciar e o resultado foi 'failed', isso e exatamente o que a pessoa precisa saber.
    if estado["service"] == "failed":
        notifica(conn, "quebrou", f"{nome}: o jogo quebrou",
                 f"{alvo}\nservico {server['service']} esta 'failed'"
                 + (f" (Result={estado['result']})" if estado.get("result") else ""))
    elif not _job_recente(conn, sid):
        notifica(conn, "caiu", f"{nome}: servidor parou de rodar",
                 f"{alvo}\nservico {server['service']} esta '{estado['service']}'")


def _alerta_de_restart(conn, server, estado, anterior) -> None:
    """Loop de crash: o systemd ressuscitando o jogo sem parar.

    E o buraco que o alerta de queda nao cobre. Com `Restart=always` o jogo pode morrer a
    cada 20 segundos que o `ActiveState` responde 'active' quase sempre — a queda nunca
    'acontece' aos olhos do painel, e o canal fica em silencio enquanto ninguem consegue
    jogar. Quem denuncia e o NRestarts, que so sobe.
    """
    sid, nome = int(server["id"]), server["name"]
    agora = int(estado.get("restarts") or 0)
    antes = int(anterior.get("restarts") or 0)

    # O contador zera quando alguem reinicia a unidade na mao (e ao recarregar o daemon).
    # Isso nao e um loop: e so uma linha de base nova.
    if agora < antes:
        anterior["restarts"] = agora
        anterior["loop_avisado"] = False
        return
    if agora == antes:
        # Uma volta inteira sem nenhum restart novo: o loop passou, e o proximo pode
        # voltar a avisar.
        anterior["loop_avisado"] = False
        return

    quantos = agora - antes
    anterior["restarts"] = agora
    # Enquanto o contador sobe volta apos volta, o alerta sai UMA vez. Repetir a cada
    # minuto seria o mesmo spam que a regra da mudanca existe para evitar.
    if anterior.get("loop_avisado") or _job_recente(conn, sid):
        return
    anterior["loop_avisado"] = True
    notifica(
        conn, "reiniciando", f"{nome}: o jogo esta caindo em loop",
        f"{server['ssh_user']}@{server['host']}\n"
        f"o systemd reiniciou {server['service']} {quantos}x desde a ultima olhada"
        f" ({agora} no total desta subida)",
    )


def _alerta_de_mudez(conn, server, estado, anterior) -> None:
    """Servico de pe, jogo mudo: nao responde mais a consulta do proprio jogo.

    E o caso que mais engana. O processo continua vivo, o systemd continua feliz, o
    dashboard continua verde — e ninguem consegue entrar. So vale para quem responde a
    uma sondagem de verdade (A2S ou API HTTP); contagem por log nao pergunta nada ao
    jogo, entao nao tem o que ficar mudo.
    """
    sid, nome = int(server["id"]), server["name"]
    if player_source(server) not in ("a2s", "http"):
        return

    # Jogo que acabou de subir ainda esta carregando mapa e nao responde: contar essas
    # voltas transformaria toda partida do zero num alerta. O mesmo para a janela de
    # silencio depois de uma acao pelo painel.
    if estado["service"] != "active" or _job_recente(conn, sid):
        anterior["mudo"] = 0
        return

    dados = server_players(server)
    if not dados.get("configured"):
        return

    if not dados.get("error"):
        anterior["mudo"] = 0
        if anterior.get("mudo_avisado"):
            anterior["mudo_avisado"] = False
            notifica(conn, "respondeu", f"{nome}: o jogo voltou a responder",
                     f"{dados.get('players')} jogador(es) online")
        return

    anterior["mudo"] = int(anterior.get("mudo") or 0) + 1
    if anterior["mudo"] < MUTE_ROUNDS or anterior.get("mudo_avisado"):
        return
    anterior["mudo_avisado"] = True
    notifica(
        conn, "travou", f"{nome}: o jogo nao responde",
        f"{server['ssh_user']}@{server['host']}\n"
        f"o servico {server['service']} esta rodando, mas o jogo nao responde ha"
        f" {anterior['mudo']} verificacoes\n{dados['error']}",
    )


def _alerta_de_log(conn, server, anterior) -> None:
    """Procura a expressao de erro do servidor no rabo do log do jogo.

    E o unico alerta que depende de configuracao: cada jogo grita de um jeito, entao a
    expressao vem do cadastro. Sem ela, nem a ida de SSH acontece.
    """
    padrao = _valor_guardado(server, "error_re")
    if not padrao:
        return
    nome = server["name"]
    try:
        regex = compile_pattern(padrao, "erro")
    except QueryError as exc:
        app.logger.warning("expressao de erro de '%s' invalida: %s", nome, exc)
        return
    if regex is None:
        return  # padrao so de espacos: nao ha o que procurar
    try:
        linhas = read_log_lines(server, LOG_ERR_LINES)
    except (RemoteError, QueryError) as exc:
        # Log ilegivel nao e erro DO JOGO. Se o servidor sumiu, quem avisa e o
        # 'inacessivel'; inventar um alerta de log aqui seria contar a mesma coisa duas
        # vezes, com o nome errado.
        app.logger.info("nao consegui ler o log de '%s' para procurar erro: %s", nome, exc)
        return

    achados = [l.strip() for l in linhas if regex.search(l)]
    if not achados:
        # A linha saiu do rabo do log: se o erro voltar, e um erro novo e avisa de novo.
        anterior["ultimo_erro"] = ""
        return

    ultima = achados[-1][:300]
    # Mesma linha da volta passada: um jogo que repete o erro a cada segundo renderia um
    # alerta por minuto ate alguem desligar o webhook.
    if ultima == anterior.get("ultimo_erro"):
        return
    # Trava de seguranca para expressao larga demais (um `.` casa tudo): mesmo com linhas
    # sempre diferentes, o canal nao leva mais de um alerta destes por janela.
    agora = time.monotonic()
    ultimo_envio = float(anterior.get("erro_em") or 0)
    if ultimo_envio and agora - ultimo_envio < LOG_ERR_COOLDOWN:
        anterior["ultimo_erro"] = ultima
        return
    anterior["ultimo_erro"] = ultima
    anterior["erro_em"] = agora
    quantas = f" ({len(achados)} linhas casaram)" if len(achados) > 1 else ""
    notifica(conn, "erro-no-log", f"{nome}: erro no log do jogo",
             f"{server['ssh_user']}@{server['host']}{quantas}\n{ultima}")


def _alerta_de_disco(conn, server, cfg) -> None:
    sid = int(server["id"])
    dados = server_metrics(server)
    if dados.get("error"):
        return
    pior = max((d for d in dados.get("disks", []) if d.get("pct") is not None),
               key=lambda d: d["pct"], default=None)
    if not pior:
        return
    cheio = pior["pct"] >= cfg["disco"]
    marca = _estado_monitor.setdefault(sid, {})
    # So avisa na VIRADA: um disco a 95%% continua a 95%% na volta seguinte, e ninguem
    # merece o mesmo alerta a cada minuto ate arrumar.
    if cheio and not marca.get("disco_cheio"):
        notifica(conn, "disco-cheio", f"{server['name']}: disco quase cheio",
                 f"{pior['mount']} em {pior['pct']}% "
                 f"({_human_size(pior['used'])} de {_human_size(pior['total'])})")
    marca["disco_cheio"] = cheio


def _alerta_de_memoria(conn, server, cfg) -> None:
    sid = int(server["id"])
    dados = server_metrics(server)
    if dados.get("error"):
        return
    mem = dados.get("mem")
    if not mem or mem.get("pct") is None:
        return
    cheio = mem["pct"] >= cfg["memoria"]
    marca = _estado_monitor.setdefault(sid, {})
    # So avisa na virada
    if cheio and not marca.get("memoria_alta"):
        notifica(conn, "memoria-alta", f"{server['name']}: memoria quase cheia",
                 f"{mem['pct']}% ({_human_size(mem['used'])} de {_human_size(mem['total'])})")
    marca["memoria_alta"] = cheio


def _alerta_de_cpu(conn, server, cfg) -> None:
    sid = int(server["id"])
    dados = server_metrics(server)
    if dados.get("error"):
        return
    cpu = dados.get("cpu_pct")
    if cpu is None:
        return
    alto = cpu >= cfg["cpu"]
    marca = _estado_monitor.setdefault(sid, {})
    # So avisa na virada
    if alto and not marca.get("cpu_alta"):
        cores = dados.get("cores", 1)
        proc = dados.get("proc", {})
        proc_cpu = proc.get("cpu_pct")
        detalhe = f"{cpu}% em {cores} nucleo{'s' if cores != 1 else ''}"
        if proc_cpu is not None:
            detalhe += f" (jogo: {proc_cpu}%)"
        notifica(conn, "cpu-alta", f"{server['name']}: uso de CPU alto", detalhe)
    marca["cpu_alta"] = alto


# Evento de recurso -> quem confere. Os tres leem o MESMO medidor e andam no mesmo
# relogio; como tabela, ligar um quarto (rede, por exemplo) e acrescentar uma linha,
# nao mais um `if` dentro do laco do monitor.
ALERTAS_DE_RECURSO = {
    "disco-cheio": _alerta_de_disco,
    "memoria-alta": _alerta_de_memoria,
    "cpu-alta": _alerta_de_cpu,
}


def _alerta_de_jogadores(conn, server, servico, anterior, cfg) -> None:
    """Avisa quando jogadores entram ou saem do servidor.

    Compara a lista de jogadores atual com a da verificacao anterior. Se o jogo
    tiver nomes (pelo log com (?P<name>...), API HTTP ou A2S), cita o nome de quem
    entrou ou saiu. Se o jogo so devolver a contagem, avisa a variacao numerica.

    Recebe o `servico` (string) em vez do estado inteiro de proposito: a volta rapida do
    monitor nao consulta o systemd, e passa aqui o ultimo estado ja conhecido. Pedir o
    dicionario obrigaria a pagar um SSH so para preencher um campo que ja se sabe.
    """
    sid, nome = int(server["id"]), server["name"]
    if not player_source(server):
        return

    # Se o servico nao estiver ativo ou tiver job recente (restart, update),
    # reseta o estado para nao disparar alertas falsos de desconexao.
    if servico != "active" or _job_recente(conn, sid):
        anterior["jogadores_nomes"] = None
        anterior["jogadores_count"] = None
        return

    dados = server_players(server)
    if not dados.get("configured") or dados.get("error"):
        return

    nomes_atuais, contagem_atual = _leitura_de_jogadores(dados)

    # Primeira olhada deste servidor: so estabelece a linha de base
    if anterior.get("jogadores_nomes") is None and anterior.get("jogadores_count") is None:
        anterior["jogadores_nomes"] = nomes_atuais
        anterior["jogadores_count"] = contagem_atual
        return

    nomes_anteriores = anterior.get("jogadores_nomes") or set()
    contagem_anterior = int(anterior.get("jogadores_count") or 0)

    if nomes_atuais or nomes_anteriores:
        # O jogo da os nomes (exatos ou aproximados): o aviso cita quem foi.
        _avisa_por_nome(conn, nome, cfg, nomes_atuais, nomes_anteriores, contagem_atual)
    else:
        # So a contagem: o aviso fala da variacao.
        _avisa_por_contagem(conn, nome, cfg, contagem_atual, contagem_anterior)

    anterior["jogadores_nomes"] = nomes_atuais
    anterior["jogadores_count"] = contagem_atual


def _leitura_de_jogadores(dados: dict) -> tuple[set, int]:
    """Normaliza a resposta da consulta em (nomes, contagem).

    Jogo que so devolve numero vem com a lista vazia; jogo que so devolve nomes vem
    sem contagem. Os dois casos saem daqui com a mesma forma, e e isso que permite ao
    resto da funcao nao repetir `or 0` e `or []` a cada linha.
    """
    lista = dados.get("list") or []
    nomes = {p["name"].strip() for p in lista if p.get("name") and p["name"].strip()}
    contagem = dados.get("players")
    if contagem is None and nomes:
        contagem = len(nomes)
    return nomes, max(0, int(contagem or 0))


def _texto_de_online(contagem: int) -> str:
    """"3 jogadores online", "1 jogador online", "nenhum jogador online".

    Existia em quatro lugares desta tela, com uma diferenca sutil entre eles: um dos
    quatro nao tratava o zero e podia dizer "0 jogadores online". Um lugar so.
    """
    if contagem == 0:
        return "nenhum jogador online"
    return f"{contagem} jogador{'es' if contagem != 1 else ''} online"


def _avisa_por_nome(conn, nome, cfg, atuais: set, anteriores: set, contagem: int) -> None:
    """Um aviso por pessoa que entrou ou saiu."""
    detalhe = _texto_de_online(contagem)
    if "jogador-entrou" in cfg["eventos"]:
        for jogador in sorted(atuais - anteriores):
            notifica(conn, "jogador-entrou", f"{nome}: {jogador} entrou no jogo", detalhe)
    if "jogador-saiu" in cfg["eventos"]:
        for jogador in sorted(anteriores - atuais):
            notifica(conn, "jogador-saiu", f"{nome}: {jogador} saiu do jogo", detalhe)


def _avisa_por_contagem(conn, nome, cfg, atual: int, anterior: int) -> None:
    """Um aviso por variacao, para o jogo que nao publica nomes."""
    if atual == anterior:
        return
    detalhe = _texto_de_online(atual)
    if atual > anterior and "jogador-entrou" in cfg["eventos"]:
        dif = atual - anterior
        texto = "um jogador conectou" if dif == 1 else f"{dif} jogadores conectaram"
        notifica(conn, "jogador-entrou", f"{nome}: {texto}", detalhe)
    elif atual < anterior and "jogador-saiu" in cfg["eventos"]:
        dif = anterior - atual
        texto = "um jogador saiu" if dif == 1 else f"{dif} jogadores saíram"
        notifica(conn, "jogador-saiu", f"{nome}: {texto}", detalhe)


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

_streams: dict[int, "_LogStream"] = {}
_streams_lock = threading.Lock()
# Um alerta de jogador por servidor de cada vez: o stream e a volta do monitor mexem no
# MESMO _estado_monitor[sid], e sem isto os dois poderiam avisar a mesma entrada.
_jogadores_locks: dict[int, threading.Lock] = {}
_jogadores_meta = threading.Lock()


def lock_de_jogadores(sid: int) -> threading.Lock:
    with _jogadores_meta:
        return _jogadores_locks.setdefault(sid, threading.Lock())


def _linha_de_jogador(linha: str, entrar, sair) -> bool:
    """Esta linha do log e uma entrada ou saida de jogador?"""
    curta = linha[:LOG_LINE_MAX]
    if entrar and entrar.search(curta):
        return True
    return bool(sair and sair.search(curta))


def _assinatura_de_stream(server) -> tuple:
    """O que, mudando, obriga a refazer a conexao (regex nova, log em outro lugar...)."""
    return (
        server["host"], int(server["ssh_port"] or 22), server["ssh_user"],
        server["service"], _valor_guardado(server, "log_path"),
        _valor_guardado(server, "join_re"), _valor_guardado(server, "leave_re"),
    )


def streams_desejados(servidores, cfg) -> dict[int, tuple]:
    """Quais servidores merecem uma conexao de log aberta, e com que assinatura."""
    if not (LOG_STREAM and cfg["eventos"] & {"jogador-entrou", "jogador-saiu"}):
        return {}
    # So quem conta por log: A2S e HTTP ja respondem de graca na volta curta, e abrir uma
    # conexao permanente para eles seria pagar por nada.
    return {int(s["id"]): _assinatura_de_stream(s) for s in servidores
            if player_source(s) == "log" and _valor_guardado(s, "join_re")}


class _LogStream:
    """Uma conexao SSH longa ouvindo o log de UM servidor."""

    def __init__(self, server, assinatura):
        # Row nao atravessa thread (ela pertence a conexao do request): copia.
        self.dados = dict(server)
        self.sid = int(server["id"])
        self.assinatura = assinatura
        self.proc: subprocess.Popen | None = None
        self.parar = threading.Event()
        self.ultimo_disparo = 0.0
        self.erro = ""
        # Erro de configuracao (regex que nao compila, caminho de log invalido) nao se
        # resolve tentando de novo. Sem esta marca o supervisor recriaria a thread a cada
        # volta, para ela morrer igual — um laco que so enche o log de erro.
        self.desistiu = False
        self.thread = threading.Thread(target=self._roda, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.parar.set()
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def vivo(self) -> bool:
        return self.thread.is_alive()

    def _roda(self) -> None:
        while not self.parar.is_set():
            try:
                self._acompanha()
            # A thread nao morre por um tropeco.
            except Exception as exc:  # noqa: BLE001
                self.erro = str(exc)
                app.logger.exception("o acompanhamento de log de '%s' caiu",
                                     self.dados.get("name"))
            # Servidor desligado nao pode virar um laco de SSH por segundo.
            if self.parar.wait(LOG_STREAM_RETRY):
                return

    def _desiste(self, motivo: str) -> None:
        self.erro = motivo
        self.desistiu = True
        self.parar.set()

    def _acompanha(self) -> None:
        # Cadastro torto para aqui: nao adianta reconectar contra um regex que nao compila.
        try:
            entrar = compile_pattern(self.dados.get("join_re"), "entrada")
            sair = compile_pattern(self.dados.get("leave_re"), "saida")
            alvo = log_path_valido(self.dados.get("log_path") or "")
        except (QueryError, ValueError) as exc:
            return self._desiste(str(exc))
        if not entrar:
            return self._desiste("sem padrao de entrada, nao ha o que ouvir")
        # Sem multiplexar: esta conexao fica de pe por horas, e a mestre compartilhada
        # existe justamente para as chamadas curtas do monitor.
        argv = ssh_argv(
            self.dados, connect_timeout=10,
            extra=("-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3"),
        ) + [q("bash", "-lc", LOG_FOLLOW_SCRIPT, "gp", self.dados["service"], alvo)]
        self.proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", bufsize=1,
        )
        # Guardado numa variavel local: `self.proc.stdout` e Optional (Popen sem PIPE
        # nao tem saida), e e daqui que sai o laco que fica horas lendo.
        saida = self.proc.stdout
        if saida is None:
            return self._desiste("nao consegui abrir a saida do ssh")
        self.erro = ""
        try:
            for linha in saida:
                if self.parar.is_set():
                    break
                if _linha_de_jogador(linha, entrar, sair):
                    self._confere()
        finally:
            self.stop_proc()

    def stop_proc(self) -> None:
        proc, self.proc = self.proc, None
        if not proc:
            return
        for fluxo in (proc.stdout, proc.stderr):
            try:
                if fluxo:
                    fluxo.close()
            except OSError:
                pass
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)      # sem isto sobra zumbi a cada reconexao
        except subprocess.TimeoutExpired:
            proc.kill()

    def _confere(self) -> None:
        """A linha chegou: refaz a contagem pelo caminho normal e avisa se mudou."""
        agora = time.monotonic()
        if agora - self.ultimo_disparo < LOG_STREAM_DEBOUNCE:
            return                     # um grupo entrando junto e UMA conferida
        self.ultimo_disparo = agora
        anterior = _estado_monitor.get(self.sid)
        if anterior is None:
            return                     # sem linha de base ainda: a volta do monitor faz
        # O cache guarda o numero de ANTES da linha que acabou de chegar.
        with _players_lock:
            _players_cache.pop(self.sid, None)
        conn = _connect()              # esta thread vive fora do contexto do request
        try:
            cfg = webhook_config(conn)
            with lock_de_jogadores(self.sid):
                _alerta_de_jogadores(conn, self.dados, anterior.get("service", ""),
                                     anterior, cfg)
        finally:
            conn.close()


def streams_vivos() -> int:
    """Quantas conexoes de log estao mesmo ouvindo agora (para a tela nao mentir)."""
    with _streams_lock:
        return sum(1 for s in _streams.values() if s.vivo())


def supervisiona_streams() -> int:
    """Liga, desliga e ressuscita as conexoes de log. Devolve quantas ficaram registradas."""
    conn = db()
    servidores = conn.execute(SQL_ALL_SERVERS).fetchall()
    desejados = streams_desejados(servidores, webhook_config(conn))
    por_id = {int(s["id"]): s for s in servidores}

    with _streams_lock:
        atuais = list(_streams.items())
    for sid, stream in atuais:
        # Sai quem deixou de ser desejado e quem mudou de configuracao (regex nova, log em
        # outro caminho). Thread morta tambem sai, para o passo abaixo levantar de novo —
        # menos quando ela desistiu por cadastro invalido, que recriar nao conserta: essa
        # fica de lapide ate alguem arrumar o cadastro e a assinatura mudar.
        trocou = sid not in desejados or desejados[sid] != stream.assinatura
        if trocou or (not stream.vivo() and not stream.desistiu):
            stream.stop()
            with _streams_lock:
                _streams.pop(sid, None)

    for sid, assinatura in desejados.items():
        with _streams_lock:
            if sid in _streams:
                continue
            novo = _LogStream(por_id[sid], assinatura)
            _streams[sid] = novo
        novo.start()

    with _streams_lock:
        return len(_streams)


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

SCHEDULE_KINDS = ("diario", "semanal", "intervalo")
SCHEDULE_ACTIONS = ("restart", "stop", "start", "update", "backup")
DIAS_SEMANA = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
# "toda segunda" mas "todo sabado": os dias de semana vem de "segunda-feira" (feminino),
# sabado e domingo sao masculinos.
ARTIGO_DIA = ("toda", "toda", "toda", "toda", "toda", "todo", "todo")
EVERY_HOURS_MAX = 168  # uma semana


def agora_local() -> datetime:
    """Hora local do painel, com fuso. E o relogio que o agendamento enxerga."""
    return datetime.now().astimezone().replace(microsecond=0)


def _parse_dt(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def rotulo_agendamento(sched) -> str:
    """Como a tarefa e descrita na tela e no historico."""
    hora = f"{int(sched['hour']):02d}:{int(sched['minute']):02d}"
    if sched["kind"] == "intervalo":
        horas = int(sched["every_hours"])
        return f"a cada {horas}h" if horas != 1 else "a cada hora"
    if sched["kind"] == "semanal":
        indice = int(sched["weekday"]) % 7
        return f"{ARTIGO_DIA[indice]} {DIAS_SEMANA[indice]} as {hora}"
    return f"todo dia as {hora}"


def ocorrencia_anterior(sched, agora: datetime) -> datetime | None:
    """Ultimo horario em que esta tarefa deveria ter rodado ('intervalo' nao tem)."""
    if sched["kind"] == "intervalo":
        return None
    alvo = agora.replace(hour=int(sched["hour"]), minute=int(sched["minute"]),
                         second=0, microsecond=0)
    if sched["kind"] == "semanal":
        atras = (agora.weekday() - int(sched["weekday"])) % 7
        alvo -= timedelta(days=atras)
        if alvo > agora:
            alvo -= timedelta(days=7)
        return alvo
    if alvo > agora:
        alvo -= timedelta(days=1)
    return alvo


def venceu(sched, agora: datetime) -> bool:
    """A tarefa deveria disparar agora?"""
    ultimo = _parse_dt(sched["last_run"])
    if sched["kind"] == "intervalo":
        if ultimo is None:
            return True
        return (agora - ultimo) >= timedelta(hours=max(1, int(sched["every_hours"])))

    alvo = ocorrencia_anterior(sched, agora)
    if alvo is None:
        return False  # so 'intervalo' nao tem ocorrencia, e ele ja saiu acima
    if ultimo is not None and ultimo >= alvo:
        return False  # esta ocorrencia ja rodou
    # Atrasada demais: o painel estava fora do ar quando a hora passou. Nao dispara e nao
    # anota nada — na proxima ocorrencia a conta acima volta a fechar sozinha.
    return (agora - alvo).total_seconds() <= SCHEDULE_GRACE


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


_scheduler_started = False
_scheduler_lock = threading.Lock()


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

    Cada tarefa vai no SEU try. Dividindo um try so, uma agenda quebrada levava junto o
    monitor e as amostras: a excecao subia na primeira tarefa e as outras tres nunca
    rodavam — para sempre, porque a tarefa quebrada quebrava de novo a cada volta. Por
    fora o painel parecia inteiro, e o botao de testar webhook (que nao passa por aqui)
    continuava funcionando e afastando a suspeita do lugar certo.
    """
    for nome, tarefa in (("agendamentos", roda_agendamentos),
                         ("monitor", monitora_servidores),
                         ("log-em-tempo-real", supervisiona_streams),
                         ("amostras", coleta_amostras),
                         ("limpeza", limpa_historico)):
        try:
            tarefa()
        # Uma tarefa nao derruba as outras.
        except Exception:  # noqa: BLE001
            _falha_do_relogio(nome)


def _scheduler_loop() -> None:
    while True:
        time.sleep(SCHEDULE_TICK)
        try:
            # Contexto de aplicacao: e o que faz o db() desta thread funcionar como o das
            # rotas (conexao propria, fechada no fim pelo teardown).
            with app.app_context():
                _scheduler_tick()
        # A thread nao pode morrer por causa de um tick.
        except Exception:  # noqa: BLE001
            app.logger.exception("falha no agendador")


def start_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    threading.Thread(target=_scheduler_loop, daemon=True).start()


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

    with _players_lock:
        _players_cache.pop(sid, None)
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
    with _players_lock:
        _players_cache.pop(sid, None)
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


def _caminhos_backup(valor: str, errors: list[str]) -> str:
    """Le a lista do que entra no backup (um caminho absoluto por linha).

    Vazio e a resposta certa para a maioria dos cadastros: sem nada aqui o backup leva a
    pasta de configuracao do servidor, que e onde o save costuma morar.
    """
    caminhos: list[str] = []
    for linha in (valor or "").replace(",", "\n").splitlines():
        bruto = linha.strip()
        if not bruto:
            continue
        try:
            limpo = clean_path(bruto)
        except ValueError as exc:
            errors.append(f"Caminho de backup invalido ({bruto}): {exc}")
            continue
        if limpo == "/":
            errors.append("Backup da raiz nao: aponte a pasta do save ou da configuracao.")
            continue
        if limpo not in caminhos:
            caminhos.append(limpo)
    if len(caminhos) > BACKUP_PATHS_MAX:
        errors.append(f"No maximo {BACKUP_PATHS_MAX} caminhos de backup por servidor.")
        caminhos = caminhos[:BACKUP_PATHS_MAX]
    return "\n".join(caminhos)


CAMINHO_JSON_RE = re.compile(r"^[A-Za-z0-9_.\[\]-]{0,120}$")


def _campo(form, nome: str, teto: int) -> str:
    """Um campo de texto do formulario: sem espacos nas pontas e com teto de tamanho."""
    return (form.get(nome, "") or "").strip()[:teto]


def _url_ou_erro(bruto: str, erro: str, errors: list[str]) -> str:
    """URL valida, ou string vazia com o erro anotado. Vazio nao e erro: e "nao usa"."""
    if bruto and not URL_RE.match(bruto):
        errors.append(erro)
        return ""
    return bruto


def _json_ou_erro(bruto: str, rotulo: str, errors: list[str]) -> str:
    """Corpo JSON valido, ou string vazia com o erro anotado."""
    if not bruto:
        return ""
    try:
        json.loads(bruto)
    except ValueError as exc:
        errors.append(f"{rotulo} nao e JSON valido: {exc}.")
        return ""
    return bruto


def _caminhos_json(form, errors: list[str]) -> dict:
    """Os tres caminhos de navegacao na resposta (lista, contagem, token)."""
    caminhos = {}
    for campo, rotulo in (("http_list_path", "lista"), ("http_count_path", "contagem"),
                          ("http_token_path", "token")):
        texto = _campo(form, campo, HTTP_PATH_MAX)
        if texto and not CAMINHO_JSON_RE.match(texto):
            errors.append(f"Caminho da {rotulo} invalido (use algo como 'data.players').")
            texto = ""
        caminhos[campo] = texto
    return caminhos


def _campos_http(form, errors: list[str]) -> dict:
    """Le e confere os campos da chamada HTTP (URL, autenticacao, corpo, caminhos)."""
    url = _url_ou_erro(
        _campo(form, "http_url", HTTP_URL_MAX),
        "URL da API invalida (ex.: http://127.0.0.1:8212/v1/api/players).", errors,
    )
    corpo = _json_ou_erro(
        _campo(form, "http_body", HTTP_BODY_MAX), "Corpo da requisicao", errors,
    )
    caminhos = _caminhos_json(form, errors)

    # Login automatico: os tres campos andam juntos. Preencher so parte deles quase
    # sempre e engano, e falhar aqui e melhor do que descobrir na hora da consulta.
    login_url = _url_ou_erro(
        _campo(form, "http_login_url", HTTP_URL_MAX),
        "URL de login invalida (ex.: https://127.0.0.1:7787/api/v1).", errors,
    )
    login_body = _json_ou_erro(
        _campo(form, "http_login_body", HTTP_BODY_MAX), "Corpo do login", errors,
    )
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
        "http_auth": _campo(form, "http_auth", 300),
        "http_body": corpo,
        **caminhos,
    }


def _caminho_log(valor: str | None, errors: list[str]) -> str:
    try:
        return log_path_valido(valor)
    except ValueError as exc:
        errors.append(str(exc).capitalize())
        return ""


def _padrao(valor: str | None, rotulo: str, errors: list[str]) -> str:
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
            "backup_paths": _caminhos_backup(form.get("backup_paths"), errors),
            "log_path": _caminho_log(form.get("log_path"), errors),
            "query_port": _porta(
                form.get("query_port"), 0, 0,
                "Porta de consulta invalida (use 0 para desligar).", errors,
            ),
            "player_source": origem,
            "join_re": _padrao(form.get("join_re"), "entrada", errors),
            "leave_re": _padrao(form.get("leave_re"), "saida", errors),
            "error_re": _padrao(form.get("error_re"), "erro", errors),
            **_campos_http(form, errors),
        },
        errors,
    )


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
                with _players_lock:
                    _players_cache.pop(sid, None)
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


def list_dir(server: Servidor, path: str) -> tuple[list[dict], bool]:
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


def stat_file(server: Servidor, path: str) -> dict:
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


def read_file(server: Servidor, path: str) -> dict:
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


# $1 = pasta dos backups, $2 = prefixo do servidor, $3 = quantas copias manter,
# $4 = sufixo do nome (a copia de seguranca do restore usa isto), $5.. = o que guardar.
BACKUP_SCRIPT = r"""
set -e
dir=$1
nome=$2
manter=$3
sufixo=$4
shift 4
[ $# -gt 0 ] || { echo "nenhuma pasta para guardar" >&2; exit 3; }

# Caminho que ainda nao existe NAO e erro: a pasta de save so nasce quando alguem entra
# no servidor pela primeira vez, e o cadastro do jogo ja aponta para ela. Cada ausente
# vira um aviso e os demais continuam entrando; so para se nao sobrar nenhum.
# (Roda os argumentos: tira o primeiro, e se ele existir devolve no fim da lista.)
n=$#
i=0
while [ "$i" -lt "$n" ]; do
  p=$1
  shift
  i=$((i + 1))
  if [ -e "$p" ]; then
    set -- "$@" "$p"
  else
    echo "ignorado (ainda nao existe): $p"
  fi
done
[ $# -gt 0 ] || { echo "nada a guardar: nenhum dos caminhos existe no container" >&2; exit 3; }
mkdir -p -- "$dir"

# Espaco livre x tamanho do alvo. O .tar.gz sai bem menor que o original, entao esta
# margem e folgada de proposito: encher o disco do container derruba o jogo junto.
precisa=$(du -sk -- "$@" 2>/dev/null | awk '{ t += $1 } END { print t+0 }')
livre=$(df -Pk -- "$dir" | awk 'NR>1 { print $4; exit }')
if [ "${livre:-0}" -lt "${precisa:-0}" ]; then
  echo "sem espaco em $dir: o alvo ocupa ${precisa}KB e sobram ${livre}KB" >&2
  exit 4
fi

alvo="$dir/$nome-$(date +%Y%m%d-%H%M%S)$sufixo.tar.gz"
tmp="$alvo.parcial"
lista=$(mktemp)
trap 'rm -f "$tmp" "$lista"' EXIT
# Caminho absoluto vira relativo dentro do tar (-C /): e o que faz o restore devolver
# cada arquivo exatamente de onde ele saiu.
for p in "$@"; do printf '%s\n' "${p#/}" >> "$lista"; done

# tar sai com 1 quando um arquivo muda durante a leitura — normal com o servidor ligado,
# e nao invalida o backup. So o codigo 2 (erro de verdade) aborta.
set +e
tar -czf "$tmp" --warning=no-file-changed -C / -T "$lista"
rc=$?
set -e
[ "$rc" -le 1 ] || { echo "tar falhou (codigo $rc)" >&2; exit 5; }
[ "$rc" -eq 1 ] && echo "aviso: algum arquivo mudou durante a copia (servidor ligado) - o backup vale, mas parar o servidor da uma copia mais fiel"

mv -- "$tmp" "$alvo"
echo "backup pronto: $alvo ($(stat -Lc %s -- "$alvo") bytes)"

# Retencao: mantem as N copias mais novas DESTE servidor e apaga o resto.
if [ "$manter" -gt 0 ]; then
  ls -1t -- "$dir/$nome-"*.tar.gz 2>/dev/null | tail -n +$((manter + 1)) | while IFS= read -r velho; do
    rm -f -- "$velho" && echo "retencao: apagado $(basename -- "$velho")"
  done
fi
"""

# $1 = pasta dos backups, $2 = prefixo do servidor.
BACKUP_LIST_SCRIPT = r"""
set -e
dir=$1
nome=$2
[ -d "$dir" ] || exit 0
# Nome primeiro: como ele comeca com a data, o sort reverso ja poe o mais novo em cima.
find "$dir" -maxdepth 1 -type f -name "$nome-*.tar.gz" \
  -printf '%f\t%s\t%TY-%Tm-%Td %TH:%TM\n' 2>/dev/null | LC_ALL=C sort -r | head -n "$3"
"""

# $1 = pasta dos backups, $2 = nome do arquivo, $3 = unidade systemd do jogo.
RESTORE_SCRIPT = r"""
set -e
dir=$1
arq=$2
unit=$3
# O nome vem da tela: barra aqui deixaria escolher qualquer .tar.gz do container.
case "$arq" in
  ''|*/*|*..*) echo "nome de backup invalido" >&2; exit 3 ;;
esac
f="$dir/$arq"
[ -f "$f" ] || { echo "backup nao encontrado: $arq" >&2; exit 3; }
# Confere ANTES de parar o servidor: descobrir que o arquivo esta corrompido com o jogo
# ja parado e a pior hora possivel.
gzip -t -- "$f" 2>/dev/null || { echo "arquivo corrompido (gzip nao le): $arq" >&2; exit 4; }
tar -tzf "$f" >/dev/null 2>&1 || { echo "arquivo corrompido (tar nao le): $arq" >&2; exit 4; }

estava=$(systemctl is-active "$unit" 2>/dev/null || true)
if [ "$estava" = active ]; then
  systemctl stop "$unit"
  echo "servidor parado para a restauracao"
fi

tar -xzf "$f" -C /
echo "restaurado: $arq"

# Servidor que ja estava parado continua parado: restaurar nao e ligar.
if [ "$estava" = active ]; then
  systemctl start "$unit"
  echo "servidor religado"
fi
"""

# $1 = pasta dos backups, $2 = nome do arquivo.
BACKUP_DELETE_SCRIPT = r"""
set -e
dir=$1
arq=$2
case "$arq" in
  ''|*/*|*..*) echo "nome de backup invalido" >&2; exit 3 ;;
esac
f="$dir/$arq"
[ -f "$f" ] || { echo "backup nao encontrado: $arq" >&2; exit 3; }
sz=$(stat -Lc %s -- "$f")
rm -f -- "$f"
echo "backup apagado: $arq ($sz bytes)"
"""

# $1 = destino final. O conteudo vem CRU pela entrada padrao (sem base64: o arquivo pode
# ter gigabytes, e codificar inflaria 33% a toa).
UPLOAD_SCRIPT = r"""
set -e
f=$1
d=$(dirname -- "$f")
[ -d "$d" ] || { echo "pasta nao existe: $d" >&2; exit 3; }
[ -d "$f" ] && { echo "ja existe uma PASTA com esse nome" >&2; exit 4; }
t=$(mktemp "$d/.gamepanel-XXXXXX")
trap 'rm -f "$t"' EXIT
cat > "$t"
if [ -e "$f" ]; then
  [ -f "$f" ] || { echo "o destino nao e um arquivo comum" >&2; exit 4; }
  cp -a -- "$f" "$f.$(date +%Y%m%d-%H%M%S).bak"
  # cat > por cima em vez de mv: preserva dono e permissao do arquivo que ja estava la.
  cat "$t" > "$f"
else
  cat "$t" > "$f"
  chmod 0644 -- "$f"
  # Arquivo novo herda o dono da pasta: o jogo roda como 'steam' e precisa poder ler.
  chown --reference="$d" -- "$f" 2>/dev/null || true
fi
echo "enviado: $f ($(stat -Lc %s -- "$f") bytes)"
"""


def ssh_stream_in(server, remote_cmd: str, origem, timeout: int) -> str:
    """Executa um comando remoto alimentando a entrada dele a partir de `origem`.

    Diferente do `ssh_run(stdin_data=...)`, que precisa do conteudo inteiro na memoria:
    aqui os bytes passam em pedacos, do arquivo que o navegador enviou direto para o
    `cat` do outro lado. E o que permite subir um mod ou um save de varios GB.
    """
    argv = ssh_argv(server, connect_timeout=10) + [remote_cmd]
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raise RemoteError(f"falha ao executar ssh: {exc}")

    # Numa variavel local porque `Popen.stdin` e Optional no tipo (Popen sem PIPE nao
    # tem entrada) e porque ela e zerada no `finally` la embaixo - o `close()` de la
    # precisa falar do MESMO objeto que o laco usou.
    entrada = proc.stdin
    if entrada is None:
        raise RemoteError("nao consegui abrir a entrada do ssh")

    try:
        while True:
            chunk = origem.read(UPLOAD_CHUNK)
            if not chunk:
                break
            entrada.write(chunk)
    except OSError:
        # O outro lado desistiu (sem espaco, sem permissao): o motivo esta no stderr,
        # entao nao adianta reclamar do cano quebrado aqui. BrokenPipeError - o caso
        # tipico - ja e um OSError, entao listar os dois nao pegava nada a mais.
        pass
    finally:
        # Fechar a entrada e o que faz o `cat` remoto terminar. A referencia tem de ir
        # junto: o communicate() abaixo daria flush num arquivo ja fechado e estouraria
        # ValueError com o arquivo JA gravado do outro lado — erro na tela, upload feito.
        try:
            entrada.close()
        except OSError:
            pass
        proc.stdin = None

    try:
        saida, erro = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RemoteError(f"tempo esgotado ({timeout}s) enviando para {server['host']}")
    if proc.returncode != 0:
        detalhe = (erro or saida or b"").decode("utf-8", "replace").strip()
        raise RemoteError(detalhe or f"falha ao enviar (exit {proc.returncode})")
    return saida.decode("utf-8", "replace").strip()


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


def write_file(server: Servidor, path: str, data: bytes) -> str:
    """Grava o arquivo no container (com .bak, dono e permissao preservados)."""
    proc = ssh_run(
        server, q("bash", "-lc", WRITE_SCRIPT, "gp", path), timeout=120,
        stdin_data=base64.b64encode(data),
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao gravar")
    return proc.stdout.strip()


def delete_file(server: Servidor, path: str) -> str:
    """Apaga um arquivo (ou pasta vazia) no container. Nao tem volta."""
    proc = ssh_run(server, q("bash", "-lc", DELETE_SCRIPT, "gp", path), timeout=60)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao apagar")
    return proc.stdout.strip()


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
    """Joga o arquivo do container direto para o navegador, sem passar por disco.

    E `cat` na outra ponta lido em pedacos: um save de varios GB desce sem o painel
    guardar nada em memoria.
    """
    argv = ssh_argv(server) + [q("cat", "--", path)]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # `Popen.stdout` e Optional no tipo; aqui ele existe porque o PIPE foi pedido acima.
    saida = proc.stdout
    if saida is None:
        raise RemoteError("nao consegui abrir a saida do ssh")

    def gerar():
        try:
            while True:
                chunk = saida.read(DOWNLOAD_CHUNK)
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
    """O que entra no backup deste servidor.

    Sem nada cadastrado vale a pasta de configuracao, que e onde o save costuma morar —
    e o padrao que evita cadastrar servidor nenhum so para ter backup.
    """
    escolhidos = [ln.strip() for ln in (server["backup_paths"] or "").splitlines() if ln.strip()]
    if escolhidos:
        return escolhidos[:BACKUP_PATHS_MAX]
    padrao = (server["config_path"] or "").strip()
    return [padrao] if padrao else []


def backup_prefix(server: Servidor) -> str:
    """Prefixo dos arquivos deste servidor: e ele que separa (e limita) as copias.

    Sai do nome da unidade systemd, que ja e unica por container. O saneamento importa
    porque o prefixo entra num glob de shell la do outro lado.
    """
    bruto = (server["service"] or "jogo").rsplit(".service", 1)[0]
    limpo = re.sub(r"[^A-Za-z0-9_-]", "-", bruto).strip("-")
    return limpo or "jogo"


BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.tar\.gz$")


def _backup_ou_400(nome: str) -> str:
    """Confere o nome que voltou da tela antes de ele entrar num comando remoto."""
    nome = (nome or "").strip()
    if not BACKUP_NAME_RE.match(nome) or ".." in nome:
        abort(400, "nome de backup invalido")
    return nome


def list_backups(server: Servidor) -> list[dict]:
    proc = ssh_run(
        server,
        q("bash", "-lc", BACKUP_LIST_SCRIPT, "gp", BACKUP_DIR, backup_prefix(server),
          str(BACKUP_LIST_MAX)),
        timeout=40,
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao listar os backups")
    copias: list[dict] = []
    for linha in proc.stdout.splitlines():
        partes = linha.split("\t", 2)
        if len(partes) != 3:
            continue
        copias.append({
            "name": partes[0],
            "size": int(partes[1]) if partes[1].isdigit() else 0,
            "mtime": partes[2],
            # A copia que o proprio painel tira antes de restaurar: some no meio das
            # outras se nao for marcada, e e justamente a que salva quem restaurou errado.
            "seguranca": partes[0].endswith("-antes-de-restaurar.tar.gz"),
        })
    return copias


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
    """Monta o comando remoto do backup. Usado pela tela, pelo restore e pelo agendador."""
    return q("bash", "-lc", BACKUP_SCRIPT, "gp", BACKUP_DIR,
             backup_prefix(server), str(BACKUP_KEEP), sufixo, *caminhos)


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
        saida = ssh_output(
            server, q("bash", "-lc", BACKUP_DELETE_SCRIPT, "gp", BACKUP_DIR, nome), timeout=40
        )
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

# Espelho do broker/catalogo.RECEITAS: so para desenhar as caixas do formulario. Quem
# decide o que vale e o broker, que recusa receita que nao conhece.
BROKER_RECEITAS = ("wine", "proton", "steamclient-sdk64")
_NUMERO_RE = re.compile(r"[0-9]{1,10}", re.ASCII)


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


def _cadastra_servidor_do_broker(r: dict) -> int:
    """Registra no painel a instancia que o broker acabou de criar. Devolve o id do servidor.

    Passa pelo mesmo `ensure_server` do deploy, entao a tela de configuracao ja abre pronta.
    """
    host = str(r["host"])
    servico = str(r["service"])
    if not HOST_RE.match(host) or not UNIT_RE.match(servico):
        raise ValueError("o broker devolveu host ou servico com formato invalido")
    ensure_server(ServidorDoDeploy(
        name=str(r["name"])[:80], host=host, service=servico,
        game_port=" ".join(str(p) for p in r.get("ports") or []),
        notes=str(r.get("notes", "")),
        config_path=str(r.get("config_path", "")),
        config_files="\n".join(r.get("config_files") or []),
        backup_paths="\n".join(r.get("backup_paths") or []),
        join_re=str(r.get("join_re", "")), leave_re=str(r.get("leave_re", "")),
        log_path=str(r.get("log_path", "")), query_port=int(r.get("query_port") or 0),
        player_source=str(r.get("player_source", "")), broker_id=int(r.get("broker_id") or 0),
    ))
    conn = _connect()
    try:
        linha = conn.execute("SELECT id FROM servers WHERE host = ? AND ssh_port = 22", (host,)).fetchone()
    finally:
        conn.close()
    if linha is None:
        raise ValueError("o servidor nao foi gravado")
    return int(linha["id"])


def _conclui_operacao_do_broker(job_id: int, op: dict) -> None:
    log = str(op.get("log", ""))
    if op.get("estado") != "ok":
        _fecha_job(job_id, "error", log, codigo=1)
        return
    try:
        sid = _cadastra_servidor_do_broker(op.get("resultado") or {})
    except (KeyError, TypeError, ValueError, sqlite3.Error) as erro:
        # A instancia EXISTE no Proxmox: o texto precisa dizer isso, senao parece que nada foi feito.
        _fecha_job(job_id, "error", f"{log}\nA instancia foi criada, mas nao consegui cadastra-la "
                   f"no painel: {erro}", codigo=1)
        return
    _fecha_job(job_id, "ok", f"{log}\nServidor cadastrado no painel (id {sid}).", codigo=0, server_id=sid)


def acompanha_operacao(job_id: int, op_id: str, dormir=time.sleep) -> None:
    """Le a operacao do broker ate ela terminar, gravando o log no job a cada volta.

    E isso que faz a tela do job mostrar o progresso ao vivo: o `start_job` comum so grava
    a saida no fim, e uma criacao de servidor leva minutos de download.
    """
    limite = time.monotonic() + JOB_TIMEOUT
    falhas = 0
    log = ""
    while time.monotonic() < limite:
        try:
            op = broker_client.operacao(op_id)
        except broker_client.BrokerError as erro:
            falhas += 1
            if falhas >= BROKER_FALHAS_MAX:
                _fecha_job(job_id, "error", f"{log}\nPerdi o contato com o broker: {erro}")
                return
            dormir(BROKER_POLL)
            continue
        falhas = 0
        log = str(op.get("log", ""))[-200000:]
        _atualiza_job(job_id, output=log)
        if op.get("estado") != "executando":
            _conclui_operacao_do_broker(job_id, op)
            return
        dormir(BROKER_POLL)
    _fecha_job(job_id, "error", f"{log}\nTempo esgotado esperando o broker.")


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


def _linhas(texto: str) -> list[str]:
    return [p.strip() for p in (texto or "").replace(",", "\n").splitlines() if p.strip()]


def _jogo_do_form(form) -> tuple[dict, list[str]]:
    """Le o formulario de jogo novo. So converte tipos: quem valida de verdade e o broker
    (ele recusa campo desconhecido, caminho fora de /opt/game, comando escondido...)."""
    erros: list[str] = []
    dados: dict = {}
    for campo in ("chave", "nome", "plataforma", "start_script", "start_args", "config_path",
                  "log_path", "join_re", "leave_re", "player_source"):
        valor = (form.get(campo) or "").strip()
        if valor:
            dados[campo] = valor
    for campo, rotulo in (("app_id", "App ID"), ("porta_jogo", "Porta do jogo"),
                          ("porta_query", "Porta de consulta"), ("porta_extra", "Porta extra"),
                          ("memoria_mb", "Memoria"),
                          ("cores", "CPUs"), ("disco_gb", "Disco")):
        bruto = (form.get(campo) or "").strip()
        if not bruto:
            continue
        if _NUMERO_RE.fullmatch(bruto):
            dados[campo] = int(bruto)
        else:
            erros.append(f"{rotulo} deve ser um numero.")
    dados["portas"] = [p for p in re.split(r"[\s,]+", (form.get("portas") or "").strip()) if p]
    dados["config_files"] = _linhas(form.get("config_files", ""))
    dados["backup_paths"] = _linhas(form.get("backup_paths", ""))
    dados["receitas"] = [r for r in form.getlist("receitas") if r in BROKER_RECEITAS]
    dados["deslocavel"] = form.get("deslocavel") == "1"
    return dados, erros


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

CHART_W, CHART_H = 720, 220
CHART_L, CHART_R, CHART_T, CHART_B = 44, 64, 12, 28
# Duas amostras separadas por mais que isto viram um BURACO na linha, nao um traco reto
# atravessando: servidor que passou duas horas fora do ar nao "andou em linha reta".
CHART_GAP = 2.5
CHART_TICKS = 5
# Distancia minima entre dois rotulos de ponta para os dois continuarem legiveis.
PONTA_MIN = 16

CHART_RANGES = ((6, "6 horas"), (24, "24 horas"), (168, "7 dias"))

# Slots 1 e 2 do catalogo categorico (versao para fundo escuro), validados contra o fundo
# do painel: separacao para daltonismo muito acima do minimo. A cor fica na LINHA; texto,
# eixo e legenda usam as cores de texto do painel.
CHART_CPU = "#3987e5"
CHART_MEM = "#d95926"

# Tetos "limpos" para o eixo de jogadores: 3 jogadores nao merecem um eixo ate 3.
TETOS = (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 64, 80, 100,
         150, 200, 300, 500, 750, 1000)


def _teto_limpo(pico: float) -> int:
    for teto in TETOS:
        if pico <= teto:
            return teto
    return int(pico) + 1


def _segmentos_da_serie(amostras, chave: str, px, py) -> tuple[list[list[str]], dict | None]:
    """Uma serie vira uma lista de SEGMENTOS de coordenadas, mais a ponta.

    Segmentos, e nao uma linha so, porque o grafico tem buracos de dois tipos: amostra
    sem valor para esta serie (a contagem de jogadores desligada, por exemplo) e painel
    que ficou fora do ar entre duas amostras (ver CHART_GAP). Emendar por cima dos dois
    desenharia uma reta que afirma algo que ninguem mediu.
    """
    segmentos: list[list[str]] = []
    atual: list[str] = []
    anterior = None
    ponta = None

    def fecha():
        nonlocal atual
        if atual:
            segmentos.append(atual)
        atual = []

    for quando, valores in amostras:
        valor = valores.get(chave)
        if valor is None:
            fecha()
            anterior = None
            continue
        if anterior is not None and (quando - anterior).total_seconds() > SAMPLE_EVERY * CHART_GAP:
            fecha()
        atual.append(f"{px(quando)},{py(valor)}")
        ponta = {"x": px(quando), "y": py(valor), "valor": valor}
        anterior = quando

    fecha()
    return segmentos, ponta


def monta_grafico(amostras, series, teto: float, inicio, fim, formato_tempo: str) -> dict:
    """Transforma as amostras em coordenadas prontas para o SVG.

    `series` diz quais colunas desenhar; cada uma vira uma lista de SEGMENTOS, porque o
    grafico pode ter buracos (ver CHART_GAP).
    """
    span = max(1.0, (fim - inicio).total_seconds())
    largura = CHART_W - CHART_L - CHART_R
    alto = CHART_H - CHART_T - CHART_B

    def px(quando) -> float:
        return round(CHART_L + largura * ((quando - inicio).total_seconds() / span), 1)

    def py(valor) -> float:
        fatia = 0.0 if teto <= 0 else min(1.0, max(0.0, valor / teto))
        return round(CHART_T + alto * (1 - fatia), 1)

    linhas = []
    for serie in series:
        segmentos, ponta = _segmentos_da_serie(amostras, serie["chave"], px, py)
        if not segmentos:
            continue
        linhas.append({
            "chave": serie["chave"],
            "rotulo": serie["rotulo"],
            "cor": serie["cor"],
            "sufixo": serie.get("sufixo", ""),
            # Um segmento de um ponto so nao vira polyline (nao teria comprimento): vira
            # um ponto desenhado, senao a amostra solta sumiria da tela.
            "tracos": [" ".join(s) for s in segmentos if len(s) > 1],
            "pontos": [s[0] for s in segmentos if len(s) == 1],
            "ponta": ponta,
        })

    # Rotulo direto so vale enquanto as pontas nao se encostam. Quando as linhas
    # convergem no canto direito, empurrar um rotulo para cima do outro os desgruda das
    # linhas e vira ruido — melhor deixar a legenda, a mira e a tabela carregarem, que e
    # o que elas ja fazem.
    pontas = [l["ponta"]["y"] for l in linhas if l["ponta"]]
    rotula_ponta = all(
        abs(a - b) >= PONTA_MIN
        for i, a in enumerate(pontas) for b in pontas[i + 1:]
    )

    grade = []
    for fatia in (0.0, 0.5, 1.0):
        valor = teto * fatia
        grade.append({
            "y": py(valor),
            "rotulo": f"{valor:g}" + (series[0].get("sufixo", "") if series else ""),
        })

    tempos = []
    for i in range(CHART_TICKS):
        quando = inicio + timedelta(seconds=span * i / (CHART_TICKS - 1))
        tempos.append({"x": px(quando), "rotulo": quando.astimezone().strftime(formato_tempo)})

    return {
        "linhas": linhas,
        "grade": grade,
        "tempos": tempos,
        "vazio": not linhas,
        "rotula_ponta": rotula_ponta,
        "w": CHART_W, "h": CHART_H,
        "l": CHART_L, "r": CHART_W - CHART_R, "t": CHART_T, "b": CHART_H - CHART_B,
        # O que a mira precisa para converter uma coordenada de volta em valor e em hora,
        # sem o painel ter de mandar os dados duas vezes (o SVG ja os carrega).
        "teto": teto,
        "inicio_ms": int(inicio.timestamp() * 1000),
        "span_s": span,
    }


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
    import argparse

    parser = argparse.ArgumentParser(description="Painel de servidores de jogos")
    parser.add_argument("--create-user", metavar="USUARIO")
    # Saida de emergencia: o unico admin perdeu o celular E os codigos de recuperacao.
    parser.add_argument("--reset-2fa", metavar="USUARIO",
                        help="desliga o segundo fator de um usuario (roda no CT do painel)")
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
    parser.add_argument("--backup-paths", default="")
    parser.add_argument("--join-re", default="")
    parser.add_argument("--leave-re", default="")
    parser.add_argument("--log-path", default="")
    parser.add_argument("--player-source", default="")
    parser.add_argument("--notes", default="")
    opts = parser.parse_args()

    if opts.reset_2fa:
        init_db()
        conn = _connect()
        with conn:
            alvo = conn.execute("SELECT id FROM users WHERE username = ?", (opts.reset_2fa,)).fetchone()
            if not alvo:
                raise SystemExit(f"usuario '{opts.reset_2fa}' nao existe")
            conn.execute(
                "UPDATE users SET totp_secret = '', totp_enabled = 0, totp_last_step = 0,"
                " totp_recovery = '' WHERE id = ?", (alvo["id"],))
        print(f"Segundo fator de '{opts.reset_2fa}' desligado.")
    elif opts.create_user:
        if not opts.password:
            raise SystemExit("--create-user exige --password")
        ensure_admin_user(opts.create_user, opts.password, opts.role)
    elif opts.register_server:
        if not opts.server_host or not opts.service:
            raise SystemExit("--register-server exige --server-host e --service")
        # A linha de comando nao aceita quebra de linha com conforto: aqui as listas
        # (arquivos de config, caminhos de backup) vem separadas por virgula.
        def por_virgula(bruto: str) -> str:
            return "\n".join(p.strip() for p in bruto.split(",") if p.strip())

        criado = ensure_server(ServidorDoDeploy(
            name=opts.register_server,
            host=opts.server_host,
            service=opts.service,
            ssh_port=opts.ssh_port,
            ssh_user=opts.ssh_user,
            game_port=opts.game_port,
            notes=opts.notes,
            config_path=opts.config_path,
            config_files=por_virgula(opts.config_files),
            backup_paths=por_virgula(opts.backup_paths),
            join_re=opts.join_re,
            leave_re=opts.leave_re,
            log_path=opts.log_path,
            query_port=opts.query_port,
            player_source=opts.player_source,
        ))
        print(f"servidor '{opts.register_server}' {'cadastrado' if criado else 'atualizado'}"
              f" ({opts.server_host})")
    else:
        start_scheduler()
        retoma_jobs_do_broker()
        app.run(host=opts.host, port=opts.port)
