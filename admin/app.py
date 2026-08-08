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

import hashlib
import hmac
import os
import re
import secrets
import shlex
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from functools import wraps

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

# Console web: executa comandos como root DENTRO do container de jogo escolhido.
# E a funcionalidade mais poderosa do painel — desligue com GAMEPANEL_ALLOW_SHELL=0.
ALLOW_SHELL = os.environ.get("GAMEPANEL_ALLOW_SHELL", "1") == "1"
SHELL_TIMEOUT = int(os.environ.get("GAMEPANEL_SHELL_TIMEOUT", "600"))
SHELL_MAX_LEN = 4000

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
    MAX_CONTENT_LENGTH=64 * 1024,
)

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


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _connect()
    with conn:
        conn.executescript(SCHEMA)
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
    sent = request.form.get("csrf", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, "token CSRF invalido ou expirado — recarregue a pagina")
    return None


@app.context_processor
def _inject():
    return {
        "csrf_token": csrf_token,
        "current_user": session.get("username"),
        "job_label": job_label,
        "allow_shell": ALLOW_SHELL,
    }


# ------------------------------------------------------------------- ssh


class RemoteError(RuntimeError):
    pass


def ssh_run(
    server: sqlite3.Row, remote_cmd: str, timeout: int = QUICK_TIMEOUT
) -> subprocess.CompletedProcess:
    """Executa um comando no container de jogo via SSH.

    `remote_cmd` ja vem montado com shlex.quote pelos helpers abaixo; o SSH o entrega
    inteiro para o shell do destino, entao nada aqui pode vir cru de um formulario.
    """
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-p", str(server["ssh_port"]),
        "-o", "BatchMode=yes",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        # accept-new: aprende a host key no primeiro acesso, mas alerta se ela mudar.
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={min(timeout, 10)}",
        f"{server['ssh_user']}@{server['host']}",
        remote_cmd,
    ]
    try:
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
            {"reachable": False, "service": "desconhecido", "error": "tempo esgotado"},
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


def job_label(action: str) -> str:
    return JOB_LABELS.get(action, action)


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
            return render_template("login.html"), 429
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
        return render_template("login.html"), 401
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def dashboard():
    servers = db().execute("SELECT * FROM servers ORDER BY name").fetchall()
    return render_template(
        "dashboard.html", servers=servers, status=all_status(servers), actions=ACTIONS
    )


@app.get("/api/status")
@login_required
def api_status():
    servers = db().execute("SELECT * FROM servers ORDER BY name").fetchall()
    return jsonify({str(sid): state for sid, state in all_status(servers).items()})


def _form_server(form) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = form.get("name", "").strip()
    host = form.get("host", "").strip()
    ssh_user = form.get("ssh_user", "").strip() or "root"
    service = form.get("service", "").strip()
    port_raw = form.get("ssh_port", "").strip() or "22"

    if not name:
        errors.append("Informe um nome.")
    if not HOST_RE.match(host):
        errors.append("Host invalido (use o IP ou hostname do container).")
    if not USER_RE.match(ssh_user):
        errors.append("Usuario SSH invalido.")
    if service and not service.endswith(".service"):
        service = f"{service}.service"
    if not UNIT_RE.match(service or ""):
        errors.append("Servico invalido (ex.: dragonwilds.service).")
    if not port_raw.isdigit() or not 1 <= int(port_raw) <= 65535:
        errors.append("Porta SSH invalida.")

    return (
        {
            "name": name,
            "host": host,
            "ssh_user": ssh_user,
            "ssh_port": int(port_raw) if port_raw.isdigit() else 22,
            "service": service,
            "game_port": form.get("game_port", "").strip()[:120],
            "notes": form.get("notes", "").strip()[:2000],
        },
        errors,
    )


@app.route("/servers/new", methods=["GET", "POST"])
@login_required
def server_new():
    data = {
        "name": "", "host": "", "ssh_user": "root", "ssh_port": 22,
        "service": "", "game_port": "", "notes": "",
    }
    if request.method == "POST":
        data, errors = _form_server(request.form)
        if not errors:
            try:
                conn = db()
                with conn:
                    conn.execute(
                        "INSERT INTO servers (name, host, ssh_port, ssh_user, service,"
                        " game_port, notes, created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            data["name"], data["host"], data["ssh_port"],
                            data["ssh_user"], data["service"], data["game_port"],
                            data["notes"], now_iso(),
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
    server = db().execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()
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
                        " service=?, game_port=?, notes=? WHERE id=?",
                        (
                            data["name"], data["host"], data["ssh_port"],
                            data["ssh_user"], data["service"], data["game_port"],
                            data["notes"], sid,
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
    server = conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()
    if not server:
        abort(404)
    jobs = conn.execute(
        "SELECT * FROM jobs WHERE server_id = ? ORDER BY id DESC LIMIT 15", (sid,)
    ).fetchall()
    try:
        lines = max(10, min(500, int(request.args.get("lines", "80"))))
    except ValueError:
        lines = 80
    logs, log_error = "", ""
    try:
        logs = ssh_output(
            server,
            q("journalctl", "-u", server["service"], "--no-pager", "-n", str(lines)),
            timeout=30,
        )
    except RemoteError as exc:
        log_error = str(exc)
    return render_template(
        "server_detail.html",
        server=server,
        status=server_status(server),
        jobs=jobs,
        logs=logs,
        log_error=log_error,
        lines=lines,
        actions=ACTIONS,
    )


@app.post("/servers/<int:sid>/action/<action>")
@login_required
def server_action(sid: int, action: str):
    if action not in ACTIONS:
        abort(404)
    server = db().execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()
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
    server = conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()
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
            "SELECT * FROM servers WHERE id = ?", (job["server_id"],)
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
    return render_template("error.html", code=400, message=str(exc)), 400


@app.errorhandler(403)
def _forbidden(exc):
    return render_template("error.html", code=403, message=str(exc)), 403


@app.errorhandler(404)
def _not_found(_exc):
    return render_template("error.html", code=404, message="Pagina nao encontrada."), 404


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
