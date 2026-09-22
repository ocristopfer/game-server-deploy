"""Esquema do banco do painel: as tabelas, as migracoes e a subida.

`CREATE TABLE IF NOT EXISTS` nao altera tabela que ja existe, entao coluna nova precisa
de um ALTER proprio em `MIGRATIONS` — e por isso as duas listas vivem lado a lado: a
segunda so faz sentido lendo a primeira.

A conexao por REQUEST (o `db()` preso ao `g` do Flask) fica em `app.py`; aqui esta so a
conexao crua, que as threads de fundo tambem usam.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable

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
  name       TEXT NOT NULL DEFAULT '',
  url        TEXT NOT NULL,
  events     TEXT NOT NULL DEFAULT '',
  enabled    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT ''
);

-- Diario de alertas: uma linha por TENTATIVA de envio, e tambem uma por alerta que
-- nasceu sem destino algum. Canal mudo tem duas causas opostas — nada aconteceu, ou
-- aconteceu e nao saiu — e do lado de fora elas sao identicas. Sem este registro a
-- unica saida e adivinhar.
CREATE TABLE IF NOT EXISTS alert_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  event      TEXT NOT NULL DEFAULT '',
  title      TEXT NOT NULL DEFAULT '',
  detail     TEXT NOT NULL DEFAULT '',
  target     TEXT NOT NULL DEFAULT '',
  -- 'enviado', 'falhou', 'sem-destino' ou 'erro-interno'
  status     TEXT NOT NULL DEFAULT '',
  error      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_alert_log_id ON alert_log (id DESC);
"""



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
    # Idioma da tela, por pessoa. Vazio de proposito: quem nunca escolheu segue o que o
    # navegador pede, e nao uma escolha que o painel fez por ela.
    ("users", "lang", "ALTER TABLE users ADD COLUMN lang TEXT NOT NULL DEFAULT ''"),
)


# Colunas que mudaram de NOME. Separadas de `MIGRATIONS` porque a pergunta e outra: ali
# e "a coluna existe?", aqui e "ela ainda tem o nome velho?". Um banco novo nasce com o
# nome novo pelo SCHEMA e nao entra em nenhum dos dois.
#
# `RENAME COLUMN` do SQLite (3.25+) reescreve o indice e as referencias sozinho, e
# preserva os dados — nada de tabela nova mais copia, que e onde se perde linha.
RENAMES = (
    ("webhooks", "nome", "name"),
    ("webhooks", "eventos", "events"),
    ("webhooks", "ativo", "enabled"),
    ("webhooks", "criado_em", "created_at"),
    ("alert_log", "criado_em", "created_at"),
    ("alert_log", "evento", "event"),
    ("alert_log", "titulo", "title"),
    ("alert_log", "detalhe", "detail"),
    ("alert_log", "destino", "target"),
    ("alert_log", "erro", "error"),
)


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    # WAL: o job em background nao trava a leitura da tela.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(db_path: str, webhook_padrao: str, eventos_padrao: str,
            agora: Callable[[], str]) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = connect(db_path)
    with conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                for comando in (ddl if isinstance(ddl, tuple) else (ddl,)):
                    conn.execute(comando)
        for table, old, new in RENAMES:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            # Os dois testes juntos: so renomeia se o velho esta la E o novo nao. Assim
            # rodar de novo nao faz nada, e um banco novo (que ja nasce certo) nem entra.
            if old in cols and new not in cols:
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
        _migra_webhook_unico(conn, webhook_padrao, eventos_padrao, agora)
    conn.close()


def _migra_webhook_unico(conn: sqlite3.Connection, webhook_padrao: str,
                         eventos_padrao: str, agora: Callable[[], str]) -> None:
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
    url = (antigo["value"] if antigo else "").strip() or webhook_padrao.strip()
    if not url:
        return
    ev = conn.execute(
        "SELECT value FROM settings WHERE key = 'webhook_events'"
    ).fetchone()
    conn.execute(
        "INSERT INTO webhooks (name, url, events, enabled, created_at)"
        " VALUES (?, ?, ?, 1, ?)",
        ("Webhook", url, (ev["value"] if ev else eventos_padrao), agora()),
    )


