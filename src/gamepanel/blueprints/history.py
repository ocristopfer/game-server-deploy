"""The panel history: everything that happened, across all servers."""
from __future__ import annotations

from flask import Blueprint, render_template, request

from gamepanel import app as panel
from gamepanel.persistence.repositories import jobs as jobs_repo
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("history", __name__)


@bp.get("/history")
@panel.login_required
def index():
    """Everything that happened on the panel, across all servers.

    The per-server history shows the last 15; this is where "who touched
    this" and "what has the scheduler been doing" get answered.
    """
    conn = panel.db()
    servers = servers_repo.all_ordered(conn)
    names = {int(s["id"]): s["name"] for s in servers}

    server_filter = (request.args.get("server", "") or "").strip()
    action_filter = (request.args.get("action", "") or "").strip()
    user_filter = (request.args.get("user", "") or "").strip()[:80]
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

    # Ask for one more than the page size: that is how we know whether there is a next page
    # without counting the whole table.
    lines_of = jobs_repo.page(conn, sql_where, values,
                              panel.HISTORY_PAGE + 1, page * panel.HISTORY_PAGE)
    has_more = len(lines_of) > panel.HISTORY_PAGE
    jobs = lines_of[:panel.HISTORY_PAGE]

    users = jobs_repo.usernames(conn, cut, hidden_ones)

    return render_template(
        "history.html", jobs=jobs, servers=servers, names=names, users=users,
        actions=sorted(panel.JOB_LABELS), server_filter=server_filter, action_filter=action_filter,
        user_filter=user_filter, page=page, has_more=has_more,
        keep_days=panel.JOBS_KEEP_DAYS,
    )
