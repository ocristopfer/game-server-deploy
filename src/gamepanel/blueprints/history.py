"""O historico do painel: tudo o que aconteceu, de todos os servidores."""
from __future__ import annotations

from flask import Blueprint, render_template, request

from gamepanel import app as panel
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("history", __name__)


@bp.get("/history")
@panel.login_required
def index():
    """Tudo o que aconteceu no painel, de todos os servidores.

    O historico por servidor mostra os ultimos 15; e aqui que se responde "quem mexeu
    nisso" e "o que o agendador andou fazendo".
    """
    conn = panel.db()
    servers = servers_repo.all_ordered(conn)
    names = {int(s["id"]): s["name"] for s in servers}

    server_filter = (request.args.get("servidor", "") or "").strip()
    action_filter = (request.args.get("acao", "") or "").strip()
    user_filter = (request.args.get("usuario", "") or "").strip()[:80]
    try:
        page = max(0, int(request.args.get("p", "0")))
    except ValueError:
        page = 0

    where_clause, values = ["1 = 1"], []
    if server_filter.isdigit():
        where_clause.append("server_id = ?")
        values.append(int(server_filter))
    if action_filter in panel.JOB_LABELS:
        where_clause.append("action = ?")
        values.append(action_filter)
    if user_filter:
        where_clause.append("username = ?")
        values.append(user_filter)

    cut, hidden_ones = panel.role_filter()
    sql_where = " AND ".join(where_clause) + cut
    values.extend(hidden_ones)

    # Pede um a mais que o tamanho da pagina: e como se sabe se existe proxima sem contar
    # a tabela inteira.
    lines_of = conn.execute(
        f"SELECT * FROM jobs WHERE {sql_where} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*values, panel.HISTORY_PAGE + 1, page * panel.HISTORY_PAGE),
    ).fetchall()
    has_more = len(lines_of) > panel.HISTORY_PAGE
    jobs = lines_of[:panel.HISTORY_PAGE]

    users = [r[0] for r in conn.execute(
        f"SELECT DISTINCT username FROM jobs WHERE username <> '' {cut} ORDER BY username",
        hidden_ones,
    ).fetchall()]

    return render_template(
        "history.html", jobs=jobs, servers=servers, names=names, users=users,
        actions=sorted(panel.JOB_LABELS), server_filter=server_filter, action_filter=action_filter,
        user_filter=user_filter, page=page, has_more=has_more,
        keep_days=panel.JOBS_KEEP_DAYS,
    )
